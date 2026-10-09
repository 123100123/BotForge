"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Plus, Bot, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
export function NewBotDialog({ label = "ربات جدید" }: { label?: string }) {
  const router = useRouter(); const [open, setOpen] = useState(false); const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null); const [pending, setPending] = useState(false);
  function changeOpen(next: boolean) { if (pending) return; setOpen(next); if (!next) setError(null); }
  async function onSubmit(e: FormEvent) {
    e.preventDefault(); if (pending) return; const trimmed = name.trim();
    if (!trimmed) { setError("نام ربات را وارد کنید."); return; }
    setPending(true); setError(null);
    try { const bot = await api.createBot(trimmed); setOpen(false); setName(""); router.push(`/bots/${bot.id}`); }
    catch (err) { setError(errorMessage(err)); } finally { setPending(false); }
  }
  return <><Button onPress={() => changeOpen(true)}><Plus className="size-4" />{label}</Button>
    <Modal.Backdrop isOpen={open} onOpenChange={changeOpen} isDismissable={!pending} isKeyboardDismissDisabled={pending}>
      <Modal.Container placement="center" size="md"><Modal.Dialog>
        <form onSubmit={onSubmit} noValidate>
          <Modal.Header className="pe-12"><span className="mb-2 grid size-12 place-items-center rounded-2xl bg-primary/10 text-primary"><Bot className="size-6" /></span><Modal.Heading>یک شروع تازه برای کسب‌وکارتان</Modal.Heading><p className="text-sm leading-7 text-muted-foreground">یک نام برای ربات انتخاب کنید. سپس در گفتگو با دستیار، رفتار آن را می‌سازید.</p></Modal.Header>
          <Button type="button" variant="ghost" isIconOnly size="sm" className="absolute end-4 top-4" onPress={() => changeOpen(false)} isDisabled={pending} aria-label="بستن"><X className="size-4" /></Button>
          <Modal.Body><div className="space-y-2"><Label htmlFor="bot-name">نام ربات</Label><Input id="bot-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="مثلاً: کارگاه‌های سپهر" autoFocus aria-invalid={Boolean(error)} aria-describedby={error ? "bot-name-error" : undefined} />{error && <p id="bot-name-error" role="alert" className="text-xs text-destructive">{error}</p>}</div></Modal.Body>
          <Modal.Footer><Button type="submit" isDisabled={pending} isPending={pending}>{pending ? "در حال ساخت…" : "ساخت ربات"}</Button><Button type="button" variant="outline" onPress={() => changeOpen(false)} isDisabled={pending}>انصراف</Button></Modal.Footer>
        </form>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </>;
}
