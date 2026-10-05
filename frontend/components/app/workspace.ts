import {
  Blocks,
  ChartColumn,
  Database,
  History,
  LayoutDashboard,
  Settings,
  Smartphone,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

/** The Business Control Center sections, in sidebar order. */
export type SectionTab =
  | "overview"
  | "copilot"
  | "capabilities"
  | "data"
  | "reports"
  | "simulator"
  | "versions"
  | "settings";

/**
 * Every value `onOpenTab` accepts. "agent" is the old name of the copilot section; section components
 * written before the rename still call `onOpenTab("agent")`, and the workspace page maps it with
 * `resolveTab`. New code should use "copilot".
 */
export type WorkspaceTab = SectionTab | "agent";

export interface WorkspaceTabMeta {
  value: SectionTab;
  label: string;
  icon: LucideIcon;
}

export const WORKSPACE_TABS: WorkspaceTabMeta[] = [
  { value: "overview", label: "نمای کلی", icon: LayoutDashboard },
  { value: "copilot", label: "دستیار هوشمند", icon: Sparkles },
  { value: "capabilities", label: "قابلیت‌ها", icon: Blocks },
  { value: "data", label: "داده‌ها", icon: Database },
  { value: "reports", label: "گزارش‌ها", icon: ChartColumn },
  { value: "simulator", label: "شبیه‌ساز", icon: Smartphone },
  { value: "versions", label: "نسخه‌ها", icon: History },
  { value: "settings", label: "تنظیمات", icon: Settings },
];

export function resolveTab(tab: WorkspaceTab): SectionTab {
  return tab === "agent" ? "copilot" : tab;
}
