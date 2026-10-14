import { useLayoutEffect, useRef } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import i18n from "@/i18n";

export type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  confirmDisabled?: boolean;
  keepOpenOnConfirm?: boolean;
  cancelLabel?: string;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
  children?: React.ReactNode;
};

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = i18n.t("common.confirm"),
  confirmDisabled = false,
  keepOpenOnConfirm = false,
  cancelLabel = i18n.t("common.cancel"),
  onConfirm,
  onOpenChange,
  children,
}: ConfirmDialogProps) {
  const openerRef = useRef<HTMLButtonElement | null>(null);

  // Capture before the portaled FocusScope's passive mount autofocus. Unlike
  // an AlertDialogTrigger, our controlled callers can unmount on close.
  useLayoutEffect(() => {
    if (open) {
      const active = document.activeElement;
      openerRef.current = active instanceof HTMLButtonElement ? active : null;
    }
  }, [open]);

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent
        onCloseAutoFocus={(event) => {
          // Radix otherwise cancels its previous-element fallback and focuses
          // a missing Trigger. Own this event, including the no-op fallback.
          event.preventDefault();
          const opener = openerRef.current;
          if (
            !opener?.isConnected ||
            opener.matches(":disabled") ||
            opener.closest('[hidden], [inert], [aria-hidden="true"]') ||
            opener.checkVisibility?.({ visibilityProperty: true }) === false
          ) {
            return;
          }
          const doc = opener.ownerDocument;
          const closing = event.target;
          const active = doc.activeElement;
          if (
            active && active !== doc.body && active !== doc.documentElement &&
            active !== opener && !(closing instanceof Element && closing.contains(active))
          ) {
            return;
          }
          // A remaining parent may own this opener; a sibling/new modal may not.
          const dialogs = doc.querySelectorAll(
            '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"], dialog[open], [aria-modal="true"]',
          );
          if (Array.from(dialogs).some((dialog) => dialog !== closing && !dialog.contains(opener))) {
            return;
          }
          opener.focus({ preventScroll: true });
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description ? <AlertDialogDescription>{description}</AlertDialogDescription> : null}
        </AlertDialogHeader>
        {children}
        <AlertDialogFooter>
          <AlertDialogCancel>{cancelLabel}</AlertDialogCancel>
          <AlertDialogAction
            disabled={confirmDisabled}
            onClick={(event) => {
              if (keepOpenOnConfirm) {
                event.preventDefault();
              }
              onConfirm();
            }}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
