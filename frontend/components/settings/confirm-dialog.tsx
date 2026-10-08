"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";
interface ConfirmDialogProps {
  open: boolean; title: string; description: string; confirmLabel: string; destructive?: boolean; busy?: boolean;
  confirmDisabled?: boolean; hideCancel?: boolean; onConfirm: () => void; onCancel: () => void; children?: ReactNode;
}
export function ConfirmDialog({ open, title, description, confirmLabel, destructive, busy, confirmDisabled, hideCancel, onConfirm, onCancel, children }: ConfirmDialogProps) {
  return <Modal.Backdrop isOpen={open} onOpenChange={(next) => !next && !busy && onCancel()} isDismissable={!busy} isKeyboardDismissDisabled={busy}>
    <Modal.Container placement="center" size="md"><Modal.Dialog>
      <Modal.Header className="pe-12"><Modal.Heading>{title}</Modal.Heading><p className="text-sm leading-7 text-muted-foreground">{description}</p></Modal.Header>
      <Button variant="ghost" isIconOnly size="sm" className="absolute end-4 top-4" onPress={onCancel} isDisabled={busy} aria-label="بستن"><X className="size-4" /></Button>
      {children && <Modal.Body>{children}</Modal.Body>}
      <Modal.Footer className="flex-wrap"><Button variant={destructive ? "danger" : "primary"} onPress={onConfirm} isDisabled={busy || confirmDisabled} isPending={busy}>{confirmLabel}</Button>{!hideCancel && <Button variant="outline" onPress={onCancel} isDisabled={busy}>انصراف</Button>}</Modal.Footer>
    </Modal.Dialog></Modal.Container>
  </Modal.Backdrop>;
}
