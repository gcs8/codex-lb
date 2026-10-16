// OpenAI publishes plan dates ("through October 29, 2026") without a zone; it
// operates on US Pacific time, so an override "through" a date ends at the
// first instant of the next day in that zone (gcs8/codex-lb#7).
export const DEFAULT_OVERRIDE_TIME_ZONE = "America/Los_Angeles";

function zoneOffsetMs(utcMs: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(utcMs));
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return asUtc - utcMs;
}

/** UTC ISO instant for 00:00 on the day after `date` (YYYY-MM-DD) in `timeZone`. */
export function endOfDayInZoneIso(date: string, timeZone: string = DEFAULT_OVERRIDE_TIME_ZONE): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) {
    return null;
  }
  const nextMidnightAsUtc = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + 1);
  // Two passes settle the offset across a DST change at that midnight.
  let instant = nextMidnightAsUtc - zoneOffsetMs(nextMidnightAsUtc, timeZone);
  instant = nextMidnightAsUtc - zoneOffsetMs(instant, timeZone);
  return new Date(instant).toISOString();
}

/** Inverse for display: the last calendar day (YYYY-MM-DD, in `timeZone`) an instant still covers. */
export function coveredDateInZone(iso: string | null | undefined, timeZone: string = DEFAULT_OVERRIDE_TIME_ZONE): string {
  if (!iso) {
    return "";
  }
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) {
    return "";
  }
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(ms - 1),
  );
}
