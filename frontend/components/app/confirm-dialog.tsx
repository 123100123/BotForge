"use client";

import { useState, type ReactNode } from "react";
import { X, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";
import { errorMessage } from "@/lib/errors";
import { ErrorNote } from "./state-blocks";

interface ConfirmDialogProps {
  open: boolean; onOpenChange: (open: boolean) => void; title: string; description: ReactNode;
  confirmLabel: string; destructive?: boolean; onConfirm: () => Promise<void>;
}
export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, destructive, onConfirm }: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  function changeOpen(next: boolean) { if (busy) return; setError(null); onOpenChange(next); }
  async function confirm() {
    setBusy(true); setError(null);
    try { await onConfirm(); onOpenChange(false); } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }
  return <Modal.Backdrop isOpen={open} onOpenChange={changeOpen} isDismissable={!busy} isKeyboardDismissDisabled={busy}>
    <Modal.Container placement="center" size="md"><Modal.Dialog>
      <Modal.Header className="pe-12"><span className="mb-2 grid size-10 place-items-center rounded-xl bg-primary/10 text-primary"><ShieldCheck className="size-5" /></span><Modal.Heading>{title}</Modal.Heading><div className="text-sm leading-7 text-muted-foreground">{description}</div></Modal.Header>
      <Button variant="ghost" isIconOnly size="sm" className="absolute end-4 top-4" onPress={() => changeOpen(false)} isDisabled={busy} aria-label="بستن"><X className="size-4" /></Button>
      {error && <Modal.Body><ErrorNote>{error}</ErrorNote></Modal.Body>}
      <Modal.Footer className="flex-wrap"><Button variant={destructive ? "danger" : "primary"} onPress={confirm} isDisabled={busy} isPending={busy}>{busy ? "در حال انجام…" : confirmLabel}</Button><Button variant="outline" onPress={() => changeOpen(false)} isDisabled={busy}>انصراف</Button></Modal.Footer>
    </Modal.Dialog></Modal.Container>
  </Modal.Backdrop>;
}
