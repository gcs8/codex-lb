import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { AppearanceSettings } from "@/features/settings/components/appearance-settings";
import i18n from "@/i18n";
import { useAccountQuotaDisplayStore } from "@/hooks/use-account-quota-display";
import { useThemeStore } from "@/hooks/use-theme";
import { useTimeFormatStore } from "@/hooks/use-time-format";
import { useDateDisplayFormatStore } from "@/hooks/use-date-format";
import { useDashboardPreferencesStore } from "@/hooks/use-dashboard-preferences";

function installLocalStorageMock() {
  const storage = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value);
      },
      removeItem: (key: string) => {
        storage.delete(key);
      },
      clear: () => {
        storage.clear();
      },
    },
  });
}

describe("AppearanceSettings", () => {
  beforeEach(() => {
    installLocalStorageMock();
    useThemeStore.setState({ preference: "light", theme: "light", initialized: true });
    useTimeFormatStore.setState({ timeFormat: "12h" });
    useDateDisplayFormatStore.setState({ dateDisplayFormat: "default" });
    useAccountQuotaDisplayStore.setState({ quotaDisplay: "both" });
    useDashboardPreferencesStore.setState({ refreshSeconds: 15 });
  });

  it("updates the dashboard refresh cadence", async () => {
    const user = userEvent.setup();
    render(<AppearanceSettings />);

    const fiveSeconds = screen.getByRole("button", { name: "5s" });
    const fifteenSeconds = screen.getByRole("button", { name: "15s" });
    expect(fifteenSeconds).toHaveAttribute("aria-pressed", "true");

    await user.click(fiveSeconds);

    expect(fiveSeconds).toHaveAttribute("aria-pressed", "true");
    expect(useDashboardPreferencesStore.getState().refreshSeconds).toBe(5);
  });

  it("exposes selected state for the time-format toggle", async () => {
    const user = userEvent.setup();

    render(<AppearanceSettings />);

    const button12h = screen.getByRole("button", { name: /12h/i });
    const button24h = screen.getByRole("button", { name: /24h/i });

    expect(button12h).toHaveAttribute("aria-pressed", "true");
    expect(button24h).toHaveAttribute("aria-pressed", "false");

    await user.click(button24h);

    expect(button12h).toHaveAttribute("aria-pressed", "false");
    expect(button24h).toHaveAttribute("aria-pressed", "true");
    expect(useTimeFormatStore.getState().timeFormat).toBe("24h");
  });

  it("exposes selected state for the date-format toggle", async () => {
    const user = userEvent.setup();

    render(<AppearanceSettings />);

    const buttonDefault = screen.getByRole("button", { name: /default/i });
    const buttonIso = screen.getByRole("button", { name: /iso 8601/i });

    expect(buttonDefault).toHaveAttribute("aria-pressed", "true");
    expect(buttonIso).toHaveAttribute("aria-pressed", "false");

    await user.click(buttonIso);

    expect(buttonDefault).toHaveAttribute("aria-pressed", "false");
    expect(buttonIso).toHaveAttribute("aria-pressed", "true");
    expect(useDateDisplayFormatStore.getState().dateDisplayFormat).toBe("iso8601");
  });

  it("exposes selected state for the account quota toggle", async () => {
    const user = userEvent.setup();

    render(<AppearanceSettings />);

    const button5h = screen.getByRole("button", { name: "5H" });
    const buttonWeekly = screen.getByRole("button", { name: "W" });
    const buttonBoth = screen.getByRole("button", { name: "Both" });

    expect(buttonBoth).toHaveAttribute("aria-pressed", "true");
    expect(button5h).toHaveAttribute("aria-pressed", "false");
    expect(buttonWeekly).toHaveAttribute("aria-pressed", "false");

    await user.click(button5h);

    expect(button5h).toHaveAttribute("aria-pressed", "true");
    expect(useAccountQuotaDisplayStore.getState().quotaDisplay).toBe("5h");

    await user.click(buttonWeekly);

    expect(buttonWeekly).toHaveAttribute("aria-pressed", "true");
    expect(useAccountQuotaDisplayStore.getState().quotaDisplay).toBe("weekly");
  });

  it.each([
    [
      "en",
      "Pool burn projection",
      "Show projected demand vs pool capacity on the dashboard.",
      "Show pool burn projection",
    ],
    ["ko", "풀 소진 예측", "대시보드에 풀 용량 대비 예상 수요를 표시합니다.", "풀 소진 예측 표시"],
    ["zh-CN", "池消耗预测", "在仪表盘上显示预计需求与池容量的对比。", "显示池消耗预测"],
  ])(
    "labels the pool burn preference and preserves its storage key in %s",
    async (language, label, description, accessibleName) => {
      await i18n.changeLanguage(language);
      try {
        const user = userEvent.setup();
        useDashboardPreferencesStore.setState({ accountBurnrateEnabled: true });
        const { unmount } = render(<AppearanceSettings />);

        expect(screen.getByText(label)).toBeInTheDocument();
        expect(screen.getByText(description)).toBeInTheDocument();
        const toggle = screen.getByRole("switch", { name: accessibleName });
        expect(toggle).toBeChecked();

        await user.click(toggle);
        expect(toggle).not.toBeChecked();
        expect(useDashboardPreferencesStore.getState().accountBurnrateEnabled).toBe(false);
        expect(window.localStorage.getItem("codex-lb-account-burnrate-enabled")).toBe("false");

        await user.click(toggle);
        expect(toggle).toBeChecked();
        expect(window.localStorage.getItem("codex-lb-account-burnrate-enabled")).toBe("true");
        unmount();
      } finally {
        await i18n.changeLanguage("en");
      }
    },
  );

  it("localizes the pool burn projection row in zh-CN", async () => {
    await i18n.changeLanguage("zh-CN");
    try {
      render(<AppearanceSettings />);

      expect(screen.getByText("池消耗预测")).toBeInTheDocument();
      expect(screen.getByText("在仪表盘上显示预计需求与池容量的对比。")).toBeInTheDocument();
      expect(screen.queryByText("Account burn projection")).not.toBeInTheDocument();
      expect(
        screen.queryByText("Show the account-equivalent projection card on the dashboard."),
      ).not.toBeInTheDocument();
    } finally {
      await i18n.changeLanguage("en");
    }
  });
});
