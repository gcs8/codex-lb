import { describe, expect, it, vi } from "vitest";

import { DashboardOverviewSchema } from "@/features/dashboard/schemas";
import type { AccountSummary, Depletion } from "@/features/dashboard/schemas";
import {
  applySecondaryConstraint,
  buildDashboardView,
  buildDepletionView,
  buildRemainingItems,
  buildWeeklyCreditPace,
  formatBurnHours,
  sumRemaining,
  weeklyCreditPaceStatus,
  type RemainingItem,
  type WeeklyCreditPace,
} from "@/features/dashboard/utils";
import { createDashboardOverview, createDefaultRequestLogs } from "@/test/mocks/factories";
import { formatCompactAccountId } from "@/utils/account-identifiers";

function account(overrides: Partial<AccountSummary> & Pick<AccountSummary, "accountId" | "email">): AccountSummary {
  return {
    accountId: overrides.accountId,
    email: overrides.email,
    displayName: overrides.displayName ?? overrides.email,
    planType: overrides.planType ?? "plus",
    status: overrides.status ?? "active",
    limitWarmupEnabled: overrides.limitWarmupEnabled ?? false,
    limitWarmup: overrides.limitWarmup ?? null,
    usage: overrides.usage ?? null,
    resetAtPrimary: overrides.resetAtPrimary ?? null,
    resetAtSecondary: overrides.resetAtSecondary ?? null,
    resetAtMonthly: overrides.resetAtMonthly ?? null,
    windowMinutesPrimary: overrides.windowMinutesPrimary ?? null,
    windowMinutesSecondary: overrides.windowMinutesSecondary ?? null,
    windowMinutesMonthly: overrides.windowMinutesMonthly ?? null,
    capacityCreditsPrimary: overrides.capacityCreditsPrimary ?? null,
    remainingCreditsPrimary: overrides.remainingCreditsPrimary ?? null,
    capacityCreditsSecondary: overrides.capacityCreditsSecondary ?? null,
    remainingCreditsSecondary: overrides.remainingCreditsSecondary ?? null,
    capacityCreditsMonthly: overrides.capacityCreditsMonthly ?? null,
    remainingCreditsMonthly: overrides.remainingCreditsMonthly ?? null,
    auth: overrides.auth ?? null,
    additionalQuotas: overrides.additionalQuotas ?? [],
    isEmailDuplicate: overrides.isEmailDuplicate,
  };
}

describe("buildDepletionView", () => {
  it("returns null for null depletion", () => {
    expect(buildDepletionView(null)).toBeNull();
  });

  it("returns null for undefined depletion", () => {
    expect(buildDepletionView(undefined)).toBeNull();
  });

  it("returns null for safe risk level", () => {
    const depletion: Depletion = {
      risk: 0.1,
      riskLevel: "safe",
      burnRate: 0.5,
      safeUsagePercent: 90,
    };
    expect(buildDepletionView(depletion)).toBeNull();
  });

  it("returns view for warning risk level", () => {
    const depletion: Depletion = {
      risk: 0.5,
      riskLevel: "warning",
      burnRate: 1.5,
      safeUsagePercent: 45,
    };
    const view = buildDepletionView(depletion);
    expect(view).toEqual({
      safePercent: 45,
      riskLevel: "warning",
    });
  });

  it("returns view for danger risk level", () => {
    const depletion: Depletion = {
      risk: 0.75,
      riskLevel: "danger",
      burnRate: 2.5,
      safeUsagePercent: 30,
    };
    const view = buildDepletionView(depletion);
    expect(view).toEqual({
      safePercent: 30,
      riskLevel: "danger",
    });
  });

  it("returns view for critical risk level", () => {
    const depletion: Depletion = {
      risk: 0.95,
      riskLevel: "critical",
      burnRate: 5.0,
      safeUsagePercent: 20,
    };
    const view = buildDepletionView(depletion);
    expect(view).toEqual({
      safePercent: 20,
      riskLevel: "critical",
    });
  });
});

function remainingItem(overrides: Partial<RemainingItem> & Pick<RemainingItem, "accountId">): RemainingItem {
  return {
    accountId: overrides.accountId,
    label: overrides.label ?? overrides.accountId,
    labelSuffix: overrides.labelSuffix ?? "",
    isEmail: overrides.isEmail ?? false,
    value: overrides.value ?? 100,
    remainingPercent: overrides.remainingPercent === undefined ? 80 : overrides.remainingPercent,
    color: overrides.color ?? "#aaa",
  };
}

describe("applySecondaryConstraint", () => {
  it("no-op when 7d remaining credits >= 5h remaining credits", () => {
    const primary = [remainingItem({ accountId: "acc-1", value: 180, remainingPercent: 80 })];
    const secondary = [remainingItem({ accountId: "acc-1", value: 6000, remainingPercent: 79 })];

    const result = applySecondaryConstraint(primary, secondary);

    expect(result[0].value).toBe(180);
    expect(result[0].remainingPercent).toBe(80);
  });

  it("caps 5h to 7d absolute credits when 7d remaining < 5h remaining", () => {
    const primary = [remainingItem({ accountId: "acc-1", value: 200, remainingPercent: 90 })];
    const secondary = [remainingItem({ accountId: "acc-1", value: 75, remainingPercent: 1 })];

    const result = applySecondaryConstraint(primary, secondary);

    expect(result[0].value).toBe(75);
    expect(result[0].remainingPercent).toBeCloseTo(90 * (75 / 200));
  });

  it("zeros 5h when 7d is fully depleted", () => {
    const primary = [remainingItem({ accountId: "acc-1", value: 200, remainingPercent: 90 })];
    const secondary = [remainingItem({ accountId: "acc-1", value: 0, remainingPercent: 0 })];

    const result = applySecondaryConstraint(primary, secondary);

    expect(result[0].value).toBe(0);
    expect(result[0].remainingPercent).toBe(0);
  });

  it("no-op when 7d has plenty even with low percent (different capacity scales)", () => {
    const primary = [remainingItem({ accountId: "acc-1", value: 200, remainingPercent: 90 })];
    const secondary = [remainingItem({ accountId: "acc-1", value: 3780, remainingPercent: 50 })];

    const result = applySecondaryConstraint(primary, secondary);

    expect(result[0].value).toBe(200);
    expect(result[0].remainingPercent).toBe(90);
  });

  it("preserves null remainingPercent on capped items", () => {
    const primary = [remainingItem({ accountId: "acc-1", value: 200, remainingPercent: null })];
    const secondary = [remainingItem({ accountId: "acc-1", value: 50 })];

    const result = applySecondaryConstraint(primary, secondary);

    expect(result[0].value).toBe(50);
    expect(result[0].remainingPercent).toBeNull();
  });

  it("returns primary unchanged when no matching secondary account exists", () => {
    const primary = [remainingItem({ accountId: "acc-1", value: 200, remainingPercent: 90 })];
    const secondary = [remainingItem({ accountId: "acc-2", value: 0, remainingPercent: 0 })];

    const result = applySecondaryConstraint(primary, secondary);

    expect(result[0].value).toBe(200);
    expect(result[0].remainingPercent).toBe(90);
  });

  it("does not clamp primary when secondary data is missing", () => {
    const primary = [remainingItem({ accountId: "acc-1", value: 200, remainingPercent: 90 })];
    const secondary = [remainingItem({ accountId: "acc-1", value: 0, remainingPercent: null })];

    const result = applySecondaryConstraint(primary, secondary);

    expect(result[0].value).toBe(200);
    expect(result[0].remainingPercent).toBe(90);
  });

  it("handles multiple accounts independently", () => {
    const primary = [
      remainingItem({ accountId: "acc-1", value: 200, remainingPercent: 90 }),
      remainingItem({ accountId: "acc-2", value: 150, remainingPercent: 60 }),
    ];
    const secondary = [
      remainingItem({ accountId: "acc-1", value: 75, remainingPercent: 1 }),
      remainingItem({ accountId: "acc-2", value: 5000, remainingPercent: 70 }),
    ];

    const result = applySecondaryConstraint(primary, secondary);

    expect(result[0].value).toBe(75);
    expect(result[0].remainingPercent).toBeCloseTo(90 * (75 / 200));
    expect(result[1].value).toBe(150);
    expect(result[1].remainingPercent).toBe(60);
  });

  it("returns empty array when primary is empty", () => {
    const result = applySecondaryConstraint([], [remainingItem({ accountId: "acc-1" })]);
    expect(result).toEqual([]);
  });

  it("does not mutate original primary items", () => {
    const primary = [remainingItem({ accountId: "acc-1", value: 200, remainingPercent: 90 })];
    const secondary = [remainingItem({ accountId: "acc-1", value: 0, remainingPercent: 0 })];

    applySecondaryConstraint(primary, secondary);

    expect(primary[0].value).toBe(200);
    expect(primary[0].remainingPercent).toBe(90);
  });

  it("caps to zero when secondary items are all zero-valued", () => {
    const primary = [
      remainingItem({ accountId: "acc-1", value: 200, remainingPercent: 90 }),
      remainingItem({ accountId: "acc-2", value: 150, remainingPercent: 60 }),
    ];
    const secondary = [
      remainingItem({ accountId: "acc-1", value: 0, remainingPercent: 0 }),
      remainingItem({ accountId: "acc-2", value: 0, remainingPercent: 0 }),
    ];

    const result = applySecondaryConstraint(primary, secondary);

    expect(result[0].value).toBe(0);
    expect(result[1].value).toBe(0);
  });
});

describe("buildRemainingItems", () => {
  it("keeps default labels for non-duplicate accounts", () => {
    const items = buildRemainingItems(
      [
        account({ accountId: "acc-1", email: "one@example.com" }),
        account({ accountId: "acc-2", email: "two@example.com" }),
      ],
      null,
      "primary",
    );

    expect(items[0].label).toBe("one@example.com");
    expect(items[1].label).toBe("two@example.com");
  });

  it("appends compact account id only when backend marks the slot duplicate", () => {
    const duplicateA = "d48f0bfc-8ea6-48a7-8d76-d0e5ef1816c5_6f12b5d5";
    const duplicateB = "7f9de2ad-7621-4a6f-88bc-ec7f3d914701_91a95cee";
    const items = buildRemainingItems(
      [
        account({ accountId: duplicateA, email: "dup@example.com", isEmailDuplicate: false }),
        account({ accountId: duplicateB, email: "dup@example.com", isEmailDuplicate: true }),
        account({ accountId: "acc-3", email: "unique@example.com" }),
      ],
      null,
      "primary",
    );

    expect(items[0].label).toBe("dup@example.com");
    expect(items[0].labelSuffix).toBe("");
    expect(items[0].isEmail).toBe(true);
    expect(items[1].label).toBe("dup@example.com");
    expect(items[1].labelSuffix).toBe(` (${formatCompactAccountId(duplicateB, 5, 4)})`);
    expect(items[1].isEmail).toBe(true);
    expect(items[2].label).toBe("unique@example.com");
    expect(items[2].labelSuffix).toBe("");
    expect(items[2].isEmail).toBe(true);
  });

  it("omits monthly-only accounts from primary and secondary donuts", () => {
    const monthly = account({
      accountId: "acc-monthly",
      email: "monthly@example.com",
      planType: "free",
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: null,
        monthlyRemainingPercent: 88,
      },
      windowMinutesPrimary: null,
      windowMinutesSecondary: null,
      windowMinutesMonthly: 43_200,
    });

    expect(buildRemainingItems([monthly], null, "primary")).toEqual([]);
    expect(buildRemainingItems([monthly], null, "secondary")).toEqual([]);
  });
});

describe("sumRemaining", () => {
  it("returns 0 for empty array", () => {
    expect(sumRemaining([])).toBe(0);
  });

  it("sums positive values", () => {
    const items = [
      remainingItem({ accountId: "a", value: 120 }),
      remainingItem({ accountId: "b", value: 80 }),
    ];
    expect(sumRemaining(items)).toBe(200);
  });

  it("clamps negative values to 0 before summing", () => {
    const items = [
      remainingItem({ accountId: "a", value: 100 }),
      remainingItem({ accountId: "b", value: -30 }),
    ];
    expect(sumRemaining(items)).toBe(100);
  });

  it("returns 0 when all values are negative", () => {
    const items = [
      remainingItem({ accountId: "a", value: -10 }),
      remainingItem({ accountId: "b", value: -20 }),
    ];
    expect(sumRemaining(items)).toBe(0);
  });
});

describe("buildWeeklyCreditPace", () => {
  const now = new Date("2026-01-07T12:00:00Z");

  type WeeklyAccountOverrides = Partial<AccountSummary> & {
    accountId: string;
    fullCredits?: number | null;
    remainingCredits?: number | null;
    timeLeftPercent?: number;
  };

  function weeklyAccount(overrides: WeeklyAccountOverrides): AccountSummary {
    const { accountId, fullCredits, remainingCredits, timeLeftPercent: timeLeftOverride, ...accountOverrides } = overrides;
    const windowMinutes = 10_080;
    const timeLeftPercent = timeLeftOverride ?? 50;
    const resetAt = new Date(now.getTime() + windowMinutes * 60_000 * (timeLeftPercent / 100)).toISOString();
    const fullCreditBudget = fullCredits !== undefined ? fullCredits : accountOverrides.capacityCreditsSecondary ?? 100_000;
    const remainingCreditBudget =
      remainingCredits !== undefined ? remainingCredits : accountOverrides.remainingCreditsSecondary ?? 50_000;
    return account({
      ...accountOverrides,
      accountId,
      email: `${accountId}@example.com`,
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent:
          fullCreditBudget && remainingCreditBudget != null
            ? (remainingCreditBudget / fullCreditBudget) * 100
            : null,
      },
      resetAtSecondary: accountOverrides.resetAtSecondary !== undefined ? accountOverrides.resetAtSecondary : resetAt,
      windowMinutesSecondary: accountOverrides.windowMinutesSecondary !== undefined
        ? accountOverrides.windowMinutesSecondary
        : windowMinutes,
      capacityCreditsSecondary: fullCreditBudget,
      remainingCreditsSecondary: remainingCreditBudget,
    });
  }

  it("marks over-schedule weekly usage as ahead before hard shortfall states", () => {
    expect(weeklyCreditPaceStatus(6, 0)).toBe("ahead");
    expect(weeklyCreditPaceStatus(6, 1)).toBe("danger");
  });

  it("treats a 99% used account at 99% elapsed as on pace", () => {
    const pace = buildWeeklyCreditPace(
      [weeklyAccount({ accountId: "acc-close", fullCredits: 100_000, remainingCredits: 1_000, timeLeftPercent: 1 })],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.totalExpectedRemainingCredits).toBeCloseTo(1_000);
    expect(pace?.overPlanCredits).toBeCloseTo(0);
    expect(pace?.deltaPercent).toBeCloseTo(0);
    expect(pace?.pauseForBreakEvenHours).toBeNull();
    expect(pace?.paceMultiplier).toBeNull();
    expect(pace?.throttleToPercent).toBeNull();
    expect(pace?.reduceByPercent).toBeNull();
    expect(pace?.proAccountsToCoverOverPlan).toBeNull();
    expect(pace?.status).toBe("on_track");
  });

  it("does not report a shortfall when the weekly reset replenishes a sustainable account", () => {
    const pace = buildWeeklyCreditPace(
      [weeklyAccount({ accountId: "acc-sustainable", fullCredits: 100_000, remainingCredits: 50_000, timeLeftPercent: 50 })],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.overPlanCredits).toBeCloseTo(0);
    expect(pace?.projectedDepletionHours).toBeNull();
    expect(pace?.pauseForBreakEvenHours).toBeNull();
    expect(pace?.status).toBe("on_track");
  });

  it("advances past-due weekly resets to the next cycle", () => {
    const pace = buildWeeklyCreditPace(
      [
        weeklyAccount({
          accountId: "acc-stale-reset",
          fullCredits: 700,
          remainingCredits: 600,
          resetAtSecondary: new Date(now.getTime() - 24 * 3_600_000).toISOString(),
        }),
      ],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.totalExpectedRemainingCredits).toBeCloseTo(600);
    expect(pace?.scheduledUsedPercent).toBeCloseTo(100 / 7);
    expect(pace?.overPlanCredits).toBeCloseTo(0);
    expect(pace?.status).toBe("on_track");
  });

  it("normalizes stale resets that are more than one full cycle in the past", () => {
    const pace = buildWeeklyCreditPace(
      [
        weeklyAccount({
          accountId: "acc-multiple-cycles-stale",
          fullCredits: 70_000,
          remainingCredits: 35_000,
          // One full weekly cycle plus one extra day behind.
          resetAtSecondary: new Date(now.getTime() - 8 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.scheduledUsedPercent).toBeCloseTo(14.2857, 3);
    expect(pace?.actualUsedPercent).toBeCloseTo(50);
    expect(pace?.overPlanCredits).toBeGreaterThan(0);
    expect(pace?.pauseForBreakEvenHours).toBeGreaterThan(0);
    expect(pace?.status).toBe("danger");
  });

  it("aggregates credit budgets instead of averaging account percentages", () => {
    const pace = buildWeeklyCreditPace(
      [
        weeklyAccount({ accountId: "acc-small", fullCredits: 100_000, remainingCredits: 1_000, timeLeftPercent: 1 }),
        weeklyAccount({ accountId: "acc-large", fullCredits: 900_000, remainingCredits: 800_000, timeLeftPercent: 80 }),
      ],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.accountCount).toBe(2);
    expect(pace?.totalActualRemainingCredits).toBeCloseTo(801_000);
    expect(pace?.totalExpectedRemainingCredits).toBeCloseTo(721_000);
    expect(pace?.overPlanCredits).toBeCloseTo(0);
    expect(pace?.actualUsedPercent).toBeCloseTo(19.9);
    expect(pace?.scheduledUsedPercent).toBeCloseTo(27.9);
    expect(pace?.pauseForBreakEvenHours).toBeNull();
    expect(pace?.paceMultiplier).toBeNull();
    expect(pace?.proAccountsToCoverOverPlan).toBeNull();
    expect(pace?.status).toBe("behind");
  });

  it("marks a large account depleted too early as danger", () => {
    const pace = buildWeeklyCreditPace(
      [weeklyAccount({ accountId: "acc-early", fullCredits: 1_000_000, remainingCredits: 10_000, timeLeftPercent: 80 })],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.totalExpectedRemainingCredits).toBeCloseTo(800_000);
    expect(pace?.scheduleGapCredits).toBeCloseTo(790_000);
    expect(pace?.projectedShortfallCredits).toBeCloseTo(3_950_000);
    expect(pace?.deltaPercent).toBeCloseTo(79);
    expect(pace?.pauseForBreakEvenHours).toBeCloseTo(134.06);
    expect(pace?.paceMultiplier).toBeCloseTo(4.95);
    expect(pace?.throttleToPercent).toBeCloseTo(0.25);
    expect(pace?.reduceByPercent).toBeCloseTo(99.75);
    // shortfall ~3,949,848 credits / 17,640 per Pro (10x Plus, weekly; gcs8/codex-lb#7)
    expect(pace?.proAccountEquivalentToCoverOverPlan).toBeCloseTo(223.92); // was 78.37 at 50,400 per Pro
    expect(pace?.proAccountsToCoverOverPlan).toBe(224);
    expect(pace?.projectedDepletionHours).toBeCloseTo(0.34);
    expect(pace?.status).toBe("danger");
  });

  it("uses each account reset time before summing credits", () => {
    const pace = buildWeeklyCreditPace(
      [
        weeklyAccount({ accountId: "acc-near", fullCredits: 100_000, remainingCredits: 50_000, timeLeftPercent: 10 }),
        weeklyAccount({ accountId: "acc-far", fullCredits: 100_000, remainingCredits: 50_000, timeLeftPercent: 90 }),
      ],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.totalExpectedRemainingCredits).toBeCloseTo(100_000);
    expect(pace?.scheduledUsedPercent).toBeCloseTo(50);
    expect(pace?.actualUsedPercent).toBeCloseTo(50);
    expect(pace?.scheduleGapCredits).toBeCloseTo(0);
    expect(pace?.projectedShortfallCredits).toBeGreaterThan(0);
    expect(pace?.pauseForBreakEvenHours).toBeCloseTo(90.72);
    expect(pace?.paceMultiplier).toBeCloseTo(2.78);
    expect(pace?.proAccountEquivalentToCoverOverPlan).toBeGreaterThan(0);
    // Same shortfall, 17,640-credit Pro (was 6 at 50,400).
    expect(pace?.proAccountsToCoverOverPlan).toBe(18);
    expect(pace?.proAccountsToCoverOverPlan).toBe(Math.ceil(pace?.proAccountEquivalentToCoverOverPlan ?? 0));
    expect(pace?.status).toBe("danger");
  });

  it("bases throttle advice on the full time until the replenishing reset", () => {
    const pace = buildWeeklyCreditPace(
      [
        weeklyAccount({ accountId: "acc-near", fullCredits: 100_000, remainingCredits: 50_000, timeLeftPercent: 10 }),
        weeklyAccount({ accountId: "acc-far", fullCredits: 100_000, remainingCredits: 50_000, timeLeftPercent: 90 }),
      ],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.projectedDepletionHours).toBeCloseTo(60.48);
    expect(pace?.throttleToPercent).toBeCloseTo(40);
    expect(pace?.reduceByPercent).toBeCloseTo(60);
  });

  it("expires unused account credits at reset instead of carrying them forward", () => {
    const pace = buildWeeklyCreditPace(
      [
        weeklyAccount({ accountId: "unused-near-reset", fullCredits: 1_000, remainingCredits: 1_000, timeLeftPercent: 10 }),
        weeklyAccount({ accountId: "empty-later-reset", fullCredits: 1_000, remainingCredits: 0, timeLeftPercent: 90 }),
      ],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.overPlanCredits).toBeCloseTo(0);
    expect(pace?.projectedMinimumRemainingCredits).toBeCloseTo(0);
  });

  it("does not let a tiny near reset hide depletion before the next meaningful reset", () => {
    const pace = buildWeeklyCreditPace(
      [
        weeklyAccount({ accountId: "tiny-reset", fullCredits: 2, remainingCredits: 0, timeLeftPercent: 1 }),
        weeklyAccount({ accountId: "large-later", fullCredits: 100_000, remainingCredits: 20_000, timeLeftPercent: 50 }),
      ],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.scheduleGapCredits).toBeCloseTo(30_000.02);
    expect(pace?.projectedShortfallCredits).toBeCloseTo(59_999.01);
    expect(pace?.projectedDepletionHours).toBeLessThan(40);
    expect(pace?.proAccountEquivalentToCoverOverPlan).toBeGreaterThan(1);
    // Same shortfall, 17,640-credit Pro (was 2 at 50,400).
    expect(pace?.proAccountsToCoverOverPlan).toBe(4);
    expect(pace?.proAccountsToCoverOverPlan).toBe(Math.ceil(pace?.proAccountEquivalentToCoverOverPlan ?? 0));
    expect(pace?.status).toBe("danger");
  });

  it("computes break-even pause across different reset deadlines", () => {
    const pace = buildWeeklyCreditPace(
      [
        weeklyAccount({ accountId: "acc-near", fullCredits: 100_000, remainingCredits: 0, timeLeftPercent: 10 }),
        weeklyAccount({ accountId: "acc-far", fullCredits: 100_000, remainingCredits: 0, timeLeftPercent: 90 }),
      ],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.scheduleGapCredits).toBeCloseTo(100_000);
    expect(pace?.projectedShortfallCredits).toBeCloseTo(900_000);
    expect(pace?.pauseForBreakEvenHours).toBeGreaterThan(0);
    expect(pace?.pauseForBreakEvenHours).toBeCloseTo(136.08);
    expect(pace?.paceMultiplier).toBeCloseTo(5.56);
    expect(pace?.throttleToPercent).toBeCloseTo(10);
    expect(pace?.reduceByPercent).toBeCloseTo(90);
    // shortfall ~900,144 credits / 17,640 per Pro (10x Plus, weekly; gcs8/codex-lb#7)
    expect(pace?.proAccountEquivalentToCoverOverPlan).toBeCloseTo(51.02); // was 17.86 at 50,400 per Pro
    expect(pace?.proAccountsToCoverOverPlan).toBe(52);
    expect(pace?.projectedDepletionHours).toBeCloseTo(0);
    expect(pace?.status).toBe("danger");
  });

  it("continues past a tiny first reset when the weekly pool starts empty", () => {
    const pace = buildWeeklyCreditPace(
      [
        weeklyAccount({ accountId: "tiny-reset", fullCredits: 2, remainingCredits: 0, timeLeftPercent: 1 }),
        weeklyAccount({ accountId: "large-later", fullCredits: 100_000, remainingCredits: 0, timeLeftPercent: 50 }),
      ],
      now,
    );

    expect(pace).not.toBeNull();
    expect(pace?.scheduleGapCredits).toBeCloseTo(50_000.02);
    expect(pace?.projectedShortfallCredits).toBeCloseTo(99_999.01);
    expect(pace?.pauseForBreakEvenHours).toBeCloseTo(84);
    expect(pace?.throttleToPercent).toBeCloseTo(0.002);
    expect(pace?.projectedDepletionHours).toBeCloseTo(0);
    expect(pace?.status).toBe("danger");
  });

  it("shows recovery pressure when per-account weekly burn exceeds staggered resets", () => {
    const liveLikeNow = new Date("2026-05-03T19:19:35Z");
    const pace = buildWeeklyCreditPace(
      [
        account({
          accountId: "old-pro-1",
          email: "old-pro-1@example.com",
          planType: "pro",
          capacityCreditsSecondary: 50_400,
          remainingCreditsSecondary: 1_008,
          resetAtSecondary: "2026-05-05T05:34:05Z",
          windowMinutesSecondary: 10_080,
        }),
        account({
          accountId: "old-pro-2",
          email: "old-pro-2@example.com",
          planType: "pro",
          capacityCreditsSecondary: 50_400,
          remainingCreditsSecondary: 1_512,
          resetAtSecondary: "2026-05-05T05:51:53Z",
          windowMinutesSecondary: 10_080,
        }),
        account({
          accountId: "team-1",
          email: "team-1@example.com",
          planType: "team",
          capacityCreditsSecondary: 7_560,
          remainingCreditsSecondary: 1_587.6,
          resetAtSecondary: "2026-05-05T13:31:20Z",
          windowMinutesSecondary: 10_080,
        }),
        account({
          accountId: "team-2",
          email: "team-2@example.com",
          planType: "team",
          capacityCreditsSecondary: 7_560,
          remainingCreditsSecondary: 5_443.2,
          resetAtSecondary: "2026-05-06T14:45:02Z",
          windowMinutesSecondary: 10_080,
        }),
        account({
          accountId: "new-pro",
          email: "new-pro@example.com",
          planType: "pro",
          capacityCreditsSecondary: 50_400,
          remainingCreditsSecondary: 48_888,
          resetAtSecondary: "2026-05-10T18:19:10Z",
          windowMinutesSecondary: 10_080,
        }),
      ],
      liveLikeNow,
    );

    expect(pace).not.toBeNull();
    expect(pace?.accountCount).toBe(5);
    expect(pace?.totalActualRemainingCredits).toBeCloseTo(58_438.8);
    expect(pace?.scheduleGapCredits).toBeCloseTo(17_226.02);
    expect(pace?.projectedShortfallCredits).toBeCloseTo(20_510.96);
    expect(pace?.pauseForBreakEvenHours).toBeGreaterThan(0);
    expect(pace?.paceMultiplier).toBeGreaterThan(1);
    expect(pace?.throttleToPercent).toBeGreaterThanOrEqual(0);
    expect(pace?.reduceByPercent).toBeGreaterThan(0);
    expect(pace?.proAccountEquivalentToCoverOverPlan).toBeGreaterThan(0);
    // Same shortfall, 17,640-credit Pro (was 1 at 50,400).
    expect(pace?.proAccountsToCoverOverPlan).toBe(2);
    expect(pace?.proAccountsToCoverOverPlan).toBe(Math.ceil(pace?.proAccountEquivalentToCoverOverPlan ?? 0));
    expect(pace?.projectedMinimumRemainingCredits).toBeCloseTo(0);
    expect(pace?.status).toBe("danger");
  });

  it("skips accounts without complete weekly credit timing data", () => {
    const pace = buildWeeklyCreditPace(
      [
        weeklyAccount({ accountId: "missing-full", fullCredits: null, remainingCredits: 1_000, timeLeftPercent: 50 }),
        weeklyAccount({ accountId: "missing-reset", fullCredits: 100_000, remainingCredits: 50_000, resetAtSecondary: null }),
        weeklyAccount({ accountId: "missing-window", fullCredits: 100_000, remainingCredits: 50_000, windowMinutesSecondary: null }),
      ],
      now,
    );

    expect(pace).toBeNull();
  });
});

describe("buildDashboardView", () => {
  function serverWeeklyPace(overrides: Partial<WeeklyCreditPace> = {}): WeeklyCreditPace {
    return {
      totalFullCredits: 100_800,
      totalActualRemainingCredits: 42_336,
      totalExpectedRemainingCredits: 60_480,
      actualUsedPercent: 58,
      scheduledUsedPercent: 40,
      deltaPercent: 18,
      scheduleGapCredits: 18_144,
      smoothedDeltaPercent: 18,
      smoothedScheduleGapCredits: 18_144,
      paceGapSmoothingMinutes: 30,
      overPlanCredits: 18_144,
      projectedShortfallCredits: 0,
      pauseForBreakEvenHours: null,
      paceMultiplier: null,
      throttleToPercent: null,
      reduceByPercent: null,
      proAccountEquivalentToCoverOverPlan: null,
      proAccountsToCoverOverPlan: null,
      projectedDepletionHours: null,
      projectedMinimumRemainingCredits: 12_000,
      forecastBurnRateCreditsPerHour: 6_000,
      scheduledBurnRateCreditsPerHour: 600,
      status: "on_track",
      accountCount: 2,
      staleAccountCount: 0,
      inactiveAccountCount: 0,
      confidence: "high",
      ...overrides,
    };
  }

  it("parses runway fields from a raw wire overview payload into the view end to end", () => {
    // Raw camelCase wire shape, deliberately untyped: it must survive
    // DashboardOverviewSchema.parse, not be injected after parsing.
    const rawWirePace = {
      totalFullCredits: 100_800,
      totalActualRemainingCredits: 8_064,
      totalExpectedRemainingCredits: 60_480,
      actualUsedPercent: 92,
      scheduledUsedPercent: 40,
      deltaPercent: 52,
      scheduleGapCredits: 52_416,
      smoothedDeltaPercent: 52,
      smoothedScheduleGapCredits: 52_416,
      paceGapSmoothingMinutes: 30,
      overPlanCredits: 52_416,
      projectedShortfallCredits: 0,
      pauseForBreakEvenHours: null,
      paceMultiplier: null,
      throttleToPercent: 28,
      reduceByPercent: 72,
      proAccountEquivalentToCoverOverPlan: null,
      proAccountsToCoverOverPlan: null,
      projectedDepletionHours: null,
      projectedMinimumRemainingCredits: 0,
      forecastBurnRateCreditsPerHour: 1_200,
      scheduledBurnRateCreditsPerHour: 600,
      runwayStatus: "runs_dry",
      headroomPercent: 8,
      headroomCredits: 8_064,
      burnRateRecentCreditsPerHour: 1_200,
      depletionEtaHours: 6.7,
      nextReliefInHours: 26,
      nextReliefCredits: 50_400,
      resetEvents: [{ at: "2026-01-08T14:00:00+00:00", creditsReturned: 50_400 }],
      saturatedAccountCount: 1,
      topApiKeys: [
        {
          apiKeyId: "key_hermes_prod",
          name: "hermes-prod",
          requests: 12_400,
          billableTokens: 9_800_000,
          cachedTokens: 4_000_000,
          dominantModel: "gpt-5.2-codex",
        },
      ],
      addProAccounts: 2,
      status: "on_track",
      accountCount: 2,
      staleAccountCount: 0,
      inactiveAccountCount: 0,
      confidence: "high",
    };
    const rawOverview: unknown = JSON.parse(
      JSON.stringify({ ...createDashboardOverview(), weeklyCreditPace: rawWirePace }),
    );

    const overview = DashboardOverviewSchema.parse(rawOverview);
    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);

    const pace = view.weeklyCreditPace;
    expect(pace).not.toBeNull();
    expect(pace?.runwayStatus).toBe("runs_dry");
    expect(pace?.headroomPercent).toBe(8);
    expect(pace?.headroomCredits).toBe(8_064);
    expect(pace?.burnRateRecentCreditsPerHour).toBe(1_200);
    expect(pace?.depletionEtaHours).toBeCloseTo(6.7);
    expect(pace?.nextReliefInHours).toBe(26);
    expect(pace?.nextReliefCredits).toBe(50_400);
    expect(pace?.resetEvents).toEqual([{ at: "2026-01-08T14:00:00+00:00", creditsReturned: 50_400 }]);
    expect(pace?.saturatedAccountCount).toBe(1);
    expect(pace?.topApiKeys).toEqual(rawWirePace.topApiKeys);
    expect(pace?.addProAccounts).toBe(2);
    expect(pace?.status).toBe("on_track");
    expect(pace?.scheduleGapCredits).toBe(52_416);
  });

  it("parses an old-backend overview payload without runway fields and keeps the legacy shape", () => {
    // serverWeeklyPace() carries only the legacy fields; the JSON round-trip
    // turns it into raw wire data before the schema parse.
    const rawOverview: unknown = JSON.parse(
      JSON.stringify({ ...createDashboardOverview(), weeklyCreditPace: serverWeeklyPace() }),
    );

    const overview = DashboardOverviewSchema.parse(rawOverview);
    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);

    const pace = view.weeklyCreditPace;
    expect(pace).not.toBeNull();
    expect(pace?.status).toBe("on_track");
    expect(pace?.scheduleGapCredits).toBe(18_144);
    expect(pace?.runwayStatus).toBeUndefined();
    expect(pace?.headroomPercent).toBeUndefined();
    expect(pace?.headroomCredits).toBeUndefined();
    expect(pace?.resetEvents).toBeUndefined();
    expect(pace?.topApiKeys).toBeUndefined();
  });

  it("reports no 5-hour window when every account is weekly-only", () => {
    const base = createDashboardOverview();
    const weeklyOnly = {
      ...base,
      accounts: base.accounts.map((account) => ({ ...account, windowMinutesPrimary: null, windowMinutesSecondary: 10_080 })),
    };
    expect(buildDashboardView(weeklyOnly, createDefaultRequestLogs(), false).hasPrimaryWindow).toBe(false);

    const mixed = {
      ...weeklyOnly,
      accounts: weeklyOnly.accounts.map((account, index) => (index === 0 ? { ...account, windowMinutesPrimary: 300 } : account)),
    };
    expect(buildDashboardView(mixed, createDefaultRequestLogs(), false).hasPrimaryWindow).toBe(true);
  });

  it("keeps the overview weekly pace when the projections refinement is null", () => {
    const overviewPace = serverWeeklyPace({ runwayStatus: "safe" });
    const overview = { ...createDashboardOverview(), weeklyCreditPace: overviewPace };

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false, {
      weeklyCreditPace: null,
    });

    expect(view.weeklyCreditPace).toBe(overviewPace);
  });

  it("prefers the fresh overview weekly pace over a retained projections copy", () => {
    // TanStack Query keeps the last successful projections payload across
    // later failures; a stale "safe" copy must not mask a fresh "runs_dry".
    const overviewPace = serverWeeklyPace({ runwayStatus: "runs_dry", headroomPercent: 4, headroomCredits: 4_032 });
    const staleProjectionsPace = serverWeeklyPace({ runwayStatus: "safe", headroomPercent: 40, headroomCredits: 40_320 });
    const overview = { ...createDashboardOverview(), weeklyCreditPace: overviewPace };

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false, {
      weeklyCreditPace: staleProjectionsPace,
    });

    expect(view.weeklyCreditPace).toBe(overviewPace);
  });

  it("uses the projections weekly pace when the overview omits the field (older backend)", () => {
    const overview = createDashboardOverview();
    expect(overview.weeklyCreditPace).toBeUndefined();
    const projectionsPace = serverWeeklyPace({ runwayStatus: "safe", headroomPercent: 40, headroomCredits: 40_320 });

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false, {
      weeklyCreditPace: projectionsPace,
    });

    expect(view.weeklyCreditPace).toBe(projectionsPace);
  });

  it("uses the projections weekly pace when the overview serves an explicit null (older backend)", () => {
    // Old backends serve `weeklyCreditPace: null` rather than omitting the
    // field, so a served null must not be read as an authoritative "no pace".
    const overview = { ...createDashboardOverview(), weeklyCreditPace: null };
    const projectionsPace = serverWeeklyPace({ runwayStatus: "safe", headroomPercent: 40, headroomCredits: 40_320 });

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false, {
      weeklyCreditPace: projectionsPace,
    });

    expect(view.weeklyCreditPace).toBe(projectionsPace);
  });

  it("prefers backend weekly credit pace when the overview provides it", () => {
    const serverPace: WeeklyCreditPace = {
      totalFullCredits: 50_400,
      totalActualRemainingCredits: 38_304,
      totalExpectedRemainingCredits: 41_904,
      actualUsedPercent: 24,
      scheduledUsedPercent: 16.86,
      deltaPercent: 7.14,
      scheduleGapCredits: 3_600,
      smoothedDeltaPercent: 7.14,
      smoothedScheduleGapCredits: 3_600,
      paceGapSmoothingMinutes: 30,
      overPlanCredits: 3_600,
      projectedShortfallCredits: 0,
      pauseForBreakEvenHours: null,
      paceMultiplier: 0,
      throttleToPercent: null,
      reduceByPercent: null,
      proAccountEquivalentToCoverOverPlan: null,
      proAccountsToCoverOverPlan: null,
      projectedDepletionHours: null,
      projectedMinimumRemainingCredits: 38_304,
      forecastBurnRateCreditsPerHour: 0,
      scheduledBurnRateCreditsPerHour: 300,
      status: "ahead",
      accountCount: 1,
      staleAccountCount: 0,
      inactiveAccountCount: 0,
      confidence: "high",
    };
    const overview = createDashboardOverview({
      accounts: [
        account({
          accountId: "acc-server-pace",
          email: "pace@example.com",
          capacityCreditsSecondary: 50_400,
          remainingCreditsSecondary: 50_400,
          resetAtSecondary: "2026-01-14T12:00:00Z",
          windowMinutesSecondary: 10_080,
        }),
      ],
    });

    const view = buildDashboardView({ ...overview, weeklyCreditPace: serverPace }, createDefaultRequestLogs(), false);

    expect(view.weeklyCreditPace).toBe(serverPace);
  });

  it("falls back to the local projection when the overview serves null and projections have none", () => {
    const weeklyResetAt = new Date(Date.now() + 3.5 * 24 * 60 * 60 * 1000).toISOString();
    const overview = createDashboardOverview({
      weeklyCreditPace: null,
      accounts: [
        account({
          accountId: "acc-null-server-pace",
          email: "null-pace@example.com",
          usage: {
            primaryRemainingPercent: null,
            secondaryRemainingPercent: 50,
          },
          capacityCreditsSecondary: 50_400,
          remainingCreditsSecondary: 25_200,
          resetAtSecondary: weeklyResetAt,
          windowMinutesSecondary: 10_080,
        }),
      ],
    });

    // Old backends serve null instead of omitting the field, so the client
    // must still synthesize a pace locally rather than hiding the card.
    expect(buildWeeklyCreditPace(overview.accounts)).not.toBeNull();

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);

    expect(view.weeklyCreditPace).not.toBeNull();
    expect(view.weeklyCreditPace?.accountCount).toBe(1);
  });

  it("keeps donut totals anchored to window capacity even when displayed slices are constrained", () => {
    const overview = createDashboardOverview({
      accounts: [
        account({
          accountId: "acc-1",
          email: "one@example.com",
          usage: {
            primaryRemainingPercent: 90,
            secondaryRemainingPercent: 1,
          },
          resetAtPrimary: null,
          resetAtSecondary: null,
          windowMinutesPrimary: 300,
          windowMinutesSecondary: 10080,
        }),
        account({
          accountId: "acc-2",
          email: "two@example.com",
          usage: {
            primaryRemainingPercent: 60,
            secondaryRemainingPercent: 70,
          },
          resetAtPrimary: null,
          resetAtSecondary: null,
          windowMinutesPrimary: 300,
          windowMinutesSecondary: 10080,
        }),
      ],
      summary: {
        primaryWindow: {
          remainingPercent: 75,
          capacityCredits: 450,
          remainingCredits: 337.5,
          resetAt: null,
          windowMinutes: 300,
        },
        secondaryWindow: {
          remainingPercent: 35.5,
          capacityCredits: 15120,
          remainingCredits: 5370,
          resetAt: null,
          windowMinutes: 10080,
        },
        cost: {
          currency: "USD",
          totalUsd: 1.82,
        },
        metrics: {
          requests: 228,
          conversations: 0,
          conversationRequests: 0,
          tokens: 45000,
          cachedInputTokens: 8200,
          errorRate: 0.028,
          errorCount: 6,
          topError: "rate_limit_exceeded",
        },
      },
    });

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);

    expect(view.primaryUsageItems).toHaveLength(2);
    expect(view.primaryUsageItems[0]?.value).toBeCloseTo(75.6);
    expect(view.primaryUsageItems[1]?.value).toBeCloseTo(135);
    expect(overview.summary.primaryWindow.capacityCredits).toBe(450);
    expect(overview.summary.secondaryWindow?.capacityCredits).toBe(15120);
    expect(view.primaryUsageItems.reduce((total, item) => total + item.value, 0)).toBeCloseTo(210.6);
  });

  it("keeps primary totals intact for accounts without secondary usage data", () => {
    const overview = createDashboardOverview({
      accounts: [
        account({
          accountId: "acc-1",
          email: "one@example.com",
          usage: {
            primaryRemainingPercent: 90,
            secondaryRemainingPercent: null,
          },
          resetAtPrimary: null,
          resetAtSecondary: null,
          windowMinutesPrimary: 300,
          windowMinutesSecondary: null,
        }),
      ],
      windows: {
        primary: {
          windowKey: "primary",
          windowMinutes: 300,
          accounts: [
            {
              accountId: "acc-1",
              remainingPercentAvg: 90,
              capacityCredits: 225,
              remainingCredits: 202.5,
            },
          ],
        },
        secondary: {
          windowKey: "secondary",
          windowMinutes: 10080,
          accounts: [
            {
              accountId: "acc-1",
              remainingPercentAvg: null,
              capacityCredits: 7560,
              remainingCredits: 0,
            },
          ],
        },
      },
      summary: {
        primaryWindow: {
          remainingPercent: 90,
          capacityCredits: 225,
          remainingCredits: 202.5,
          resetAt: null,
          windowMinutes: 300,
        },
        secondaryWindow: {
          remainingPercent: 0,
          capacityCredits: 7560,
          remainingCredits: 0,
          resetAt: null,
          windowMinutes: 10080,
        },
        cost: {
          currency: "USD",
          totalUsd: 1.82,
        },
        metrics: {
          requests: 228,
          conversations: 0,
          conversationRequests: 0,
          tokens: 45000,
          cachedInputTokens: 8200,
          errorRate: 0.028,
          errorCount: 6,
          topError: "rate_limit_exceeded",
        },
      },
    });

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);

    expect(view.primaryUsageItems).toHaveLength(1);
    expect(view.primaryUsageItems[0]?.value).toBeCloseTo(202.5);
    expect(view.primaryUsageItems[0]?.remainingPercent).toBe(90);
    expect(overview.summary.primaryWindow.capacityCredits).toBe(225);
  });

  it("adds account burn rate from per-account window consumption", () => {
    const overview = createDashboardOverview({
      accounts: [
        account({
          accountId: "acc-1",
          email: "one@example.com",
          usage: {
            primaryRemainingPercent: 50,
            secondaryRemainingPercent: 25,
          },
          resetAtPrimary: null,
          resetAtSecondary: null,
          windowMinutesPrimary: 300,
          windowMinutesSecondary: 10080,
          capacityCreditsPrimary: 225,
          capacityCreditsSecondary: 1_764,
        }),
        account({
          accountId: "acc-2",
          email: "two@example.com",
          usage: {
            primaryRemainingPercent: 80,
            secondaryRemainingPercent: 100,
          },
          resetAtPrimary: null,
          resetAtSecondary: null,
          windowMinutesPrimary: 300,
          windowMinutesSecondary: 10080,
          capacityCreditsPrimary: 225,
          capacityCreditsSecondary: 1_764,
        }),
      ],
    });

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);
    const burn = view.stats[3];

    // Without reset times there is nothing to extrapolate: demand = used credits.
    // 5h: (0.5 + 0.2) x 225 / 450 = 0.35x; 7d: 0.75 x 1,764 / 3,528 = 0.375x.
    expect(burn.label).toBe("Pool burn projection (5h/7d)");
    expect(burn.value).toBe("0.35× / 0.38×");
    expect(burn.meta).toBe("1.32K of 3.53K credits by reset · no account runs out before reset");
    expect(view.stats[4]?.label).toBe("Error rate (7d)");
  });

  it("projects pool burn in credits without clamping and names the first account to run out", () => {
    // Live h015a shape (2026-10-15): weekly-only pool, 19.6 h into the week.
    const now = Date.parse("2026-10-16T01:36:00Z");
    const resetIn = (hours: number) => new Date(now + hours * 3_600_000).toISOString();
    const weekly = (id: string, used: number, capacity: number) =>
      account({
        accountId: id,
        email: `${id}@example.com`,
        usage: { primaryRemainingPercent: null, secondaryRemainingPercent: 100 - used },
        resetAtSecondary: resetIn(168 - 19.6),
        windowMinutesPrimary: null,
        windowMinutesSecondary: 10_080,
        capacityCreditsSecondary: capacity,
      });
    const overview = createDashboardOverview({
      accounts: [weekly("pro", 7, 35_280), weekly("lite-a", 25, 8_820), weekly("lite-b", 26, 8_820)],
    });
    vi.useFakeTimers();
    vi.setSystemTime(now);
    try {
      const burn = buildDashboardView(overview, createDefaultRequestLogs(), false).stats[3];
      // Account-count version showed min(0.60 + 2.14 + 2.24, 3) = "3.0".
      // Credits: (0.07x35,280 + 0.25x8,820 + 0.26x8,820) x 168/19.6 = 59.7K of 52.9K.
      expect(burn.label).toBe("Pool burn projection (7d)");
      expect(burn.value).toBe("1.13×");
      expect(burn.meta).toBe("59.72K of 52.92K credits by reset · lite-b@example.com runs out in ~2d 8h · low confidence (<24h of data)");
    } finally {
      vi.useRealTimers();
    }
  });

  it("can hide the account burn rate card", () => {
    const overview = createDashboardOverview();

    const view = buildDashboardView(overview, createDefaultRequestLogs(), {
      isDark: false,
      showAccountBurnrate: false,
    });

    expect(view.stats.map((stat) => stat.label).some((label) => label.startsWith("Pool burn projection"))).toBe(false);
    expect(view.stats).toHaveLength(4);
  });

  it("counts quota-exceeded secondary windows as fully burned", () => {
    const overview = createDashboardOverview({
      accounts: [
        account({
          accountId: "acc-1",
          email: "one@example.com",
          status: "quota_exceeded",
          usage: {
            primaryRemainingPercent: 100,
            secondaryRemainingPercent: 80,
          },
          resetAtPrimary: null,
          resetAtSecondary: null,
          windowMinutesPrimary: 300,
          windowMinutesSecondary: 10080,
          capacityCreditsPrimary: 225,
          capacityCreditsSecondary: 1_764,
        }),
      ],
    });

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);
    const burn = view.stats[3];

    // Quota-exceeded counts as a fully used weekly window regardless of the sample.
    expect(burn.value).toBe("0.00× / 1.00×");
  });

  it("rounds 'runs out in' to whole hours before splitting off days (#29)", () => {
    expect(formatBurnHours(47.6)).toBe("~2d 0h");
    expect(formatBurnHours(23.5)).toBe("~1d 0h");
    expect(formatBurnHours(23.4)).toBe("~23h");
    expect(formatBurnHours(55.78)).toBe("~2d 8h");
    expect(formatBurnHours(0.2)).toBe("~1h");
    expect(formatBurnHours(0)).toBe("now");
  });

  it("names the 5h cutoff in the low-confidence note when the 5h projection is the headline (#29)", () => {
    const now = Date.parse("2026-10-16T01:36:00Z");
    const overview = createDashboardOverview({
      accounts: [
        account({
          accountId: "plus",
          email: "plus@example.com",
          usage: { primaryRemainingPercent: 90, secondaryRemainingPercent: null },
          // 30 minutes into the 5 h window: under the 5 h / 7 (about 43 min) cutoff.
          resetAtPrimary: new Date(now + 4.5 * 3_600_000).toISOString(),
          windowMinutesPrimary: 300,
          windowMinutesSecondary: null,
          capacityCreditsPrimary: 225,
        }),
      ],
    });
    vi.useFakeTimers();
    vi.setSystemTime(now);
    try {
      const burn = buildDashboardView(overview, createDefaultRequestLogs(), false).stats[3];
      expect(burn.meta).toContain("low confidence (<43 min of data)");
      expect(burn.meta).not.toContain("24h");
    } finally {
      vi.useRealTimers();
    }
  });

  it("treats an elapsed reset as a full window and does not extrapolate (#29)", () => {
    const now = Date.parse("2026-10-16T01:36:00Z");
    const overview = createDashboardOverview({
      accounts: [
        account({
          accountId: "stale",
          email: "stale@example.com",
          usage: { primaryRemainingPercent: null, secondaryRemainingPercent: 40 },
          resetAtSecondary: new Date(now - 3_600_000).toISOString(),
          windowMinutesPrimary: null,
          windowMinutesSecondary: 10_080,
          capacityCreditsSecondary: 8_820,
        }),
      ],
    });
    vi.useFakeTimers();
    vi.setSystemTime(now);
    try {
      const burn = buildDashboardView(overview, createDefaultRequestLogs(), false).stats[3];
      // Hours until reset clamp to 0, so elapsed is the whole window: demand is
      // the used share, nothing can run out before a reset that already passed,
      // and a full window of data is not low confidence.
      expect(burn.value).toBe("0.60×");
      expect(burn.meta).toBe("5.29K of 8.82K credits by reset · no account runs out before reset");
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves paused and deactivated accounts out of the pool burn projection (#31)", () => {
    const weekly = (id: string, status: string, used: number, capacity: number) =>
      account({
        accountId: id,
        email: `${id}@example.com`,
        status,
        usage: { primaryRemainingPercent: null, secondaryRemainingPercent: 100 - used },
        resetAtSecondary: null,
        windowMinutesPrimary: null,
        windowMinutesSecondary: 10_080,
        capacityCreditsSecondary: capacity,
      });
    const overview = createDashboardOverview({
      accounts: [
        weekly("active", "active", 50, 8_820),
        weekly("paused", "paused", 0, 35_280),
        weekly("gone", "deactivated", 100, 8_820),
      ],
    });

    const burn = buildDashboardView(overview, createDefaultRequestLogs(), false).stats[3];

    // Only the active Pro Lite counts: 0.5 x 8,820 of 8,820. The paused Pro's
    // 35,280 of idle capacity and the deactivated account's frozen 100 % are out.
    expect(burn.label).toBe("Pool burn projection (7d)");
    expect(burn.value).toBe("0.50×");
    expect(burn.meta).toBe("4.41K of 8.82K credits by reset · no account runs out before reset");
  });

  it("shows only the averaged cost text on the estimated cost card", () => {
    const weeklyView = buildDashboardView(
      createDashboardOverview({
        summary: {
          primaryWindow: {
            remainingPercent: 63.5,
            capacityCredits: 225,
            remainingCredits: 142.875,
            resetAt: null,
            windowMinutes: 300,
          },
          secondaryWindow: {
            remainingPercent: 55.2,
            capacityCredits: 7560,
            remainingCredits: 4173.12,
            resetAt: null,
            windowMinutes: 10080,
          },
          cost: {
            currency: "USD",
            totalUsd: 56,
          },
          metrics: {
            requests: 228,
            conversations: 0,
            conversationRequests: 0,
            tokens: 45000,
            cachedInputTokens: 8200,
            errorRate: 0.028,
            errorCount: 6,
            topError: "rate_limit_exceeded",
          },
        },
      }),
      createDefaultRequestLogs(),
      false,
    );

    const dailyView = buildDashboardView(
      createDashboardOverview({
        timeframe: {
          key: "1d",
          windowMinutes: 1440,
          bucketSeconds: 3600,
          bucketCount: 24,
        },
        summary: {
          primaryWindow: {
            remainingPercent: 63.5,
            capacityCredits: 225,
            remainingCredits: 142.875,
            resetAt: null,
            windowMinutes: 300,
          },
          secondaryWindow: {
            remainingPercent: 55.2,
            capacityCredits: 7560,
            remainingCredits: 4173.12,
            resetAt: null,
            windowMinutes: 10080,
          },
          cost: {
            currency: "USD",
            totalUsd: 24,
          },
          metrics: {
            requests: 228,
            conversations: 0,
            conversationRequests: 0,
            tokens: 45000,
            cachedInputTokens: 8200,
            errorRate: 0.028,
            errorCount: 6,
            topError: "rate_limit_exceeded",
          },
        },
      }),
      createDefaultRequestLogs(),
      false,
    );

    expect(weeklyView.stats[2]?.meta).toBe("Avg/day $8.00");
    expect(dailyView.stats[2]?.meta).toBe("Avg/hr $1.00");
  });

  it("adds previous-window comparison indicators to requests tokens and cost cards", () => {
    const overview = createDashboardOverview();

    const view = buildDashboardView(
      {
        ...overview,
        summary: {
          ...overview.summary,
          metrics: {
            requests: 1500,
            conversations: 0,
            conversationRequests: 0,
            tokens: 450,
            cachedInputTokens: 0,
            errorRate: 0.028,
            errorCount: 6,
            topError: "rate_limit_exceeded",
          },
          cost: {
            currency: "USD",
            totalUsd: 15,
          },
          comparison: {
            canCompare: true,
            previous: {
              requests: 1000,
              tokens: 900,
              costUsd: 10,
            },
          },
        },
      },
      createDefaultRequestLogs(),
      false,
    );

    expect(view.stats[0]?.comparison).toEqual({ text: "▲ 50%", tone: "positive" });
    expect(view.stats[1]?.comparison).toEqual({ text: "▼ 50%", tone: "negative" });
    expect(view.stats[2]?.comparison).toEqual({ text: "▲ 50%", tone: "positive" });
    expect(view.stats[view.stats.length - 1]?.comparison).toBeUndefined();
  });

  it("hides comparison indicators for sub-percent deltas that would round to 0%", () => {
    const overview = createDashboardOverview();

    const view = buildDashboardView(
      {
        ...overview,
        summary: {
          ...overview.summary,
          metrics: {
            requests: 1001,
            conversations: 0,
            conversationRequests: 0,
            tokens: 999,
            cachedInputTokens: 0,
            errorRate: 0.028,
            errorCount: 6,
            topError: "rate_limit_exceeded",
          },
          cost: {
            currency: "USD",
            totalUsd: 10.04,
          },
          comparison: {
            canCompare: true,
            previous: {
              requests: 1000,
              tokens: 1000,
              costUsd: 10,
            },
          },
        },
      },
      createDefaultRequestLogs(),
      false,
    );

    expect(view.stats[0]?.comparison).toBeUndefined();
    expect(view.stats[1]?.comparison).toBeUndefined();
    expect(view.stats[2]?.comparison).toBeUndefined();
  });

  it("hides previous-window comparison indicators when comparison is unavailable or previous totals are zero", () => {
    const overview = createDashboardOverview();

    const unavailableView = buildDashboardView(
      {
        ...overview,
        summary: {
          ...overview.summary,
          comparison: {
            canCompare: false,
            previous: {
              requests: 1000,
              tokens: 1000,
              costUsd: 10,
            },
          },
        },
      },
      createDefaultRequestLogs(),
      false,
    );

    expect(unavailableView.stats[0]?.comparison).toBeUndefined();
    expect(unavailableView.stats[1]?.comparison).toBeUndefined();
    expect(unavailableView.stats[2]?.comparison).toBeUndefined();

    const zeroPreviousView = buildDashboardView(
      {
        ...overview,
        summary: {
          ...overview.summary,
          comparison: {
            canCompare: true,
            previous: {
              requests: 0,
              tokens: 0,
              costUsd: 0,
            },
          },
        },
      },
      createDefaultRequestLogs(),
      false,
    );

    expect(zeroPreviousView.stats[0]?.comparison).toBeUndefined();
    expect(zeroPreviousView.stats[1]?.comparison).toBeUndefined();
    expect(zeroPreviousView.stats[2]?.comparison).toBeUndefined();
  });

  it("places Conversations stat after Est. API Cost and before optional burn-rate/Error Rate", () => {
    const overview = createDashboardOverview({
      summary: {
        primaryWindow: {
          remainingPercent: 80,
          capacityCredits: 100,
          remainingCredits: 80,
          resetAt: null,
          windowMinutes: 300,
        },
        secondaryWindow: null,
        cost: { currency: "USD", totalUsd: 12.5 },
        metrics: {
          requests: 500,
          conversationRequests: 0,
          tokens: 2000,
          cachedInputTokens: 300,
          errorRate: 0.02,
          errorCount: 10,
          topError: null,
          conversations: 42,
        },
      },
    });

    const viewWithoutBurn = buildDashboardView(overview, createDefaultRequestLogs(), false);

    const costIdx = viewWithoutBurn.stats.findIndex((s) => s.label.includes("API-equivalent cost"));
    const convIdx = viewWithoutBurn.stats.findIndex((s) => s.label.includes("Conversations"));
    const errorIdx = viewWithoutBurn.stats.findIndex((s) => s.label.includes("Error rate"));

    expect(convIdx).toBeGreaterThan(costIdx);
    expect(convIdx).toBeGreaterThan(-1);
    expect(errorIdx).toBeGreaterThan(convIdx);

    // With burn-rate enabled, conversation should still be between cost and burn-rate
    const viewWithBurn = buildDashboardView(overview, createDefaultRequestLogs(), { isDark: false, showAccountBurnrate: true });

    const costIdxB = viewWithBurn.stats.findIndex((s) => s.label.includes("API-equivalent cost"));
    const convIdxB = viewWithBurn.stats.findIndex((s) => s.label.includes("Conversations"));
    const burnIdxB = viewWithBurn.stats.findIndex((s) => s.label.includes("Pool burn"));
    const errorIdxB = viewWithBurn.stats.findIndex((s) => s.label.includes("Error rate"));

    expect(convIdxB).toBeGreaterThan(costIdxB);
    expect(burnIdxB).toBeGreaterThan(convIdxB);
    expect(errorIdxB).toBeGreaterThan(burnIdxB);
  });

  it("omits Conversations stat when metrics.conversations is null/undefined", () => {
    const overview = createDashboardOverview({
      summary: {
        primaryWindow: {
          remainingPercent: 80,
          capacityCredits: 100,
          remainingCredits: 80,
          resetAt: null,
          windowMinutes: 300,
        },
        secondaryWindow: null,
        cost: { currency: "USD", totalUsd: 12.5 },
        metrics: {
          requests: 500,
          conversationRequests: 0,
          tokens: 2000,
          cachedInputTokens: 300,
          errorRate: 0.02,
          errorCount: 10,
          topError: null,
          conversations: null,
        },
      },
    });

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);
    const convIdx = view.stats.findIndex((s) => s.label.includes("Conversations"));
    expect(convIdx).toBe(-1);
  });

  it("omits Conversations stat when metrics.conversations is entirely absent", () => {
    const overview = createDashboardOverview({
      summary: {
        primaryWindow: {
          remainingPercent: 80,
          capacityCredits: 100,
          remainingCredits: 80,
          resetAt: null,
          windowMinutes: 300,
        },
        secondaryWindow: null,
        cost: { currency: "USD", totalUsd: 12.5 },
        metrics: {
          requests: 500,
          conversationRequests: 0,
          tokens: 2000,
          cachedInputTokens: 300,
          errorRate: 0.02,
          errorCount: 10,
          topError: null,
        } as Record<string, unknown>,
      },
    } as Parameters<typeof buildDashboardView>[0]);

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);
    const convIdx = view.stats.findIndex((s) => s.label.includes("Conversations"));
    expect(convIdx).toBe(-1);
  });

  it("formats Conversations stat as integer with thousand grouping, not compact abbreviation", () => {
    const overview = createDashboardOverview({
      summary: {
        primaryWindow: {
          remainingPercent: 80,
          capacityCredits: 100,
          remainingCredits: 80,
          resetAt: null,
          windowMinutes: 300,
        },
        secondaryWindow: null,
        cost: { currency: "USD", totalUsd: 12.5 },
        metrics: {
          requests: 500,
          conversationRequests: 0,
          tokens: 2000,
          cachedInputTokens: 300,
          errorRate: 0.02,
          errorCount: 10,
          topError: null,
          conversations: 1200,
        },
      },
    });

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);
    const convStat = view.stats.find((s) => s.label.includes("Conversations"));
    expect(convStat?.value).toBe("1,200");
    expect(convStat?.meta).toBe("Avg req/conv 0.0 · 0 sessions");
  });

  it("formats Conversations stat above 1000 as grouped integer, not as '1.2K'", () => {
    const overview = createDashboardOverview({
      summary: {
        primaryWindow: {
          remainingPercent: 80,
          capacityCredits: 100,
          remainingCredits: 80,
          resetAt: null,
          windowMinutes: 300,
        },
        secondaryWindow: null,
        cost: { currency: "USD", totalUsd: 12.5 },
        metrics: {
          requests: 500,
          conversationRequests: 0,
          tokens: 2000,
          cachedInputTokens: 300,
          errorRate: 0.02,
          errorCount: 10,
          topError: null,
          conversations: 1523,
        },
      },
    });

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);
    const convStat = view.stats.find((s) => s.label.includes("Conversations"));
    expect(convStat?.value).toBe("1,523");
    // Must not use compact format
    expect(convStat?.value).not.toContain("K");
    expect(convStat?.value).not.toContain(".");
  });

  it("renders Avg req/conv metadata with one decimal ratio", () => {
    const overview = createDashboardOverview({
      summary: {
        primaryWindow: {
          remainingPercent: 80,
          capacityCredits: 100,
          remainingCredits: 80,
          resetAt: null,
          windowMinutes: 300,
        },
        secondaryWindow: null,
        cost: { currency: "USD", totalUsd: 12.5 },
        metrics: {
          requests: 500,
          tokens: 2000,
          cachedInputTokens: 300,
          errorRate: 0.02,
          errorCount: 10,
          topError: null,
          conversations: 2,
          conversationRequests: 5,
        },
      },
    } as Parameters<typeof buildDashboardView>[0]);

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);
    const convStat = view.stats.find((s) => s.label.includes("Conversations + sessions"));
    expect(convStat).toBeDefined();
    expect(convStat?.label).toBe("Conversations + sessions (7d)");
    expect(convStat?.meta).toBe("Avg req/conv 2.5 · 0 sessions");
  });

  it("renders em-dash Avg req/conv metadata when conversations is zero", () => {
    const overview = createDashboardOverview({
      summary: {
        primaryWindow: {
          remainingPercent: 80,
          capacityCredits: 100,
          remainingCredits: 80,
          resetAt: null,
          windowMinutes: 300,
        },
        secondaryWindow: null,
        cost: { currency: "USD", totalUsd: 12.5 },
        metrics: {
          requests: 500,
          tokens: 2000,
          cachedInputTokens: 300,
          errorRate: 0.02,
          errorCount: 10,
          topError: null,
          conversations: 0,
          conversationRequests: 4,
        },
      },
    } as Parameters<typeof buildDashboardView>[0]);

    const view = buildDashboardView(overview, createDefaultRequestLogs(), false);
    const convStat = view.stats.find((s) => s.label.includes("Conversations + sessions"));
    expect(convStat).toBeDefined();
    expect(convStat?.meta).toBe("Avg req/conv — · 0 sessions");
  });
});
