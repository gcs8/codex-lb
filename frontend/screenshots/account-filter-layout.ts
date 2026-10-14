import { expect, type Page } from "@playwright/test";

/** Real Chromium geometry; DOM text presence or JSDOM widths are insufficient. */
export async function measureAccountFilterLabel(page: Page, name: string) {
  return page.getByTestId("accounts-list-card").getByRole("combobox", { name, exact: true }).evaluate((trigger) => {
    const value = trigger.querySelector<HTMLElement>('[data-slot="select-value"]');
    const card = trigger.closest('[data-testid="accounts-list-card"]');
    if (!value || !card) throw new Error("Accounts filter value or card missing");
    const range = document.createRange();
    range.selectNodeContents(value);
    const valueRect = value.getBoundingClientRect();
    const triggerRect = trigger.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    const textRects = Array.from(range.getClientRects());
    const css = getComputedStyle(value);
    const fits = textRects.length > 0 && textRects.every((rect) =>
      rect.left >= valueRect.left - 0.5 && rect.right <= valueRect.right + 0.5 &&
      rect.top >= valueRect.top - 0.5 && rect.bottom <= valueRect.bottom + 0.5,
    ) && value.scrollWidth <= value.clientWidth + 1;
    return {
      text: value.textContent,
      fits,
      valueRect: valueRect.toJSON(),
      textRects: textRects.map((rect) => rect.toJSON()),
      triggerRect: triggerRect.toJSON(),
      cardRect: cardRect.toJSON(),
      triggerFitsCard: triggerRect.left >= cardRect.left && triggerRect.right <= cardRect.right,
      clientWidth: value.clientWidth,
      scrollWidth: value.scrollWidth,
      overflow: css.overflow,
      lineClamp: css.webkitLineClamp,
      textOverflow: css.textOverflow,
      viewport: { width: innerWidth, height: innerHeight },
    };
  });
}

/** Select every offered option rather than a hard-coded subset of long labels. */
export async function inspectAccountFilterLabels(page: Page) {
  const evidence = [];
  for (const name of ["Sort accounts", "Filter accounts by status"]) {
    const trigger = page.getByTestId("accounts-list-card").getByRole("combobox", { name, exact: true });
    await trigger.click();
    const options = await page.getByRole("option").allTextContents();
    expect(options.length).toBeGreaterThan(0);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox", { includeHidden: true })).toHaveCount(0);
    for (const label of options) {
      await trigger.click();
      await page.getByRole("option", { name: label, exact: true }).click();
      await expect(trigger).toHaveText(label);
      await expect(page.getByRole("listbox", { includeHidden: true })).toHaveCount(0);
      await page.evaluate(() => document.fonts.ready);
      await page.waitForFunction(() => !document.getAnimations().some((animation) =>
        animation.playState === "running" && animation.effect?.getComputedTiming().iterations !== Infinity,
      ));
      evidence.push({ name, label, ...await measureAccountFilterLabel(page, name) });
    }
  }
  return evidence;
}
