import { HttpResponse, http } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AccountQuotaTier } from "@/features/accounts/components/account-quota-tier";
import { createAccountSummary } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";

function renderTier(overrides: Parameters<typeof createAccountSummary>[0] = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const account = createAccountSummary({
    accountId: "acc_tier",
    planType: "pro",
    planQuotaTierMultiplier: 10,
    effectiveQuotaTierMultiplier: 10,
    quotaTierMultiplier: null,
    capacityCreditsSecondary: 17_640,
    capacityCreditsSecondaryMonthlyEquivalent: 75_600,
    ...overrides,
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AccountQuotaTier account={account} />
    </QueryClientProvider>,
  );
  return { queryClient };
}

describe("AccountQuotaTier", () => {
  it("shows the effective tier and weekly/monthly capacity", () => {
    renderTier();
    expect(screen.getByTestId("account-quota-tier-effective")).toHaveTextContent(
      "10× Plus · 17.64K / week (≈ 75.6K / month)",
    );
    expect(screen.queryByRole("button", { name: "Use plan default" })).not.toBeInTheDocument();
  });

  it("saves a preset tier with an end date", async () => {
    const user = userEvent.setup();
    const body = vi.fn();
    server.use(
      http.put("/api/accounts/acc_tier/quota-tier", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json({
          accountId: "acc_tier",
          quotaTierMultiplier: 20,
          quotaTierMultiplierExpiresAt: "2026-10-30T00:00:00Z",
          planQuotaTierMultiplier: 10,
          effectiveQuotaTierMultiplier: 20,
        });
      }),
    );
    const { queryClient } = renderTier();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await user.click(screen.getByRole("button", { name: "20×" }));
    const date = screen.getByLabelText("Override ends");
    await user.clear(date);
    await user.type(date, "2026-10-30");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(body).toHaveBeenCalledTimes(1));
    expect(body).toHaveBeenCalledWith({
      quotaTierMultiplier: 20,
      quotaTierMultiplierExpiresAt: "2026-10-30T00:00:00.000Z",
    });
    await waitFor(() => expect(invalidate).toHaveBeenCalled());
  });

  it("clears an existing override back to the plan default", async () => {
    const user = userEvent.setup();
    const body = vi.fn();
    server.use(
      http.put("/api/accounts/acc_tier/quota-tier", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json({
          accountId: "acc_tier",
          quotaTierMultiplier: null,
          quotaTierMultiplierExpiresAt: null,
          planQuotaTierMultiplier: 10,
          effectiveQuotaTierMultiplier: 10,
        });
      }),
    );
    renderTier({ quotaTierMultiplier: 20, effectiveQuotaTierMultiplier: 20 });

    await user.click(screen.getByRole("button", { name: "Use plan default" }));
    await waitFor(() =>
      expect(body).toHaveBeenCalledWith({ quotaTierMultiplier: null, quotaTierMultiplierExpiresAt: null }),
    );
  });

  it("blocks saving an out-of-range multiplier", async () => {
    const user = userEvent.setup();
    renderTier();
    await user.type(screen.getByLabelText("Tier multiplier"), "500");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});
