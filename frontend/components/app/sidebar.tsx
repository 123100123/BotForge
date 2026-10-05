"use client";

import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WORKSPACE_TABS } from "@/components/app/workspace";

/**
 * Section navigation of the workspace: a vertical sidebar on the right (the layout is RTL, so it is the
 * first flex child) on desktop, a horizontally scrollable bar on mobile. Must render inside <Tabs>.
 */
export function WorkspaceSidebar() {
  return (
    <TabsList
      aria-label="بخش‌های ربات"
      className="gap-1 md:sticky md:top-4 md:w-52 md:shrink-0 md:flex-col md:items-stretch md:gap-0.5 md:self-start md:overflow-visible md:rounded-xl md:border md:bg-card md:p-2"
    >
      {WORKSPACE_TABS.map(({ value, label, icon: Icon }) => (
        <TabsTrigger
          key={value}
          value={value}
          className="md:mb-0 md:justify-start md:rounded-md md:border-b-0 md:px-3 md:data-[state=active]:bg-accent md:data-[state=active]:text-accent-foreground"
        >
          <Icon className="size-4" aria-hidden />
          {label}
        </TabsTrigger>
      ))}
    </TabsList>
  );
}
