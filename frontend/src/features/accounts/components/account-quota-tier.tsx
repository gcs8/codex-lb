import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { updateAccountQuotaTier } from "@/features/accounts/api";
import { invalidateAccountRelatedQueries } from "@/features/accounts/query-invalidation";
import type { AccountSummary } from "@/features/accounts/schemas";
import { formatCompactNumber } from "@/utils/formatters";

// x Plus monthly quota (7,560). Pro 100 / Business Premium 5x, Pro 200 10x,
// grandfathered Pro 200 20x, Pro 500 25x.
const TIER_PRESETS = [1, 5, 10, 20, 25] as const;

function toDateInput(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : "";
}

export type AccountQuotaTierProps = {
  account: AccountSummary;
  disabled?: boolean;
};

export function AccountQuotaTier({ account, disabled = false }: AccountQuotaTierProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const planMultiplier = account.planQuotaTierMultiplier ?? null;
  const effective = account.effectiveQuotaTierMultiplier ?? planMultiplier;
  const [multiplier, setMultiplier] = useState<string>(
    account.quotaTierMultiplier != null ? String(account.quotaTierMultiplier) : "",
  );
  const [expires, setExpires] = useState<string>(toDateInput(account.quotaTierMultiplierExpiresAt));

  const mutation = useMutation({
    mutationFn: (value: number | null) =>
      updateAccountQuotaTier(
        account.accountId,
        value,
        value != null && expires ? new Date(`${expires}T00:00:00Z`).toISOString() : null,
      ),
    onSuccess: () => {
      toast.success(t("accounts.toasts.quotaTierSet"));
      invalidateAccountRelatedQueries(queryClient, account.accountId);
    },
    onError: (error: Error) => {
      toast.error(error.message || t("accounts.toasts.quotaTierUpdateFailed"));
    },
  });

  const parsed = multiplier.trim() === "" ? null : Number(multiplier);
  const invalid = parsed != null && (!Number.isFinite(parsed) || parsed < 0.1 || parsed > 100);
  const busy = disabled || mutation.isPending;

  return (
    <div className="space-y-2 rounded-md border bg-muted/30 p-3" data-testid="account-quota-tier">
      <div className="flex items-center justify-between gap-2 text-sm font-medium">
        <span className="flex items-center gap-2">
          <Gauge className="h-4 w-4 text-muted-foreground" />
          {t("accounts.quotaTier.title")}
        </span>
        <span className="text-xs tabular-nums text-muted-foreground" data-testid="account-quota-tier-effective">
          {effective != null ? t("accounts.quotaTier.effective", { multiplier: effective }) : null}
          {account.capacityCreditsSecondary != null && account.capacityCreditsSecondaryMonthlyEquivalent != null
            ? ` · ${t("accounts.quotaTier.capacity", {
                weekly: formatCompactNumber(account.capacityCreditsSecondary),
                monthly: formatCompactNumber(account.capacityCreditsSecondaryMonthlyEquivalent),
              })}`
            : null}
        </span>
      </div>
      <div className="flex flex-wrap gap-1">
        {TIER_PRESETS.map((preset) => (
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
        ))}
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Input
          aria-label={t("accounts.quotaTier.multiplierLabel")}
          inputMode="decimal"
          className="h-8 text-xs sm:w-28"
          placeholder={planMultiplier != null ? t("accounts.quotaTier.planDefault", { multiplier: planMultiplier }) : ""}
          value={multiplier}
          disabled={busy}
          onChange={(event) => setMultiplier(event.target.value)}
        />
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
            disabled={busy || invalid}
            onClick={() => mutation.mutate(parsed)}
          >
            {t("accounts.quotaTier.save")}
          </Button>
          {account.quotaTierMultiplier != null ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-8 text-xs"
              disabled={busy}
              onClick={() => {
                setMultiplier("");
                setExpires("");
                mutation.mutate(null);
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
