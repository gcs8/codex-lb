import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { ResetCreditConfirmDialog } from "@/features/accounts/components/reset-credit-confirm-dialog";
import { server } from "@/test/mocks/server";

function ResetScene() {
  const [open, setOpen] = useState(false);
  return <>
    <button onClick={() => setOpen(true)}>Redeem opener</button>
    {open && <ResetCreditConfirmDialog open onOpenChange={setOpen} accountId="acc_primary" />}
  </>;
}

function renderReset() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><ResetScene /></QueryClientProvider>);
}

const snapshot = () => HttpResponse.json({ availableCount: 2, nearestExpiresAt: null, credits: [] });
const result = () => HttpResponse.json({ code: "rate_limit_reset", windowsReset: 1, redeemedAt: "2026-10-04T12:00:00Z" });

describe("ResetCreditConfirmDialog original opener", () => {
  for (const close of ["Escape", "Cancel", "Action"]) {
    it(`automatically restores its conditionally mounted opener on ${close}`, async () => {
      const user = userEvent.setup();
      const consume = vi.fn();
      server.use(
        http.get("/api/accounts/acc_primary/rate-limit-reset-credits", snapshot),
        http.post("/api/accounts/acc_primary/rate-limit-reset-credits/consume", () => { consume(); return result(); }),
      );
      renderReset();
      const opener = screen.getByRole("button", { name: "Redeem opener" });
      await user.click(opener);
      expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
      await waitFor(() => expect(screen.getByRole("button", { name: "Redeem credit" })).toBeEnabled());
      if (close === "Escape") await user.keyboard("{Escape}");
      else await user.click(screen.getByRole("button", { name: close === "Action" ? "Redeem credit" : "Cancel" }));
      await waitFor(() => expect(opener).toHaveFocus());
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Redeem opener" })).toBe(opener);
      expect(opener.isConnected).toBe(true);
      expect(consume).toHaveBeenCalledTimes(close === "Action" ? 1 : 0);
    });
  }

  it("does not restore on pending/refused redemption, then returns on Cancel", async () => {
    const user = userEvent.setup();
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => { finish = resolve; });
    const consume = vi.fn();
    server.use(
      http.get("/api/accounts/acc_primary/rate-limit-reset-credits", snapshot),
      http.post("/api/accounts/acc_primary/rate-limit-reset-credits/consume", async () => {
        consume(); await pending;
        return HttpResponse.json({ error: { code: "refused", message: "Synthetic refusal" } }, { status: 403 });
      }),
    );
    renderReset();
    const opener = screen.getByRole("button", { name: "Redeem opener" });
    await user.click(opener);
    await waitFor(() => expect(screen.getByRole("button", { name: "Redeem credit" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Redeem credit" }));
    expect(await screen.findByRole("button", { name: "Redeeming..." })).toBeDisabled();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(opener).not.toHaveFocus();
    await act(async () => finish());
    await waitFor(() => expect(screen.getByRole("button", { name: "Redeem credit" })).toBeEnabled());
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(opener).not.toHaveFocus();
    expect(consume).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(opener).toHaveFocus());
    expect(screen.getByRole("button", { name: "Redeem opener" })).toBe(opener);
  });
});
