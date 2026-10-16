import { describe, expect, it } from "vitest";

import { coveredDateInZone, endOfDayInZoneIso } from "@/features/accounts/end-of-day";

describe("endOfDayInZoneIso", () => {
  it("ends 'through Oct 29' at midnight Pacific (PDT)", () => {
    expect(endOfDayInZoneIso("2026-10-29")).toBe("2026-10-30T07:00:00.000Z");
  });

  it("uses PST after the DST change", () => {
    expect(endOfDayInZoneIso("2026-11-02")).toBe("2026-11-03T08:00:00.000Z");
  });

  it("handles the day whose end is the DST fall-back day", () => {
    // Oct 31 ends at Nov 1 00:00 PDT, before the 02:00 fall-back.
    expect(endOfDayInZoneIso("2026-10-31")).toBe("2026-11-01T07:00:00.000Z");
  });

  it("honours another zone", () => {
    expect(endOfDayInZoneIso("2026-10-29", "UTC")).toBe("2026-10-30T00:00:00.000Z");
    expect(endOfDayInZoneIso("2026-10-29", "America/New_York")).toBe("2026-10-30T04:00:00.000Z");
  });

  it("rejects malformed dates", () => {
    expect(endOfDayInZoneIso("10/29/2026")).toBeNull();
  });

  it("round-trips to the covered date for display", () => {
    expect(coveredDateInZone("2026-10-30T07:00:00Z")).toBe("2026-10-29");
    expect(coveredDateInZone(endOfDayInZoneIso("2026-11-02"))).toBe("2026-11-02");
  });
});
