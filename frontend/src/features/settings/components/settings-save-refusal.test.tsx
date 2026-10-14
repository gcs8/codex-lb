import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { AutomationsPauseToggle } from "@/features/automations/components/automations-pause-toggle";
import { useAuthStore } from "@/features/auth/hooks/use-auth";
import { SettingsPage } from "@/features/settings/components/settings-page";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import { DashboardSettingsSchema, SettingsUpdateRequestSchema, type SettingsUpdateRequest } from "@/features/settings/schemas";
import { ADMIN_PERMISSIONS, createDashboardSettings } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";

// No mocked hooks or child controls: UI -> payload/schema -> API -> real mutation.
function mount(automations = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/settings?advanced=1"]}>
        {automations ? <AutomationsPauseToggle /> : <SettingsPage />}
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, close: () => { view.unmount(); client.clear(); } };
}

beforeEach(() => {
  useAuthStore.setState({ canWrite: true, permissions: ADMIN_PERMISSIONS, authMode: "standard", passwordManagementEnabled: false, passwordSessionActive: false, user: null });
});

describe("shared settings save refusal ownership", () => {
  it.each([
    { status: 422, code: "validation_error", message: "Synthetic settings validation refusal" },
    { status: 403, code: "forbidden", message: "Synthetic settings access refusal" },
    { status: 409, code: "settings_conflict", message: "Synthetic settings conflict" },
    { status: 0, code: "network_error", message: "Failed to fetch" },
    { status: 500, code: "unexpected_failure", message: "Synthetic unexpected backend failure" },
  ])("handles $code with unchanged feedback and a later successful retry", async ({ status, code, message }) => {
    let persisted = createDashboardSettings({ version: 3, limitWarmupExhaustedThresholdPercent: 50 });
    const initial = DashboardSettingsSchema.parse(persisted);
    const bodies: SettingsUpdateRequest[] = [];
    let reads = 0;
    let refuse = true;
    let release: (() => void) | undefined;
    const held = new Promise<void>((resolve) => { release = resolve; });
    server.use(
      http.get("/api/diagnostics/cache-isolation-probe", () => HttpResponse.json({
        model: "gpt-probe", seedAccount: { accountId: "a-0", label: "Seed" }, availableOtherAccounts: [],
        seedRepetitions: 3, totalCalls: 3, estimatedInputTokensPerCall: 28000, estimatedTotalInputTokens: 84000,
        maxSeedRepetitions: 5, maxOtherAccounts: 5,
        pressure: { underPressure: false, reason: null, detail: null, selectableAccountCount: 1, eligibleAccountCount: 1, pressuredAccountCount: 0 },
      })),
      http.get("/api/settings", () => { reads++; return HttpResponse.json(persisted); }),
      http.put("/api/settings", async ({ request }) => {
        const body = SettingsUpdateRequestSchema.parse(await request.json());
        bodies.push(body);
        if (refuse) {
          await held;
          // A conflict read is authoritative, but it must not apply the refused draft.
          if (status === 409) persisted = createDashboardSettings({ ...persisted, version: 4 });
          return status === 0 ? HttpResponse.error() : HttpResponse.json({ error: { code, message } }, { status });
        }
        persisted = createDashboardSettings({ ...persisted, limitWarmupExhaustedThresholdPercent: body.limitWarmupExhaustedThresholdPercent, version: (persisted.version ?? 0) + 1 });
        return HttpResponse.json(persisted);
      }),
    );
    const rejected: unknown[] = [];
    const capture = (event: PromiseRejectionEvent) => { rejected.push(event.reason); };
    window.addEventListener("unhandledrejection", capture);
    const errorToast = vi.spyOn(toast, "error");
    const successToast = vi.spyOn(toast, "success");
    const view = mount();
    const invalidation = vi.spyOn(view.client, "invalidateQueries");
    try {
      const user = userEvent.setup({ delay: null });
      const field = await screen.findByRole("spinbutton", { name: "Min usage percent" });
      const save = () => screen.getByRole("button", { name: "Save warm-up settings" });
      expect(save()).toBeDisabled();
      await user.clear(field);
      await user.type(field, "37.5");
      await user.click(save());
      await waitFor(() => expect(bodies).toHaveLength(1));
      await waitFor(() => expect(save()).toBeDisabled());
      expect(field).toBeDisabled();
      expect(bodies[0]).toEqual(buildSettingsUpdateRequest(initial, { limitWarmupExhaustedThresholdPercent: 37.5 }));
      await act(async () => { release?.(); });
      await waitFor(() => expect(errorToast).toHaveBeenCalledWith(message));
      await waitFor(() => expect(save()).toBeEnabled());
      expect(screen.getByRole("spinbutton", { name: "Min usage percent" })).toBeEnabled();
      expect(successToast).not.toHaveBeenCalled();
      expect(screen.getByText(message)).toBeInTheDocument();
      expect(persisted.limitWarmupExhaustedThresholdPercent).toBe(50);
      if (status === 409) {
        await waitFor(() => expect(reads).toBe(2));
        await waitFor(() => expect(view.client.getQueryData(["settings", "detail"])).toEqual(DashboardSettingsSchema.parse(persisted)));
        expect(invalidation).toHaveBeenCalledExactlyOnceWith({ queryKey: ["settings", "detail"] });
      } else {
        expect(reads).toBe(1);
        expect(invalidation).not.toHaveBeenCalled();
        expect(view.client.getQueryData(["settings", "detail"])).toEqual(initial);
      }
      expect(rejected).toEqual([]);
      refuse = false;
      await user.click(save());
      await waitFor(() => expect(successToast).toHaveBeenCalledExactlyOnceWith("Settings saved"));
      await waitFor(() => expect(save()).toBeDisabled());
      expect(screen.getByRole("spinbutton", { name: "Min usage percent" })).toBeEnabled();
      expect(bodies).toHaveLength(2);
      expect(bodies[1]).toEqual({ ...bodies[0], expectedVersion: status === 409 ? 4 : 3 });
      await waitFor(() => expect(view.client.getQueryData(["settings", "detail"])).toEqual(DashboardSettingsSchema.parse(persisted)));
      expect(persisted.limitWarmupExhaustedThresholdPercent).toBe(37.5);
      expect(invalidation).toHaveBeenCalledWith({ queryKey: ["settings", "upstream-proxy"] });
      expect(rejected).toEqual([]);
    } finally {
      release?.();
      view.close();
      window.removeEventListener("unhandledrejection", capture);
      errorToast.mockRestore();
      successToast.mockRestore();
    }
  });

  it.each([false, true])("observes the equivalent Automations save, inheritance reset=%s", async (reset) => {
    const settings = createDashboardSettings({ version: 3, automationsSchedulerEnabled: false, provenance: { automations_scheduler_enabled: { source: "dashboard", envValue: true, default: true } } });
    const body = vi.fn();
    server.use(
      http.get("/api/settings", () => HttpResponse.json(settings)),
      http.put("/api/settings", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json({ error: { code: "validation_error", message: "Synthetic automations refusal" } }, { status: 422 });
      }),
    );
    const errorToast = vi.spyOn(toast, "error");
    const rejected: unknown[] = [];
    const capture = (event: PromiseRejectionEvent) => { rejected.push(event.reason); };
    window.addEventListener("unhandledrejection", capture);
    const view = mount(true);
    try {
      const user = userEvent.setup({ delay: null });
      const toggle = await screen.findByRole("switch", { name: "Pause all automations" });
      await user.click(reset ? screen.getByRole("button", { name: "Reset to inherited" }) : toggle);
      await waitFor(() => expect(errorToast).toHaveBeenCalledWith("Synthetic automations refusal"));
      expect(body).toHaveBeenCalledExactlyOnceWith(buildSettingsUpdateRequest(DashboardSettingsSchema.parse(settings), { automationsSchedulerEnabled: reset ? null : true }));
      await waitFor(() => expect(toggle).toBeEnabled());
      expect(toggle).toBeChecked();
      expect(view.client.getQueryData(["settings", "detail"])).toEqual(DashboardSettingsSchema.parse(settings));
      expect(rejected).toEqual([]);
    } finally {
      view.close();
      window.removeEventListener("unhandledrejection", capture);
      errorToast.mockRestore();
    }
  });
});
