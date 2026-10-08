"use client";

import { ArrowUpLeft, Bot, PanelRightClose } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WORKSPACE_TABS, type SectionTab } from "@/components/app/workspace";
import { cn } from "@/lib/utils";

const groups: { label: string; tabs: SectionTab[] }[] = [
  { label: "مرکز کنترل", tabs: ["overview"] },
  { label: "ساخت و پیکربندی", tabs: ["copilot", "capabilities"] },
  { label: "عملیات روزانه", tabs: ["data", "simulator"] },
  { label: "بینش", tabs: ["reports"] },
  { label: "تاریخچه", tabs: ["versions"] },
  { label: "مدیریت", tabs: ["settings"] },
];
export function WorkspaceSidebar({ selected, onSelect, onClose }: {
  selected: SectionTab; onSelect: (tab: SectionTab) => void; onClose?: () => void;
}) {
  return <nav aria-label="بخش‌های ربات" className="flex h-full flex-col gap-5 p-3">
    <div className="flex items-center gap-3 px-2 py-2">
      <span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-primary/10 text-primary"><Bot className="size-5" /></span>
      <div className="min-w-0 flex-1"><p className="text-sm font-bold">مرکز کنترل</p><p className="text-xs text-muted-foreground">همه‌چیز در یک ربات</p></div>
      {onClose && <Button variant="ghost" isIconOnly aria-label="بستن فهرست" onPress={onClose}><PanelRightClose className="size-5" /></Button>}
    </div>
    {groups.map((group) => <div key={group.label} className="space-y-1">
      <p className="px-3 pb-2 text-[11px] font-semibold tracking-wide text-muted-foreground">{group.label}</p>
      {group.tabs.map((id) => {
        const item = WORKSPACE_TABS.find((t) => t.value === id)!; const Icon = item.icon;
        return <Button key={id} variant="ghost" onPress={() => onSelect(id)} aria-current={selected === id ? "page" : undefined}
          className={cn("h-11 w-full justify-start gap-3 rounded-xl px-3 text-sm", selected === id ? "bg-primary/10 font-semibold text-primary" : "text-muted-foreground")}
        ><Icon className="size-[18px] shrink-0" aria-hidden />{item.label}{selected === id && <span className="ms-auto size-1.5 rounded-full bg-primary" />}</Button>;
      })}
    </div>)}
    <div className="mt-auto rounded-2xl border border-primary/10 bg-primary/5 p-4">
      <ArrowUpLeft className="mb-2 size-5 text-primary" aria-hidden /><p className="text-xs font-semibold">از ایده تا اجرا</p>
      <p className="mt-1 text-xs leading-6 text-muted-foreground">تغییر بعدی ربات را با دستیار بسازید و پیش از انتشار بررسی کنید.</p>
      <Button variant="ghost" size="sm" className="mt-2 px-0 text-primary" onPress={() => onSelect("copilot")}>گفتگو با دستیار</Button>
    </div>
  </nav>;
}
