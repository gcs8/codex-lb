import { Gauge } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AccountQuotaTierOverride } from "@/features/accounts/api";
import type { AccountSummary } from "@/features/accounts/schemas";
import { formatCompactNumber } from "@/utils/formatters";

// OpenAI advertises plans as a multiple of the $20 Plus plan (7,560 credits / month):
// Pro 100 / Business Premium 5x, Pro 200 10x, grandfathered Pro 200 20x, Pro 500 25x.
const PLUS_MONTHLY_CREDITS = 7_560;
const TIER_PRESETS = [1, 5, 10, 20, 25] as const;

type Mode = "multiplier" | "monthlyCredits";

function toDateInput(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : "";
}

export type AccountQuotaTierSave = (
  accountId: string,
  override: AccountQuotaTierOverride,
  expiresAt: string | null,
) => Promise<unknown>;

export type AccountQuotaTierProps = {
  account: AccountSummary;
  disabled?: boolean;
  onSave: AccountQuotaTierSave;
};

export function AccountQuotaTier({ account, disabled = false, onSave }: AccountQuotaTierProps) {
  const { t } = useTranslation();
  const [pending, setPending] = useState(false);
  const planMultiplier = account.planQuotaTierMultiplier ?? null;
  const effective = account.effectiveQuotaTierMultiplier ?? planMultiplier;
  const hasOverride = account.quotaTierMultiplier != null || account.quotaMonthlyCredits != null;
  const [mode, setMode] = useState<Mode>(account.quotaMonthlyCredits != null ? "monthlyCredits" : "multiplier");
  const [multiplier, setMultiplier] = useState<string>(
    account.quotaTierMultiplier != null ? String(account.quotaTierMultiplier) : "",
  );
  const [credits, setCredits] = useState<string>(
    account.quotaMonthlyCredits != null ? String(account.quotaMonthlyCredits) : "",
  );
  const [expires, setExpires] = useState<string>(toDateInput(account.quotaTierMultiplierExpiresAt));

  const save = (value: AccountQuotaTierOverride) => {
    setPending(true);
    void onSave(
      account.accountId,
      value,
      value != null && expires ? new Date(`${expires}T00:00:00Z`).toISOString() : null,
    )
      .catch(() => undefined)
      .finally(() => setPending(false));
  };

  const raw = mode === "multiplier" ? multiplier : credits;
  const parsed = raw.trim() === "" ? null : Number(raw.replaceAll(",", ""));
  const [min, max] = mode === "multiplier" ? [0.1, 100] : [1, 7_560_000];
  const invalid = parsed != null && (!Number.isFinite(parsed) || parsed < min || parsed > max);
  const override: AccountQuotaTierOverride = parsed == null ? null : { kind: mode, value: parsed };
  const busy = disabled || pending;

  return (
    <div className="space-y-2 rounded-md border bg-muted/30 p-3" data-testid="account-quota-tier">
      <div className="flex items-center justify-between gap-2 text-sm font-medium">
        <span className="flex items-center gap-2">
          <Gauge className="h-4 w-4 text-muted-foreground" />
          {t("accounts.quotaTier.title")}
        </span>
        <span className="text-xs tabular-nums text-muted-foreground" data-testid="account-quota-tier-effective">
          {effective != null ? t("accounts.quotaTier.effective", { multiplier: Math.round(effective * 100) / 100 }) : null}
          {account.capacityCreditsSecondary != null && account.capacityCreditsSecondaryMonthlyEquivalent != null
            ? ` · ${t("accounts.quotaTier.capacity", {
                weekly: formatCompactNumber(account.capacityCreditsSecondary),
                monthly: formatCompactNumber(account.capacityCreditsSecondaryMonthlyEquivalent),
              })}`
            : null}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-1" role="group" aria-label={t("accounts.quotaTier.title")}>
        {(["multiplier", "monthlyCredits"] as const).map((value) => (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={mode === value ? "secondary" : "ghost"}
            aria-pressed={mode === value}
            className="h-7 px-2 text-xs"
            disabled={busy}
            onClick={() => setMode(value)}
          >
            {t(value === "multiplier" ? "accounts.quotaTier.modeMultiplier" : "accounts.quotaTier.modeCredits")}
          </Button>
        ))}
        {mode === "multiplier"
          ? TIER_PRESETS.map((preset) => (
              <Button
                key={preset}
                type="button"
                size="sm"
                variant={parsed === preset ? "default" : "outline"}
                className="h-7 px-2 text-xs"
                disabled={busy}
                onClick={() => setMultiplier(String(preset))}
              >
                {preset}×
              </Button>
            ))
          : null}
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        {mode === "multiplier" ? (
          <Input
            aria-label={t("accounts.quotaTier.multiplierLabel")}
            inputMode="decimal"
            className="h-8 text-xs sm:w-28"
            placeholder={planMultiplier != null ? t("accounts.quotaTier.planDefault", { multiplier: planMultiplier }) : ""}
            value={multiplier}
            disabled={busy}
            onChange={(event) => setMultiplier(event.target.value)}
          />
        ) : (
          <Input
            aria-label={t("accounts.quotaTier.creditsLabel")}
            inputMode="numeric"
            className="h-8 text-xs sm:w-36"
            placeholder={
              planMultiplier != null
                ? t("accounts.quotaTier.creditsPlaceholder", {
                    credits: (planMultiplier * PLUS_MONTHLY_CREDITS).toLocaleString(),
                  })
                : ""
            }
            value={credits}
            disabled={busy}
            onChange={(event) => setCredits(event.target.value)}
          />
        )}
        <Input
          type="date"
          aria-label={t("accounts.quotaTier.expiresLabel")}
          className="h-8 text-xs sm:w-40"
          value={expires}
          disabled={busy || parsed == null}
          onChange={(event) => setExpires(event.target.value)}
        />
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            className="h-8 text-xs"
            disabled={busy || invalid || override == null}
            onClick={() => save(override)}
          >
            {t("accounts.quotaTier.save")}
          </Button>
          {hasOverride ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-8 text-xs"
              disabled={busy}
              onClick={() => {
                setMultiplier("");
                setCredits("");
                setExpires("");
                save(null);
              }}
            >
              {t("accounts.quotaTier.reset")}
            </Button>
          ) : null}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{t("accounts.quotaTier.help")}</p>
    </div>
  );
}
