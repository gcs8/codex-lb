import { useTranslation } from "react-i18next";

import { Checkbox } from "@/components/ui/checkbox";

export function ResetCreditPermissionToggle({ id, value, onChange, disabled }: {
  id: string;
  value: boolean;
  onChange: (value: boolean) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-1 rounded-md border p-2" data-testid="reset-credit-permission">
      <div className="flex items-center gap-2 text-sm">
        <Checkbox id={id} checked={value} disabled={disabled} onCheckedChange={(checked) => onChange(checked === true)} aria-describedby={`${id}-help`} />
        <label htmlFor={id} className="cursor-pointer">{t("apiKeys.form.allowResetCreditRedeem", "Allow reset-credit redemption")}</label>
      </div>
      <p id={`${id}-help`} className="text-xs text-muted-foreground">{t("apiKeys.form.resetCreditPermissionHelp", "Allows this key to spend banked reset credits. Reading credits does not require this permission.")}</p>
    </div>
  );
}
