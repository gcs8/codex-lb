import { Activity, AlertTriangle, Coins, DollarSign, Flame, MessageSquare, type LucideIcon } from "lucide-react";

import i18n from "@/i18n";
import type {
  AccountSummary,
  DashboardOverview,
  DashboardProjections,
  Depletion,
  RequestLog,
  ServerWeeklyCreditPace,
  TrendPoint,
  UsageWindow,
  WeeklyCreditPaceStatus,
} from "@/features/dashboard/schemas";
import { formatCompactAccountId } from "@/utils/account-identifiers";
import { buildDonutPalette } from "@/utils/colors";
import {
  formatCachedTokensMeta,
  formatCompactNumber,
  formatCurrency,
  formatNumber,
  formatRate,
  formatWindowMinutes,
} from "@/utils/formatters";
import { PRO_WEEKLY_CAPACITY_CREDITS } from "@/features/dashboard/capacity";

function t(key: string, options?: Record<string, unknown>): string {
  return i18n.t(key, options);
}

export type RemainingItem = {
  accountId: string;
  label: string;
  /** Suffix appended after the label (e.g. compact account ID for duplicates). Not blurred. */
  labelSuffix: string;
  /** True when the displayed label is the account email (should be blurred in privacy mode). */
  isEmail: boolean;
  value: number;
  remainingPercent: number | null;
  color: string;
};

export type DashboardStat = {
  label: string;
  value: string;
  meta?: string;
  comparison?: DashboardStatComparison;
  icon: LucideIcon;
  trend: { value: number }[];
  trendColor: string;
};

export type DashboardStatComparison = {
  text: string;
  tone: "positive" | "negative" | "neutral";
};

export interface SafeLineView {
  safePercent: number;
  riskLevel: "safe" | "warning" | "danger" | "critical";
}

/**
 * View-model weekly pace, derived from the Zod wire contract in schemas.ts so
 * the shapes cannot drift apart. Runway fields are absent when the backend
 * predates the runway model.
 */
export type WeeklyCreditPace = ServerWeeklyCreditPace;
export type {
  WeeklyCreditApiKeyAttribution,
  WeeklyCreditPaceStatus,
  WeeklyCreditResetEvent,
  WeeklyCreditRunwayStatus,
} from "@/features/dashboard/schemas";

export type DashboardView = {
  stats: DashboardStat[];
  primaryUsageItems: RemainingItem[];
  // False when no account reports a 5 h window (e.g. Pro / Pro 100 plans are
  // weekly-only); the 5 h donut is hidden rather than shown as exhausted.
  hasPrimaryWindow: boolean;
  secondaryUsageItems: RemainingItem[];
  /** Sum of visible primary remaining items shown in the donut center label. */
  primaryTotal: number;
  /** Sum of visible secondary remaining items shown in the donut center label. */
  secondaryTotal: number;
  requestLogs: RequestLog[];
  safeLinePrimary: SafeLineView | null;
  safeLineSecondary: SafeLineView | null;
  weeklyCreditPace: WeeklyCreditPace | null;
};

type DashboardViewOptions = {
  isDark?: boolean;
  showAccountBurnrate?: boolean;
};

function resolveDashboardViewOptions(optionsOrIsDark: DashboardViewOptions | boolean): Required<DashboardViewOptions> {
  if (typeof optionsOrIsDark === "boolean") {
    return {
      isDark: optionsOrIsDark,
      showAccountBurnrate: true,
    };
  }
  return {
    isDark: optionsOrIsDark.isDark ?? false,
    showAccountBurnrate: optionsOrIsDark.showAccountBurnrate ?? true,
  };
}

export function buildDepletionView(depletion: Depletion | null | undefined): SafeLineView | null {
  if (!depletion || depletion.riskLevel === "safe") return null;
  return { safePercent: depletion.safeUsagePercent, riskLevel: depletion.riskLevel };
}

function buildWindowIndex(window: UsageWindow | null): Map<string, number> {
  const index = new Map<string, number>();
  if (!window) {
    return index;
  }
  for (const entry of window.accounts) {
    index.set(entry.accountId, entry.remainingCredits);
  }
  return index;
}

function isWeeklyOnlyAccount(account: AccountSummary): boolean {
  return account.windowMinutesPrimary == null && account.windowMinutesSecondary != null;
}

function isMonthlyOnlyAccount(account: AccountSummary): boolean {
  return (
    account.windowMinutesMonthly != null &&
    account.windowMinutesPrimary == null &&
    account.windowMinutesSecondary == null
  );
}

function accountRemainingPercent(account: AccountSummary, windowKey: "primary" | "secondary"): number | null {
  if (windowKey === "secondary") {
    return account.usage?.secondaryRemainingPercent ?? null;
  }
  return account.usage?.primaryRemainingPercent ?? null;
}

/**
 * Cap primary (5h) remaining by secondary (7d) absolute credits.
 *
 * The 7d window is a hard quota gate — when its remaining credits are lower
 * than the 5h remaining credits, the account can only use up to the 7d amount
 * regardless of 5h headroom.  Comparing absolute credits (not percentages) is
 * essential because the two windows have vastly different capacities
 * (e.g. 225 vs 7 560 for Plus plans).
 */
export function applySecondaryConstraint(
  primaryItems: RemainingItem[],
  secondaryItems: RemainingItem[],
): RemainingItem[] {
  const secondaryByAccount = new Map<string, RemainingItem>();
  for (const item of secondaryItems) {
    secondaryByAccount.set(item.accountId, item);
  }

  return primaryItems.map((item) => {
    const secondaryItem = secondaryByAccount.get(item.accountId);
    if (!secondaryItem) return item;
    if (secondaryItem.remainingPercent == null) return item;
    if (secondaryItem.value >= item.value) return item;

    const effectivePercent =
      item.remainingPercent != null && item.value > 0
        ? item.remainingPercent * (secondaryItem.value / item.value)
        : item.remainingPercent;

    return {
      ...item,
      value: Math.max(0, secondaryItem.value),
      remainingPercent: effectivePercent != null ? Math.max(0, effectivePercent) : null,
    };
  });
}

export function buildRemainingItems(
  accounts: AccountSummary[],
  window: UsageWindow | null,
  windowKey: "primary" | "secondary",
  isDark = false,
): RemainingItem[] {
  const usageIndex = buildWindowIndex(window);
  const palette = buildDonutPalette(accounts.length, isDark);
  return accounts
    .map((account, index) => {
      if (isMonthlyOnlyAccount(account)) {
        return null;
      }
      if (windowKey === "primary" && isWeeklyOnlyAccount(account)) {
        return null;
      }
      const remaining = usageIndex.get(account.accountId) ?? 0;
      const rawLabel = account.displayName || account.email || account.accountId;
      const labelIsEmail = !!account.email && rawLabel === account.email;
      const labelSuffix = account.isEmailDuplicate === true
        ? ` (${formatCompactAccountId(account.accountId, 5, 4)})`
        : "";
      return {
        accountId: account.accountId,
        label: rawLabel,
        labelSuffix,
        isEmail: labelIsEmail,
        value: remaining,
        remainingPercent: accountRemainingPercent(account, windowKey),
        color: palette[index % palette.length],
      };
    })
    .filter((item): item is RemainingItem => item !== null);
}

function avgPerUnit(total: number, units: number): number {
  if (!Number.isFinite(total) || total <= 0 || units <= 0) {
    return 0;
  }
  return total / units;
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value));
}

function buildStatComparison(
  current: number | null | undefined,
  previous: number,
  canCompare: boolean,
): DashboardStatComparison | undefined {
  if (!canCompare || !isFiniteNumber(current) || previous <= 0) {
    return undefined;
  }

  const deltaPercent = ((current - previous) / previous) * 100;
  const roundedPercent = Math.round(Math.abs(deltaPercent));
  if (roundedPercent === 0) {
    return undefined;
  }
  if (deltaPercent > 0) {
    return { text: `▲ ${roundedPercent}%`, tone: "positive" };
  }
  if (deltaPercent < 0) {
    return { text: `▼ ${roundedPercent}%`, tone: "negative" };
  }
  return undefined;
}

type PoolBurnProjection = {
  // Projected end-of-window demand as a multiple of pool capacity (credits, not
  // account counts), so it is never clamped and mixed plans weigh by capacity.
  ratio: number;
  demandCredits: number;
  poolCredits: number;
  // First account projected to reach 100 % before its own reset, if any.
  firstExhaustion: { label: string; inHours: number } | null;
  lowConfidence: boolean;
  // Elapsed-hours cutoff below which the projection is flagged low confidence
  // (24 h for the weekly window, windowHours / 7 for shorter ones).
  lowConfidenceCutoffHours: number;
};

const BURN_LOW_CONFIDENCE_MAX_HOURS = 24;
// Routing never uses these accounts, so they are neither supply nor demand.
// Mirrors the pace card's PACE_ELIGIBLE_ACCOUNT_STATUSES (gcs8/codex-lb#31).
const BURN_EXCLUDED_ACCOUNT_STATUSES = new Set(["paused", "deactivated"]);

function projectPoolBurn(
  overview: DashboardOverview,
  windowKey: "primary" | "secondary",
  nowMs: number = Date.now(),
): PoolBurnProjection | null {
  let demandCredits = 0;
  let poolCredits = 0;
  let included = 0;
  let lowConfidence = false;
  let lowConfidenceCutoffHours = 0;
  let firstExhaustion: PoolBurnProjection["firstExhaustion"] = null;

  for (const account of overview.accounts) {
    if (BURN_EXCLUDED_ACCOUNT_STATUSES.has(account.status)) {
      continue;
    }
    const windowMinutes = windowKey === "primary" ? account.windowMinutesPrimary : account.windowMinutesSecondary;
    const remainingPercent =
      windowKey === "primary" ? account.usage?.primaryRemainingPercent : account.usage?.secondaryRemainingPercent;
    const capacity = windowKey === "primary" ? account.capacityCreditsPrimary : account.capacityCreditsSecondary;
    const resetAt = windowKey === "primary" ? account.resetAtPrimary : account.resetAtSecondary;
    if (windowMinutes == null || windowMinutes <= 0 || !isFiniteNumber(remainingPercent)) {
      continue;
    }
    if (!isFiniteNumber(capacity) || capacity <= 0) {
      continue;
    }

    let used = (100 - clampPercent(remainingPercent)) / 100;
    if (windowKey === "secondary" && account.status === "quota_exceeded") {
      used = Math.max(used, 1);
    }
    const windowHours = windowMinutes / 60;
    const cutoffHours = Math.min(BURN_LOW_CONFIDENCE_MAX_HOURS, windowHours / 7);
    lowConfidenceCutoffHours = Math.max(lowConfidenceCutoffHours, cutoffHours);
    let projectedFraction = used;
    const resetAtMs = resetAt ? Date.parse(resetAt) : Number.NaN;
    if (Number.isFinite(resetAtMs)) {
      const hoursUntilReset = Math.max(0, (resetAtMs - nowMs) / 3_600_000);
      const elapsedHours = Math.max(0, windowHours - hoursUntilReset);
      if (elapsedHours > 0) {
        projectedFraction = Math.max(used, (used * windowHours) / elapsedHours);
        if (elapsedHours < cutoffHours) {
          lowConfidence = true;
        }
        const hoursToFull = used >= 1 ? 0 : used > 0 ? ((1 - used) * elapsedHours) / used : Number.POSITIVE_INFINITY;
        if (hoursToFull < hoursUntilReset && (firstExhaustion === null || hoursToFull < firstExhaustion.inHours)) {
          firstExhaustion = {
            label: account.displayName || account.email || account.accountId,
            inHours: hoursToFull,
          };
        }
      } else {
        lowConfidence = true;
      }
    }

    demandCredits += projectedFraction * capacity;
    poolCredits += capacity;
    included += 1;
  }

  if (included === 0 || poolCredits <= 0) {
    return null;
  }
  return {
    ratio: demandCredits / poolCredits,
    demandCredits,
    poolCredits,
    firstExhaustion,
    lowConfidence,
    lowConfidenceCutoffHours,
  };
}

function formatBurnRatio(projection: PoolBurnProjection | null): string {
  if (projection === null || !Number.isFinite(projection.ratio)) {
    return "--";
  }
  return `${projection.ratio.toFixed(2)}×`;
}

export function formatBurnHours(hours: number): string {
  if (hours <= 0) {
    return "now";
  }
  // Round the total first: splitting before rounding let the remainder round
  // up to 24 and print "~1d 24h" (gcs8/codex-lb#29).
  const total = Math.max(1, Math.round(hours));
  const days = Math.floor(total / 24);
  const rest = total - days * 24;
  return days > 0 ? `~${days}d ${rest}h` : `~${rest}h`;
}

/** Elapsed-data span for the low-confidence note: whole hours, or minutes under an hour. */
export function formatBurnSpan(hours: number): string {
  if (hours >= 1) {
    return `${Math.round(hours)}h`;
  }
  return `${Math.max(1, Math.round(hours * 60))} min`;
}

function buildBurnTrend(points: TrendPoint[], currentValue: number | null): { value: number }[] {
  if (currentValue === null || !Number.isFinite(currentValue) || currentValue <= 0 || points.length === 0) {
    return [];
  }

  const lastPoint = points[points.length - 1]?.v ?? 0;
  if (!Number.isFinite(lastPoint) || lastPoint <= 0) {
    return points.map(() => ({ value: currentValue }));
  }

  const scale = currentValue / lastPoint;
  return points.map((point) => ({ value: Math.max(0, point.v * scale) }));
}

function formatBurnWindowLabel(windowKey: "primary" | "secondary", windowMinutes: number | null | undefined): string {
  const formatted = formatWindowMinutes(windowMinutes ?? null);
  if (formatted !== "--") {
    return formatted;
  }
  return windowKey === "primary" ? "5h" : "7d";
}

const TREND_COLORS = ["#3b82f6", "#8b5cf6", "#10b981", "#ef4444", "#f59e0b"];

function trendPointsToValues(points: TrendPoint[]): { value: number }[] {
  return points.map((p) => ({ value: p.v }));
}

/** Sum the `value` fields of remaining items (clamped to >= 0). */
export function sumRemaining(items: RemainingItem[]): number {
  return items.reduce((sum, item) => sum + Math.max(0, item.value), 0);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function isPositiveFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function isNonNegativeFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

export function weeklyCreditPaceStatus(deltaPercent: number, projectedShortfallCredits: number): WeeklyCreditPaceStatus {
  if (projectedShortfallCredits > 0) return "danger";
  if (deltaPercent < -5) return "behind";
  if (deltaPercent > 5) return "ahead";
  return "on_track";
}

type WeeklyPoolAccount = {
  fullCredits: number;
  remainingCredits: number;
  resetAtMs: number;
  windowMs: number;
};

type WeeklyPoolSimulationAccount = WeeklyPoolAccount & {
  balanceCredits: number;
};

type WeeklyPoolProjection = {
  burnRateCreditsPerMs: number;
  projectedShortfallCredits: number;
  projectedDepletionHours: number | null;
  projectedMinimumRemainingCredits: number;
  firstReplenishmentWaitMs: number | null;
};

type WeeklyResetEvent = {
  fullCredits: number;
  balanceCredits: number;
  resetAtMs: number;
  windowMs: number;
};

function totalWeeklyBalanceCredits(accounts: WeeklyPoolSimulationAccount[]): number {
  return accounts.reduce((sum, account) => sum + account.balanceCredits, 0);
}

function consumeWeeklyBalanceCredits(accounts: WeeklyPoolSimulationAccount[], amountCredits: number): void {
  let remainingToConsume = amountCredits;
  const spendOrder = accounts.toSorted((a, b) => a.resetAtMs - b.resetAtMs);

  for (const account of spendOrder) {
    if (remainingToConsume <= 0) {
      return;
    }

    const consumed = Math.min(account.balanceCredits, remainingToConsume);
    account.balanceCredits -= consumed;
    remainingToConsume -= consumed;
  }
}

function buildEmptyWeeklyPoolProjection(
  accounts: WeeklyPoolAccount[],
  burnRateCreditsPerMs: number,
  nowMs: number,
): WeeklyPoolProjection {
  const resetEvents = accounts
    .reduce<Array<Pick<WeeklyResetEvent, "fullCredits" | "resetAtMs">>>((events, account) => {
      if (account.resetAtMs > nowMs) {
        events.push({
          fullCredits: account.fullCredits,
          resetAtMs: account.resetAtMs,
        });
      }
      return events;
    }, [])
    .sort((a, b) => a.resetAtMs - b.resetAtMs);

  if (resetEvents.length === 0) {
    return {
      burnRateCreditsPerMs,
      projectedShortfallCredits: 0,
      projectedDepletionHours: 0,
      projectedMinimumRemainingCredits: 0,
      firstReplenishmentWaitMs: 0,
    };
  }

  let cursorMs = nowMs;
  let balanceCredits = 0;
  let minimumRemainingCredits = 0;
  let minimumRemainingAtMs = resetEvents[0].resetAtMs;

  for (const event of resetEvents) {
    const intervalMs = event.resetAtMs - cursorMs;
    balanceCredits -= burnRateCreditsPerMs * intervalMs;
    if (balanceCredits < minimumRemainingCredits) {
      minimumRemainingCredits = balanceCredits;
      minimumRemainingAtMs = event.resetAtMs;
    }
    balanceCredits += event.fullCredits;
    cursorMs = event.resetAtMs;
  }

  return {
    burnRateCreditsPerMs,
    projectedShortfallCredits: Math.max(0, -minimumRemainingCredits),
    projectedDepletionHours: 0,
    projectedMinimumRemainingCredits: 0,
    firstReplenishmentWaitMs: Math.max(0, minimumRemainingAtMs - nowMs),
  };
}

function buildWeeklyPoolProjection(accounts: WeeklyPoolAccount[], nowMs: number): WeeklyPoolProjection | null {
  const totalRemainingCredits = accounts.reduce((sum, account) => sum + account.remainingCredits, 0);
  const burnRateCreditsPerMs = accounts.reduce((sum, account) => {
    const usedCredits = Math.max(0, account.fullCredits - account.remainingCredits);
    const windowStartMs = account.resetAtMs - account.windowMs;
    const elapsedMs = nowMs - windowStartMs;
    if (usedCredits <= 0 || !Number.isFinite(elapsedMs) || elapsedMs <= 0) {
      return sum;
    }
    return sum + usedCredits / elapsedMs;
  }, 0);
  if (burnRateCreditsPerMs <= 0) {
    return null;
  }

  if (totalRemainingCredits <= 0) {
    return buildEmptyWeeklyPoolProjection(accounts, burnRateCreditsPerMs, nowMs);
  }

  const hasFutureReset = accounts.some((account) => account.resetAtMs > nowMs);
  if (!hasFutureReset) {
    return {
      burnRateCreditsPerMs,
      projectedShortfallCredits: 0,
      projectedDepletionHours: null,
      projectedMinimumRemainingCredits: totalRemainingCredits,
      firstReplenishmentWaitMs: null,
    };
  }

  const simulationAccounts: WeeklyPoolSimulationAccount[] = accounts.map((account) => ({
    ...account,
    balanceCredits: account.remainingCredits,
  }));
  const resetEvents: WeeklyResetEvent[] = simulationAccounts.filter((account) => account.resetAtMs > nowMs);

  let cursorMs = nowMs;
  let balanceCredits = totalRemainingCredits;
  let minimumRemainingCredits = totalRemainingCredits;
  const longestWindowMs = Math.max(...accounts.map((account) => account.windowMs));
  const horizonMs = nowMs + longestWindowMs * 2;

  while (cursorMs < horizonMs) {
    resetEvents.sort((a, b) => a.resetAtMs - b.resetAtMs);
    const event = resetEvents[0];
    const nextEventAtMs = Math.min(event.resetAtMs, horizonMs);
    const intervalMs = nextEventAtMs - cursorMs;
    const intervalBurnCredits = burnRateCreditsPerMs * intervalMs;
    if (intervalBurnCredits > balanceCredits) {
      const projectedShortfallCredits = intervalBurnCredits - balanceCredits;
      return {
        burnRateCreditsPerMs,
        projectedShortfallCredits,
        projectedDepletionHours: (cursorMs - nowMs + balanceCredits / burnRateCreditsPerMs) / 3_600_000,
        projectedMinimumRemainingCredits: 0,
        firstReplenishmentWaitMs: nextEventAtMs - nowMs,
      };
    }

    consumeWeeklyBalanceCredits(simulationAccounts, intervalBurnCredits);
    balanceCredits = totalWeeklyBalanceCredits(simulationAccounts);
    minimumRemainingCredits = Math.min(minimumRemainingCredits, balanceCredits);
    cursorMs = nextEventAtMs;
    if (cursorMs >= horizonMs) {
      break;
    }

    event.balanceCredits = event.fullCredits;
    event.resetAtMs += event.windowMs;
    balanceCredits = totalWeeklyBalanceCredits(simulationAccounts);
  }

  return {
    burnRateCreditsPerMs,
    projectedShortfallCredits: 0,
    projectedDepletionHours: null,
    projectedMinimumRemainingCredits: minimumRemainingCredits,
    firstReplenishmentWaitMs: null,
  };
}

function advanceWeeklyResetAt(resetAtMs: number, windowMs: number, nowMs: number): number {
  if (!Number.isFinite(resetAtMs) || !isPositiveFinite(windowMs) || !Number.isFinite(nowMs)) {
    return resetAtMs;
  }
  if (resetAtMs > nowMs) {
    return resetAtMs;
  }
  const missedWindows = Math.floor((nowMs - resetAtMs) / windowMs) + 1;
  return resetAtMs + missedWindows * windowMs;
}

export function buildWeeklyCreditPace(
  accounts: AccountSummary[],
  now: Date = new Date(),
): WeeklyCreditPace | null {
  const nowMs = now.getTime();
  if (!Number.isFinite(nowMs)) {
    return null;
  }

  let totalFullCredits = 0;
  let totalActualRemainingCredits = 0;
  let totalExpectedRemainingCredits = 0;
  let accountCount = 0;
  const weeklyAccounts: WeeklyPoolAccount[] = [];

  for (const account of accounts) {
    const fullCredits = account.capacityCreditsSecondary;
    const remainingCredits = account.remainingCreditsSecondary;
    const resetAtMs = account.resetAtSecondary ? Date.parse(account.resetAtSecondary) : Number.NaN;
    const windowMinutes = account.windowMinutesSecondary;

    if (
      !isPositiveFinite(fullCredits) ||
      !isNonNegativeFinite(remainingCredits) ||
      !Number.isFinite(resetAtMs) ||
      !isPositiveFinite(windowMinutes)
    ) {
      continue;
    }

    const windowMs = windowMinutes * 60_000;
    const effectiveResetAtMs = advanceWeeklyResetAt(resetAtMs, windowMs, nowMs);
    const timeLeftMs = clamp(effectiveResetAtMs - nowMs, 0, windowMs);
    const expectedRemainingCredits = fullCredits * (timeLeftMs / windowMs);
    const actualRemainingCredits = clamp(remainingCredits, 0, fullCredits);

    totalFullCredits += fullCredits;
    totalActualRemainingCredits += actualRemainingCredits;
    totalExpectedRemainingCredits += expectedRemainingCredits;
    accountCount += 1;
    weeklyAccounts.push({
      fullCredits,
      remainingCredits: actualRemainingCredits,
      resetAtMs: effectiveResetAtMs,
      windowMs,
    });
  }

  if (accountCount === 0 || totalFullCredits <= 0) {
    return null;
  }

  const actualUsedPercent = (100 * (totalFullCredits - totalActualRemainingCredits)) / totalFullCredits;
  const scheduledUsedPercent = (100 * (totalFullCredits - totalExpectedRemainingCredits)) / totalFullCredits;
  const deltaPercent = actualUsedPercent - scheduledUsedPercent;
  const scheduleGapCredits = Math.max(0, totalExpectedRemainingCredits - totalActualRemainingCredits);
  const scheduledBurnRateCreditsPerHour = weeklyAccounts.reduce(
    (sum, account) => sum + (account.fullCredits / account.windowMs) * 3_600_000,
    0,
  );
  const projection = buildWeeklyPoolProjection(weeklyAccounts, nowMs);
  const projectedShortfallCredits = projection?.projectedShortfallCredits ?? 0;
  const pauseForBreakEvenHours =
    projection && projectedShortfallCredits > 0 && projection.burnRateCreditsPerMs > 0
      ? projectedShortfallCredits / projection.burnRateCreditsPerMs / 3_600_000
      : null;
  const paceMultiplier =
    projection && projectedShortfallCredits > 0 && projection.burnRateCreditsPerMs > 0 && scheduledBurnRateCreditsPerHour > 0
      ? (projection.burnRateCreditsPerMs * 3_600_000) / scheduledBurnRateCreditsPerHour
      : null;
  const throttleToPercent =
    projection && projectedShortfallCredits > 0 && projection.firstReplenishmentWaitMs && projection.burnRateCreditsPerMs > 0
      ? clamp(
          ((projection.firstReplenishmentWaitMs * projection.burnRateCreditsPerMs - projectedShortfallCredits) /
            (projection.firstReplenishmentWaitMs * projection.burnRateCreditsPerMs)) *
            100,
          0,
          100,
        )
      : null;
  const reduceByPercent = throttleToPercent != null ? 100 - throttleToPercent : null;
  const proAccountEquivalentToCoverOverPlan =
    projectedShortfallCredits > 0 ? projectedShortfallCredits / PRO_WEEKLY_CAPACITY_CREDITS : null;
  const proAccountsToCoverOverPlan =
    projectedShortfallCredits > 0 ? Math.ceil(projectedShortfallCredits / PRO_WEEKLY_CAPACITY_CREDITS) : null;

  return {
    totalFullCredits,
    totalActualRemainingCredits,
    totalExpectedRemainingCredits,
    actualUsedPercent,
    scheduledUsedPercent,
    deltaPercent,
    scheduleGapCredits,
    smoothedDeltaPercent: deltaPercent,
    smoothedScheduleGapCredits: scheduleGapCredits,
    paceGapSmoothingMinutes: 0,
    overPlanCredits: scheduleGapCredits,
    projectedShortfallCredits,
    pauseForBreakEvenHours,
    paceMultiplier,
    throttleToPercent,
    reduceByPercent,
    proAccountEquivalentToCoverOverPlan,
    proAccountsToCoverOverPlan,
    projectedDepletionHours: projection?.projectedDepletionHours ?? null,
    projectedMinimumRemainingCredits: projection?.projectedMinimumRemainingCredits ?? null,
    forecastBurnRateCreditsPerHour: projection ? projection.burnRateCreditsPerMs * 3_600_000 : null,
    scheduledBurnRateCreditsPerHour,
    status: weeklyCreditPaceStatus(deltaPercent, projectedShortfallCredits),
    accountCount,
    staleAccountCount: 0,
    inactiveAccountCount: 0,
    confidence: "low",
  };
}

export function buildDashboardView(
  overview: DashboardOverview,
  requestLogs: RequestLog[],
  optionsOrIsDark: DashboardViewOptions | boolean = false,
  projections?: DashboardProjections,
): DashboardView {
  const { isDark, showAccountBurnrate } = resolveDashboardViewOptions(optionsOrIsDark);
  const primaryWindow = overview.windows.primary;
  const secondaryWindow = overview.windows.secondary;
  const metrics = overview.summary.metrics;
  const cost = overview.summary.cost.totalUsd;
  const timeframeLabel = (() => {
    const formatted = formatWindowMinutes(overview.timeframe.windowMinutes);
    return formatted === "--" ? overview.timeframe.key : formatted;
  })();
  const timeframeHours = overview.timeframe.windowMinutes / 60;
  const timeframeDays = overview.timeframe.windowMinutes / 1440;
  const requestMeta =
    timeframeHours <= 24
      ? t("dashboard.stats.avgPerHour", { value: formatCompactNumber(Math.round(avgPerUnit(metrics?.requests ?? 0, timeframeHours))) })
      : t("dashboard.stats.avgPerDay", { value: formatCompactNumber(Math.round(avgPerUnit(metrics?.requests ?? 0, timeframeDays))) });
  const costAverage =
    timeframeHours <= 24
      ? t("dashboard.stats.avgPerHour", { value: formatCurrency(avgPerUnit(cost, timeframeHours)) })
      : t("dashboard.stats.avgPerDay", { value: formatCurrency(avgPerUnit(cost, timeframeDays)) });
  const costMeta = costAverage;
  const trends = overview.trends;
  const primaryBurnLabel = formatBurnWindowLabel("primary", overview.summary.primaryWindow.windowMinutes);
  const secondaryBurnLabel = formatBurnWindowLabel("secondary", overview.summary.secondaryWindow?.windowMinutes);
  const showPrimaryBurn = overview.accounts.some((account) => account.windowMinutesPrimary != null);
  const primaryBurn = showPrimaryBurn ? projectPoolBurn(overview, "primary") : null;
  const secondaryBurn = projectPoolBurn(overview, "secondary");
  const combinedBurnRatio =
    (primaryBurn?.ratio ?? 0) + (secondaryBurn?.ratio ?? 0) > 0
      ? (primaryBurn?.ratio ?? 0) + (secondaryBurn?.ratio ?? 0)
      : null;
  const comparison = overview.summary.comparison;
  const canCompare = comparison?.canCompare ?? false;

  const stats: DashboardStat[] = [
    {
      label: t("dashboard.stats.requests", { timeframe: timeframeLabel }),
      value: formatCompactNumber(metrics?.requests ?? 0),
      meta: requestMeta,
      comparison: buildStatComparison(metrics?.requests, comparison?.previous.requests ?? 0, canCompare),
      icon: Activity,
      trend: trendPointsToValues(trends.requests),
      trendColor: TREND_COLORS[0],
    },
    {
      label: t("dashboard.stats.tokens", { timeframe: timeframeLabel }),
      value: formatCompactNumber(metrics?.tokens ?? 0),
      meta: formatCachedTokensMeta(metrics?.tokens, metrics?.cachedInputTokens),
      comparison: buildStatComparison(metrics?.tokens, comparison?.previous.tokens ?? 0, canCompare),
      icon: Coins,
      trend: trendPointsToValues(trends.tokens),
      trendColor: TREND_COLORS[1],
    },
    {
      label: t("dashboard.stats.estimatedCost", { timeframe: timeframeLabel }),
      value: formatCurrency(cost),
      meta: costMeta,
      comparison: buildStatComparison(cost, comparison?.previous.costUsd ?? 0, canCompare),
      icon: DollarSign,
      trend: trendPointsToValues(trends.cost),
      trendColor: TREND_COLORS[2],
    },
  ];

  const conversationCount = metrics?.conversations !== null && metrics?.conversations !== undefined ? metrics.conversations : null;
  if (conversationCount !== null) {
    const averageRequestsPerConversation =
      conversationCount > 0
        ? ((metrics?.conversationRequests ?? 0) / conversationCount).toFixed(1)
        : "—";

    const sessionCount = metrics?.sessions ?? 0;
    stats.push({
      label: t("dashboard.stats.conversationsAndSessions", { timeframe: timeframeLabel }),
      value: formatNumber(conversationCount + sessionCount),
      meta: t("dashboard.stats.conversationsSessionsMeta", {
        conversations: formatNumber(conversationCount),
        sessions: formatNumber(sessionCount),
        value: averageRequestsPerConversation,
      }),
      icon: MessageSquare,
      trend: trendPointsToValues(trends.conversations),
      trendColor: TREND_COLORS[3],
    });
  }

  if (showAccountBurnrate) {
    const headline = secondaryBurn ?? primaryBurn;
    const metaParts: string[] = [];
    if (headline) {
      metaParts.push(
        t("dashboard.stats.poolBurnDemand", {
          demand: formatCompactNumber(headline.demandCredits),
          pool: formatCompactNumber(headline.poolCredits),
        }),
      );
      metaParts.push(
        headline.firstExhaustion
          ? t("dashboard.stats.poolBurnFirstExhaustion", {
              account: headline.firstExhaustion.label,
              when: formatBurnHours(headline.firstExhaustion.inHours),
            })
          : t("dashboard.stats.poolBurnNoExhaustion"),
      );
      if (headline.lowConfidence) {
        metaParts.push(
          t("dashboard.stats.poolBurnLowConfidence", { span: formatBurnSpan(headline.lowConfidenceCutoffHours) }),
        );
      }
    }
    stats.push({
      label: showPrimaryBurn
        ? t("dashboard.stats.poolBurnProjection", { windows: `${primaryBurnLabel}/${secondaryBurnLabel}` })
        : t("dashboard.stats.poolBurnProjection", { windows: secondaryBurnLabel }),
      value: showPrimaryBurn
        ? `${formatBurnRatio(primaryBurn)} / ${formatBurnRatio(secondaryBurn)}`
        : formatBurnRatio(secondaryBurn),
      meta: metaParts.join(" · "),
      icon: Flame,
      trend: buildBurnTrend(trends.tokens, combinedBurnRatio),
      trendColor: TREND_COLORS[3],
    });
  }

  stats.push({
    label: t("dashboard.stats.errorRate", { timeframe: timeframeLabel }),
    value: formatRate(metrics?.errorRate ?? null),
    meta: metrics?.topError
      ? t("dashboard.stats.topError", { error: metrics.topError })
      : t("dashboard.stats.errorsInTimeframe", {
          count: formatCompactNumber(metrics?.errorCount ?? Math.round((metrics?.errorRate ?? 0) * (metrics?.requests ?? 0))),
          timeframe: timeframeLabel,
        }),
    icon: AlertTriangle,
    trend: trendPointsToValues(trends.errorRate),
    trendColor: TREND_COLORS[4],
  });

  const rawPrimaryItems = buildRemainingItems(overview.accounts, primaryWindow, "primary", isDark);
  const secondaryUsageItems = buildRemainingItems(overview.accounts, secondaryWindow, "secondary", isDark);
  const primaryUsageItems = secondaryWindow
    ? applySecondaryConstraint(rawPrimaryItems, secondaryUsageItems)
    : rawPrimaryItems;

  const hasPrimaryWindow = overview.accounts.some((account) => account.windowMinutesPrimary != null);

  return {
    stats,
    primaryUsageItems,
    hasPrimaryWindow,
    secondaryUsageItems,
    primaryTotal: sumRemaining(primaryUsageItems),
    secondaryTotal: sumRemaining(secondaryUsageItems),
    requestLogs,
    safeLinePrimary: buildDepletionView(projections?.depletionPrimary ?? overview.depletionPrimary),
    safeLineSecondary: buildDepletionView(projections?.depletionSecondary ?? overview.depletionSecondary),
    // A present overview pace is the freshest verdict and always wins.
    // TanStack Query retains the last successful projections payload across
    // later failures, so a stale projections copy must never override it.
    // Older backends serve `weeklyCreditPace: null` (they cannot compute the
    // runway model), which is indistinguishable from a fresh backend with no
    // eligible accounts — so null falls back to the projections copy and then
    // to the local projection instead of hiding the card entirely.
    weeklyCreditPace:
      overview.weeklyCreditPace ?? projections?.weeklyCreditPace ?? buildWeeklyCreditPace(overview.accounts),
  };
}
