"use client";

import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** One line of plain text under the title (rendered inside a paragraph). */
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  busy?: boolean;
  confirmDisabled?: boolean;
  /** Hides the cancel button (a result dialog that only closes). */
  hideCancel?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  /** Optional body between the description and the buttons (a form, a notice). */
  children?: ReactNode;
}

/** A small confirm step for actions that cannot be taken back (revoking a link, posting to a group). */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  destructive,
  busy,
  confirmDisabled,
  hideCancel,
  onConfirm,
  onCancel,
  children,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && !busy && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="leading-7">{description}</DialogDescription>
        </DialogHeader>
        {children}
        <DialogFooter>
          <Button variant={destructive ? "destructive" : "default"} onClick={onConfirm} disabled={busy || confirmDisabled}>
            {confirmLabel}
          </Button>
          {!hideCancel && (
            <Button variant="outline" onClick={onCancel} disabled={busy}>
              انصراف
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
