import { StrictMode, useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "@/components/confirm-dialog";

function ConfirmationScene({
  conditional = false,
  eligibility = "eligible",
  onConfirm = () => {},
  busy = false,
}: {
  conditional?: boolean;
  eligibility?: "eligible" | "detached" | "disabled" | "hidden" | "inert" | "fieldset";
  onConfirm?: () => void;
  busy?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const dialog = (
    <ConfirmDialog open={open} title="Delete item" description="Confirm deletion"
      onConfirm={onConfirm} onOpenChange={(next) => { if (!busy) setOpen(next); }}
      keepOpenOnConfirm={busy} confirmDisabled={busy} />
  );
  return <>
    {eligibility !== "detached" && <fieldset disabled={eligibility === "fieldset"}>
      <div hidden={eligibility === "hidden"} inert={eligibility === "inert"}>
        <button disabled={eligibility === "disabled"} onClick={() => setOpen(true)}>Open confirmation</button>
      </div>
    </fieldset>}
    {conditional ? open && dialog : dialog}
  </>;
}

async function activate(user: ReturnType<typeof userEvent.setup>) {
  const opener = screen.getByRole("button", { name: "Open confirmation" });
  await user.click(opener);
  expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  return opener;
}

async function expectReturned(opener: HTMLElement) {
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  await waitFor(() => expect(opener).toHaveFocus());
  expect(opener.isConnected).toBe(true);
  expect(screen.getByRole("button", { name: "Open confirmation" })).toBe(opener);
}

describe("ConfirmDialog automatic focus ownership", () => {
  for (const conditional of [false, true]) {
    for (const close of ["Escape", "Cancel", "Confirm"]) {
      it(`returns to the original button on ${close}, conditional=${conditional}`, async () => {
        const user = userEvent.setup();
        const onConfirm = vi.fn();
        render(<StrictMode><ConfirmationScene conditional={conditional} onConfirm={onConfirm} /></StrictMode>);
        const opener = await activate(user);
        if (close === "Escape") await user.keyboard("{Escape}");
        else await user.click(screen.getByRole("button", { name: close }));
        await expectReturned(opener);
        expect(onConfirm).toHaveBeenCalledTimes(close === "Confirm" ? 1 : 0);
        // Reopening must capture this activation, not the prior dialog's Cancel.
        await user.keyboard("{Enter}");
        expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
        await user.keyboard("{Escape}");
        await expectReturned(opener);
      });
    }
  }

  for (const eligibility of ["detached", "disabled", "hidden", "inert", "fieldset"] as const) {
    it(`does not focus an opener made ${eligibility} or search for a replacement`, async () => {
      const user = userEvent.setup();
      const view = render(<ConfirmationScene />);
      const opener = await activate(user);
      const focus = vi.spyOn(opener, "focus");
      const bodyFocus = vi.spyOn(document.body, "focus");
      const unmounted = vi.fn();
      screen.getByRole("alertdialog").addEventListener("focusScope.autoFocusOnUnmount", unmounted);
      view.rerender(<ConfirmationScene eligibility={eligibility} />);
      await user.keyboard("{Escape}");
      await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
      // Wait for Radix's actual unmount event, not an arbitrary timeout.
      await waitFor(() => expect(unmounted).toHaveBeenCalledOnce());
      expect(focus).not.toHaveBeenCalled();
      expect(bodyFocus).not.toHaveBeenCalled();
      focus.mockRestore(); bodyFocus.mockRestore();
    });
  }

  it("does not move focus while closed or when a busy caller refuses dismissal", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const view = render(<ConfirmationScene busy onConfirm={onConfirm} />);
    const opener = await activate(user);
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(opener).not.toHaveFocus();
    expect(onConfirm).not.toHaveBeenCalled();
    view.rerender(<ConfirmationScene onConfirm={onConfirm} />);
    await user.keyboard("{Escape}");
    await expectReturned(opener);
  });

  it("returns an inner confirmation to its parent without closing the parent", async () => {
    function Nested() {
      const [outer, setOuter] = useState(false);
      const [inner, setInner] = useState(false);
      return <>
        <button onClick={() => setOuter(true)}>Open parent</button>
        <ConfirmDialog open={outer} onOpenChange={setOuter} onConfirm={() => {}}
          title="Parent" description="Parent dialog">
          <button onClick={() => setInner(true)}>Open inner</button>
          {inner && <ConfirmDialog open onOpenChange={setInner} onConfirm={() => {}}
            title="Inner" description="Inner dialog" />}
        </ConfirmDialog>
      </>;
    }
    const user = userEvent.setup();
    render(<Nested />);
    const parent = screen.getByRole("button", { name: "Open parent" });
    await user.click(parent);
    const inner = screen.getByRole("button", { name: "Open inner" });
    await user.click(inner);
    expect(within(screen.getByRole("alertdialog", { name: "Inner" })).getByText("Cancel")).toHaveFocus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(inner).toHaveFocus());
    expect(screen.getByRole("alertdialog", { name: "Parent" })).toBeInTheDocument();
    expect(inner.isConnected).toBe(true);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(parent).toHaveFocus());
  });

  it("does not steal focus from a new sibling modal opened by the action", async () => {
    function Siblings() {
      const [first, setFirst] = useState(false);
      const [second, setSecond] = useState(false);
      return <>
        <button onClick={() => setFirst(true)}>Open confirmation</button>
        <ConfirmDialog open={first} onOpenChange={setFirst} onConfirm={() => setSecond(true)}
          title="First" description="First dialog" />
        <ConfirmDialog open={second} onOpenChange={setSecond} onConfirm={() => {}}
          title="Second" description="Second dialog" />
      </>;
    }
    const user = userEvent.setup();
    render(<Siblings />);
    const opener = await activate(user);
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog", { name: "First" })).not.toBeInTheDocument());
    const second = screen.getByRole("alertdialog", { name: "Second" });
    await waitFor(() => expect(within(second).getByText("Cancel")).toHaveFocus());
    expect(opener).not.toHaveFocus();
  });

  it("preserves AlertDialog outside-interaction prevention", async () => {
    const user = userEvent.setup();
    render(<ConfirmationScene />);
    const opener = await activate(user);
    await user.pointer({ target: document.querySelector('[data-slot="alert-dialog-overlay"]')!, keys: "[MouseLeft]" });
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await expectReturned(opener);
  });
});
