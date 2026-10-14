import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AccountViewModeToggle } from "./account-view-mode-toggle";
import type { DashboardAccountViewMode } from "@/hooks/use-dashboard-preferences";

function Harness() {
  const [mode, setMode] = useState<DashboardAccountViewMode>("cards");
  const [fullscreen, setFullscreen] = useState(false);
  return <AccountViewModeToggle value={mode} onChange={setMode} fullscreen={fullscreen} onFullscreenChange={setFullscreen} />;
}

describe("AccountViewModeToggle", () => {
  it("moves selection and focus with arrows and tabs once through the radio group", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const cards = screen.getByRole("radio", { name: "View accounts as cards" });
    const list = screen.getByRole("radio", { name: "View accounts as list" });
    const compact = screen.getByRole("radio", { name: "View accounts in compact mode" });
    await user.tab();
    expect(cards).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(list).toHaveFocus();
    expect(list).toHaveAttribute("aria-checked", "true");
    await user.keyboard("{ArrowDown}");
    expect(compact).toHaveFocus();
    expect(compact).toHaveAttribute("aria-checked", "true");
    await user.keyboard("{ArrowRight}");
    expect(cards).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(compact).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "View accounts full screen" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(compact).toHaveFocus();
  });

  it("exposes the fullscreen state and localized exit action to keyboard users", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const enter = screen.getByRole("button", { name: "View accounts full screen" });
    enter.focus();
    await user.keyboard(" ");
    const exit = screen.getByRole("button", { name: "Exit full screen" });
    expect(exit).toHaveFocus();
    expect(exit).toHaveAttribute("aria-pressed", "true");
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "View accounts full screen" })).toHaveAttribute("aria-pressed", "false");
  });
});
