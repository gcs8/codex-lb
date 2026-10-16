import { HttpResponse, http } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { updateAccountQuotaTier } from "@/features/accounts/api";
import { AccountQuotaTier } from "@/features/accounts/components/account-quota-tier";
import { createAccountSummary } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";

function renderTier(overrides: Parameters<typeof createAccountSummary>[0] = {}) {
  const onSave = vi.fn(updateAccountQuotaTier);
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
  render(<AccountQuotaTier account={account} onSave={onSave} />);
  return { onSave };
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
          quotaTierMultiplierExpiresAt: "2026-10-30T07:00:00Z",
          planQuotaTierMultiplier: 10,
          effectiveQuotaTierMultiplier: 20,
        });
      }),
    );
    const { onSave } = renderTier();

    await user.click(screen.getByRole("button", { name: "20×" }));
    const date = screen.getByLabelText("Override ends");
    await user.clear(date);
    await user.type(date, "2026-10-29");
    // "Through Oct 29" = end of that day in Pacific (PDT) = 07:00Z on Oct 30.
    expect(screen.getByTestId("account-quota-tier-ends")).toHaveTextContent(
      "Ends after 2026-10-29 (America/Los_Angeles) · 2026-10-30T07:00:00Z",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(body).toHaveBeenCalledTimes(1));
    expect(body).toHaveBeenCalledWith({
      quotaTierMultiplier: 20,
      quotaMonthlyCredits: null,
      quotaTierMultiplierExpiresAt: "2026-10-30T07:00:00.000Z",
    });
    expect(onSave).toHaveBeenCalledWith("acc_tier", { kind: "multiplier", value: 20 }, "2026-10-30T07:00:00.000Z");
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
      expect(body).toHaveBeenCalledWith({
        quotaTierMultiplier: null,
        quotaMonthlyCredits: null,
        quotaTierMultiplierExpiresAt: null,
      }),
    );
  });

  it("saves a raw monthly credit allowance instead of a multiplier", async () => {
    const user = userEvent.setup();
    const body = vi.fn();
    server.use(
      http.put("/api/accounts/acc_tier/quota-tier", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json({
          accountId: "acc_tier",
          quotaTierMultiplier: null,
          quotaTierMultiplierExpiresAt: null,
          quotaMonthlyCredits: 151200,
          planQuotaTierMultiplier: 10,
          effectiveQuotaTierMultiplier: 20,
          effectiveQuotaMonthlyCredits: 151200,
        });
      }),
    );
    renderTier();

    await user.click(screen.getByRole("button", { name: "Credits / month" }));
    expect(screen.getByLabelText("Monthly credits")).toHaveAttribute("placeholder", "plan: 75,600");
    await user.type(screen.getByLabelText("Monthly credits"), "151,200");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(body).toHaveBeenCalledWith({
        quotaTierMultiplier: null,
        quotaMonthlyCredits: 151200,
        quotaTierMultiplierExpiresAt: null,
      }),
    );
  });

  it("opens in credits mode when the account has a credit override", () => {
    renderTier({ quotaMonthlyCredits: 45_360, effectiveQuotaTierMultiplier: 6 });
    expect(screen.getByRole("button", { name: "Credits / month" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Monthly credits")).toHaveValue("45360");
  });

  it("blocks saving an out-of-range multiplier", async () => {
    const user = userEvent.setup();
    renderTier();
    await user.type(screen.getByLabelText("Tier multiplier"), "500");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});
