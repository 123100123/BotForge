"use client";

import { useSyncExternalStore } from "react";

export type ToastTone = "neutral" | "success" | "warning" | "danger" | "info";

export interface ToastItem {
  id: string;
  title: string;
  description?: string;
  tone: ToastTone;
  /** ms before it closes by itself; Infinity keeps it until dismissed. */
  duration: number;
}

export type ToastInput = Omit<ToastItem, "id" | "tone" | "duration"> & { tone?: ToastTone; duration?: number };

const MAX_TOASTS = 4;
let toasts: ToastItem[] = [];
const listeners = new Set<() => void>();
let counter = 0;

function emit() {
  for (const l of listeners) l();
}

/** Show a toast from anywhere (event handlers, effects). Returns its id. */
export function toast(input: ToastInput): string {
  const id = `t${++counter}`;
  const item: ToastItem = { id, tone: "neutral", duration: 5000, ...input };
  toasts = [...toasts, item].slice(-MAX_TOASTS);
  emit();
  return id;
}

export function dismissToast(id: string) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

const EMPTY: ToastItem[] = [];

export function useToast() {
  const items = useSyncExternalStore(subscribe, () => toasts, () => EMPTY);
  return { toasts: items, toast, dismiss: dismissToast };
}
