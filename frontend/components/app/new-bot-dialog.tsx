"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

/** Asks only for a name, creates the bot, and opens its workspace. `children` is the trigger button. */
export function NewBotDialog({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("نام ربات را وارد کنید.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const bot = await api.createBot(trimmed);
      setOpen(false);
      setName("");
      router.push(`/bots/${bot.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setError(null);
      }}
    >
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent>
        <form onSubmit={onSubmit} noValidate className="grid gap-4">
          <DialogHeader>
            <DialogTitle>ربات جدید</DialogTitle>
            <DialogDescription>برای ربات یک نام انتخاب کنید. بقیهٔ کار را در گفتگو با ایجنت انجام می‌دهید.</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="bot-name">نام ربات</Label>
            <Input
              id="bot-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "bot-name-error" : undefined}
            />
            {error && (
              <p id="bot-name-error" role="alert" className="text-caption text-danger-text">
                {error}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="submit" disabled={pending}>
              {pending ? "در حال ساخت…" : "ساخت ربات"}
            </Button>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                انصراف
              </Button>
            </DialogClose>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
