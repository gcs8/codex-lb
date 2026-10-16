// Pro 200 weekly capacity: 10x the Plus monthly quota (7,560 credits) pro-rated
// to 7 days. Must match app/core/usage PLAN_CAPACITY_CREDITS_SECONDARY["pro"]
// (gcs8/codex-lb#7). Used only for "N more Pro accounts" fallbacks when the
// backend did not send its own figures.
export const PRO_WEEKLY_CAPACITY_CREDITS = (7_560 * 10 * 7) / 30;
