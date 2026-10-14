import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { AccountList } from "@/features/accounts/components/account-list";
import { sortAccountsForDisplay, type AccountSortMode } from "@/features/accounts/sorting";
import { createAccountSummary } from "@/test/mocks/factories";

const accounts = [
  createAccountSummary({
    accountId: "scoped-prolite",
    email: "shared@example.com",
    displayName: "Weekly seat",
    planType: "prolite",
    chatgptAccountId: "fixture-workspace-lite",
    workspaceId: "fixture-workspace-lite",
    isEmailDuplicate: true,
    resetAtPrimary: null,
    windowMinutesPrimary: null,
    usage: { primaryRemainingPercent: null, secondaryRemainingPercent: 80, monthlyRemainingPercent: null },
  }),
  createAccountSummary({
    accountId: "scoped-pro",
    email: "shared@example.com",
    displayName: "Pro seat",
    planType: "pro",
    chatgptAccountId: "fixture-workspace-pro",
    workspaceId: "fixture-workspace-pro",
    isEmailDuplicate: true,
    usage: { primaryRemainingPercent: 0, secondaryRemainingPercent: 0, monthlyRemainingPercent: null },
  }),
];

function List({ onSelect }: { onSelect: (accountId: string) => void }) {
  const [sortMode, onSortModeChange] = useState<AccountSortMode>("quota_5h_desc");
  return <AccountList accounts={accounts} sortMode={sortMode} onSortModeChange={onSortModeChange} selectedAccountId="scoped-prolite" onSelect={onSelect} onOpenImport={vi.fn()} onOpenOauth={vi.fn()} />;
}

function rows() {
  return within(screen.getByTestId("account-list-scroll-region")).getAllByRole("button");
}

const newModes: AccountSortMode[] = [
  "status_asc", "status_desc", "quota_5h_asc", "quota_5h_desc",
  "quota_7d_asc", "quota_7d_desc", "quota_monthly_asc", "quota_monthly_desc",
];

describe("account sorting preserves quota and credential slots", () => {
  it.each(["quota_5h_asc", "quota_5h_desc"] as const)("keeps weekly-only 5h quota unknown in %s", mode => {
    const sorted = sortAccountsForDisplay(accounts, "both", mode);
    expect(sorted.map(account => account.accountId)).toEqual(["scoped-pro", "scoped-prolite"]);
    expect(sorted[1]).toBe(accounts[0]);
    expect(sorted[1].usage?.primaryRemainingPercent).toBeNull();
    expect(sorted[1].usage?.secondaryRemainingPercent).toBe(80);
    expect(accounts.map(account => account.accountId)).toEqual(["scoped-prolite", "scoped-pro"]);
  });

  it.each(newModes)("uses reset, label and scoped ID ties consistently for %s", mode => {
    const tied = [
      createAccountSummary({ accountId: "scope-z", displayName: "Same", resetAtPrimary: "2099-01-02T00:00:00Z", resetAtSecondary: null }),
      createAccountSummary({ accountId: "scope-b", displayName: "Same", resetAtPrimary: "2099-01-01T00:00:00Z", resetAtSecondary: null }),
      createAccountSummary({ accountId: "scope-a", displayName: "Same", resetAtPrimary: "2099-01-01T00:00:00Z", resetAtSecondary: null }),
      createAccountSummary({ accountId: "scope-c", displayName: "Alpha", resetAtPrimary: "2099-01-01T00:00:00Z", resetAtSecondary: null }),
    ];
    const expected = ["scope-c", "scope-a", "scope-b", "scope-z"];
    expect(sortAccountsForDisplay(tied, "both", mode).map(account => account.accountId)).toEqual(expected);
    expect(sortAccountsForDisplay([...tied].reverse(), "both", mode).map(account => account.accountId)).toEqual(expected);
  });

  it("keeps pro/prolite labels, weekly-only rows and scoped selection through sorting and filtering", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<List onSelect={onSelect} />);
    expect(within(rows()[0]).getByText("Pro seat")).toBeInTheDocument();
    expect(within(rows()[0]).getByText(/Pro \| fixture-workspace-pro/)).toBeInTheDocument();
    expect(within(rows()[1]).getByText(/Prolite \| fixture-workspace-lite/)).toBeInTheDocument();
    expect(within(rows()[1]).queryByText("5h")).not.toBeInTheDocument();
    expect(within(rows()[1]).getByText("Weekly")).toBeInTheDocument();

    const sort = screen.getByRole("combobox", { name: "Sort accounts" });
    await user.click(sort);
    await user.click(await screen.findByRole("option", { name: "Weekly quota (highest remaining)" }));
    expect(within(rows()[0]).getByText("Weekly seat")).toBeInTheDocument();
    expect(rows()[0]).toHaveClass("bg-primary/8");
    await user.click(rows()[0]);
    expect(onSelect).toHaveBeenLastCalledWith("scoped-prolite");
    await user.click(rows()[1]);
    expect(onSelect).toHaveBeenLastCalledWith("scoped-pro");

    await user.type(screen.getByPlaceholderText("Search accounts..."), "shared@example.com");
    expect(rows()).toHaveLength(2);
    expect(sort).toHaveTextContent("Weekly quota (highest remaining)");
    await user.clear(screen.getByPlaceholderText("Search accounts..."));
    await user.type(screen.getByPlaceholderText("Search accounts..."), "scoped-prolite");
    expect(rows()).toHaveLength(1);
    expect(within(rows()[0]).getByText("Weekly seat")).toBeInTheDocument();
    await user.click(rows()[0]);
    expect(onSelect).toHaveBeenLastCalledWith("scoped-prolite");
    expect(accounts[0].planType).toBe("prolite");
    expect(accounts[1].planType).toBe("pro");
  });
});
