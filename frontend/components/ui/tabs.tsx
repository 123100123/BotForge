"use client";

import * as React from "react";
import { Tabs as TabsPrimitive } from "radix-ui";
import { cn } from "@/lib/utils";

function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root data-slot="tabs" dir="rtl" className={cn("flex flex-col gap-4", className)} {...props} />;
}

/** `underline` is the page-level tab strip; `segmented` is a compact control for switching a view. */
function TabsList({
  className,
  variant = "underline",
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> & { variant?: "underline" | "segmented" }) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(
        "group/tabs-list flex items-center overflow-x-auto",
        variant === "underline" && "w-full gap-1 border-b border-border",
        variant === "segmented" && "w-fit max-w-full gap-0.5 rounded-sm border border-border bg-surface-sunken p-0.5",
        className,
      )}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 text-small font-medium whitespace-nowrap text-fg-muted transition-colors duration-fast hover:text-fg data-[state=active]:text-fg",
        "group-data-[variant=underline]/tabs-list:-mb-px group-data-[variant=underline]/tabs-list:border-b-2 group-data-[variant=underline]/tabs-list:border-transparent group-data-[variant=underline]/tabs-list:px-4 group-data-[variant=underline]/tabs-list:py-2.5 group-data-[variant=underline]/tabs-list:data-[state=active]:border-brand",
        "group-data-[variant=segmented]/tabs-list:rounded-xs group-data-[variant=segmented]/tabs-list:border group-data-[variant=segmented]/tabs-list:border-transparent group-data-[variant=segmented]/tabs-list:px-3 group-data-[variant=segmented]/tabs-list:py-1 group-data-[variant=segmented]/tabs-list:data-[state=active]:border-border group-data-[variant=segmented]/tabs-list:data-[state=active]:bg-surface",
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content data-slot="tabs-content" className={cn("flex-1 outline-none", className)} {...props} />;
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
