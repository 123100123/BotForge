"use client";

import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { errorMessage } from "@/lib/errors";
import { ErrorNote } from "./state-blocks";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  /** Throw to keep the dialog open and show the (Persian) error message. */
  onConfirm: () => Promise<void>;
}

/** Confirmation with an inline error: the backend's refusal message is shown inside the dialog. */
export function ConfirmDialog({ open, onOpenChange, ...rest }: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <ConfirmBody onClose={() => onOpenChange(false)} {...rest} />
      </DialogContent>
    </Dialog>
  );
}

function ConfirmBody({
  title,
  description,
  confirmLabel,
  destructive,
  onConfirm,
  onClose,
}: Omit<ConfirmDialogProps, "open" | "onOpenChange"> & { onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>
      {error && <ErrorNote>{error}</ErrorNote>}
      <DialogFooter>
        <Button variant={destructive ? "destructive" : "default"} onClick={confirm} disabled={busy}>
          {busy ? "در حال انجام…" : confirmLabel}
        </Button>
        <Button variant="outline" onClick={onClose} disabled={busy}>
          انصراف
        </Button>
      </DialogFooter>
    </>
  );
}
