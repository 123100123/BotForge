# BotForge design system

Durable design authority for the frontend. Read this before touching UI. Decisions behind it are in the
roadmap Decision Log (rows tagged "UI redesign"). Token values live in `app/globals.css`; this file says what
they mean and how to use them.

## Design read

Operate-mode business software for non-technical Iranian owners: calm, exact, with one place of character.
Direction: **turquoise ledger**. From the ledger: ruled rows, tabular figures, totals that line up. From
turquoise (فیروزه‌ای): the brand hue (190 to 195), chosen to avoid Telegram blue and default SaaS blue.
Persian only, right-to-left, everywhere including the landing page. One family, Vazirmatn.

## Principles

1. Borders, not shadows. Shadows only on things that float (menus, popovers, dialogs, sheets, toasts).
2. No card inside a card. Inside a panel, separate sections with headings and dividers.
3. No pills. Radius by role (below). `rounded-full` only for avatars, dots, step circles, switches.
4. Status is never color alone: always a word, and an icon or marker shape, plus the tone color.
5. Components use semantic tokens only. No palette classes (`bg-blue-600`, `text-gray-500`, `bg-white`), no
   hex, no `oklch()` literals in components. Light and dark are tuned separately, never inverted.
6. Logical properties only (RTL rules below). `npm run check:rtl` enforces it.
7. Motion is feedback only. No scroll reveals, page transitions or looping effects.
8. Imagery is product only (real components, fixture data, the simulator phone). No stock photos, no sparkles.
9. Minimum text size 12.5px, including chart labels.

## Tokens (semantic layer)

Defined in `app/globals.css`: light on `:root`, dark on `[data-theme="dark"]`. Components use the Tailwind
class names in the right-hand column. Contrast intent: body text at least 7:1, secondary 4.5:1, borders and
icons that carry meaning 3:1.

| Token | Meaning | Tailwind |
|---|---|---|
| `--bg` | page background | `bg-page` |
| `--surface` | panels, cards, headers | `bg-surface` |
| `--surface-sunken` | wells, table headers, hover rows, segmented track | `bg-surface-sunken` |
| `--surface-raised` | inputs, menus, dialogs, sheets, toasts | `bg-surface-raised` |
| `--border` | dividers, panel borders | `border-border` (default border color) |
| `--border-strong` | input borders, off-switch track | `border-border-strong` |
| `--text` | primary text | `text-fg` |
| `--text-secondary` | supporting text | `text-fg-secondary` |
| `--text-muted` | captions, hints, placeholders | `text-fg-muted` |
| `--brand` | primary actions, focus ring, active indicator | `bg-brand`, `border-brand` |
| `--brand-hover` | hover of brand fills | `bg-brand-hover` |
| `--brand-soft` | selected row, active nav item, tint | `bg-brand-soft` |
| `--brand-text` | brand-colored text and links on surfaces | `text-brand-text` |
| `--on-brand` | text and icons on a brand (or danger) fill | `text-on-brand` |
| `--success` `--warning` `--danger` `--info` | tone fill or icon color | `bg-success`, `text-danger` ... |
| `--*-soft` | tone background for badges, notes | `bg-success-soft` ... |
| `--*-text` | tone text on a soft or plain surface | `text-success-text` ... |
| `--chart-1..5` | categorical series: turquoise, indigo, amber, rose, olive | `fill-chart-1`, `bg-chart-3` |
| `--chart-grid` `--chart-label` `--chart-compare` | gridlines, axis labels, dashed comparison | `stroke-chart-grid`, `fill-chart-label` |
| `--scrim` | modal overlay | `bg-scrim` |
| `--shadow-float`, `--float-border` | floating surfaces | `shadow-float border border-float` |

Rules of thumb: text in a tone uses `*-text` (never the plain tone, it is for fills and icons); a tone fill
behind text uses `*-soft` + `*-text`; solid tone buttons use `text-on-brand`. The alias
`text-fg-muted` replaces `text-muted-foreground` in new code.

**Legacy shadcn names** (`bg-background`, `text-foreground`, `bg-card`, `bg-primary`, `text-primary-foreground`,
`bg-muted`, `text-muted-foreground`, `bg-accent`, `text-accent-foreground`, `bg-destructive`, `border-input`,
`ring-ring`, `bg-success`, `bg-warning`) still work as aliases of the tokens above, in both themes. Do not use
them in new code; migrate them when you touch a file.

Primitives (ramps) are not exposed; do not add new raw colors. A new semantic token needs a light and a dark
value in `globals.css`, an entry in `@theme inline`, and a row here.

### Themes

Preference is `light | dark | system` (default system), stored in `localStorage["botforge.theme"]` (absent
means system). An inline script in `<head>` (`THEME_INIT_SCRIPT` in `lib/theme.tsx`) resolves it and always
writes the resolved `light` or `dark` to `data-theme` on `<html>` before first paint; `ThemeProvider` keeps it
in sync and follows `prefers-color-scheme` while the preference is system. Tailwind's `dark:` variant keys off
the attribute. Use `useTheme()` for `{ preference, resolved, setPreference }`. `ThemeMenu` is the picker.
`<meta name="theme-color">` follows the OS scheme (set in `viewport` in `app/layout.tsx`).

## Type scale

Classes (defined in `globals.css`, usable with variants such as `md:text-h1`). Persian needs tall line heights.
They set size, line height and weight; pair with a color class. Headings get `text-wrap: balance`.

| Class | Size / line / weight | Use |
|---|---|---|
| `text-display` | 44 (32 on mobile) / 1.3 / 800 | landing hero h1 only |
| `text-h1` | 26 / 1.45 / 700 | page title (one per page, inside PageHeader) |
| `text-h2` | 20 / 1.5 / 700 | section title, dialog and sheet title |
| `text-h3` | 16.5 / 1.6 / 600 | panel title, empty-state title |
| `text-body` | 15 / 1.8 / 400 | default text, inputs, buttons |
| `text-small` | 13.5 / 1.75 | secondary text, table cells, labels |
| `text-caption` | 12.5 / 1.7 / 500 | badges, hints, chart labels. Nothing smaller |
| `text-metric` | 28 / 1.2 / 700, tabular | headline number of a stat tile |
| `text-metric-sm` | 22 / 1.3 / 650, tabular | secondary numbers |

Body default is 15px / 1.8. Table cells use tabular numbers globally. Do not use `text-xs`, `text-[11px]` or
other ad-hoc sizes; `text-sm`/`text-base`/`text-lg` remain only in not-yet-migrated screens. A `font-*` or
`leading-*` utility overrides the weight or line height of a type class.

## Shape, spacing, borders

Radius by role (Tailwind class, px): `rounded-xs` 6 badges and small inputs; `rounded-sm` 8 buttons and inputs;
`rounded-md` 12 panels, cards, menus, popovers, toasts; `rounded-lg` 16 dialogs, sheets. `rounded-xl` and `rounded-2xl` are 16 and exist only so stray classes stay in scale; do not use them.

Spacing scale: 4 8 12 16 20 24 32 40 56 80 (Tailwind 1, 2, 3, 4, 5, 6, 8, 10, 14, 20). Control Center page
padding 24, panel padding 20, table rows about 40 tall, dense tables with row dividers only (no zebra, no box
per row). Landing is airy, content max width 1360, prose 72ch.

Panels: `Card` (1px border, no shadow). Floating: `shadow-float` plus `border border-float` (the border is
`border-strong` in dark, where shadows do not read).

## Motion

Tokens: `--duration-fast` 120ms (hover, press, toggle: `duration-fast`), `--duration-base` 180ms (menus,
popovers, drawers: `duration-base`), `--duration-slow` 240ms (dialogs, sheets: `duration-slow`);
`--ease-out cubic-bezier(.2,.8,.2,1)` for enter (`ease-out`), `--ease-in cubic-bezier(.4,0,1,1)` for exit.
Exits are about 70% of entry duration. Use `motion-safe:` on zoom and slide animations; fades are always
allowed. A `prefers-reduced-motion` block in `globals.css` removes animations and limits transitions to
opacity and color, so transforms never animate. The agent timeline's active step is the only "alive" element.

## z-index scale

`z-sticky` 10, `z-drawer` 30 (docked non-modal panels), `z-overlay` 40 (scrims), `z-modal` 50 (dialogs, sheets,
and the menus, popovers and tooltips that open from them: Radix portals stack in open order), `z-toast` 60.

## Focus

One global rule: `:focus-visible` gets a 2px `--brand` outline with 2px offset. Do not add `outline-none` or
per-component ring styles; do not remove the outline. Inputs also switch their border to brand; an invalid
input (`aria-invalid`) has a danger border and danger focus outline.

## Icons

lucide-react only. `strokeWidth` 1.75 (set on icons you place directly; defaults inside primitives).
Sizes: 16 (`size-4`: inline, buttons, tables) and 20 (`size-5`: navigation, empty-state tiles). Icons go on
navigation, status, and ambiguous verbs; never decorate headings. Decorative icons get `aria-hidden`;
icon-only buttons get an `aria-label` (Persian). Directional icons (arrows, chevrons, send, log-out) mirror in
RTL with `rtl:-scale-x-100`.

## RTL rules

- Logical utilities only: `ms-/me-/ps-/pe-`, `start-/end-`, `text-start/text-end`, `rounded-s/e/ss/se/es/ee`,
  `border-s/e`, `inset-x-0`. Never `ml-/mr-/pl-/pr-`, `left-/right-`, `text-left/right`, `rounded-l/r`,
  `border-l/r`. `npm run check:rtl` fails on them; a truly symmetric line (for example `left-1/2
  -translate-x-1/2` centering) may carry the comment marker `rtl-ok`.
- Center overlays with `inset-0 m-auto` (see Dialog), not left plus translate.
- Isolate left-to-right content with `dir="ltr"`: emails, @handles, URLs, phone numbers, codes, file names.
  Number lists and units in a flex row are separate elements so the bidi algorithm does not merge digits.
- Radix primitives get `dir="rtl"` from `Direction.Provider` in `components/app/providers.tsx`.
- Charts run right to left: the oldest point is at the right.
- "start" means the right edge in RTL (Sheet `side="start"` slides from the right).

## Status semantics

Always a word, plus an icon or the 7px square marker, plus the tone. Tones: `neutral` (draft, off, unknown),
`brand` (selected, new), `success` (active, done, connected), `warning` (waiting, needs attention, soon),
`danger` (failed, rejected, destructive), `info` (neutral news, hints). Use `StatusBadge`; `Badge` is for plain
labels. Deltas pair an arrow with a word (increase or decrease), never color alone. Direction of "good" is not
always up (cancellations): color follows polarity, the arrow follows direction.

## Page template

`PageHeader` (the only h1, optional breadcrumb, description, actions) then sections (h2) then panels (h3). No
skipped heading levels; heading size is visual (`text-h3` on an h2 is fine), level is structural. Empty and
error states use the same heading level as their siblings (`EmptyState as="h3"`).

## Persian glossary

Use these words consistently. Business = the bot; the Telegram channel is the ربات تلگرام.

| English | Persian |
|---|---|
| capability | قابلیت |
| change proposal | پیشنهاد تغییر (short: تغییر) |
| version | نسخه |
| assistant | دستیار (never «ایجنت», never «دستیار هوشمند») |
| simulator | آزمایش ربات |
| spreadsheets (analyst) | تحلیل فایل اکسل |
| the business (= the bot) | کسب‌وکار |
| the Telegram channel | ربات تلگرام |

## Component inventory

`components/ui` (primitives, token-driven, RTL-correct):

- `button.tsx` `Button`: variants primary, secondary, ghost, danger, link (legacy default/outline/destructive
  still map); sizes sm 32, md 40 (36 on sm+), lg 44, icon; `loading` shows a spinner, sets `aria-busy`, disables.
- `input.tsx` `Input`, `textarea.tsx` `Textarea`, `select.tsx` `Select` (native): radius 8, raised surface,
  strong border; invalid via `aria-invalid`. `FIELD_CLASS` is the shared chrome.
- `label.tsx` `Label`; `switch.tsx` `Switch` (thumb moves toward the end edge when on).
- `tabs.tsx` `Tabs`, `TabsList variant="underline" | "segmented"`, `TabsTrigger`, `TabsContent`.
- `card.tsx` `Card`, `CardHeader/Title/Description/Content/Footer`: 12px, 1px border, no shadow.
- `dialog.tsx` `Dialog` family: radius 16, floating, centered, close button at the end edge.
- `sheet.tsx` `Sheet` family, `SheetContent side="start" | "end" | "bottom"`: edge-anchored dialog.
- `dropdown-menu.tsx` `DropdownMenu` family (items, radio, checkbox, sub-menus); content aligns to start.
- `popover.tsx` `Popover`, `PopoverTrigger`, `PopoverContent`; `tooltip.tsx` `Tooltip` (provider is mounted in
  `Providers`; labels icon-only controls, never carries essential text).
- `toast.tsx` `Toaster` (mounted in `app/layout.tsx`, polite live region) and `use-toast.ts`
  `toast({ title, description?, tone?, duration? })` callable from anywhere; `useToast()`.
- `status-badge.tsx` `StatusBadge tone icon? marker?`; `badge.tsx` `Badge` (generic label, legacy variants).
- `skeleton.tsx` `Skeleton` (size with className); `empty-state.tsx` `EmptyState icon title description action
  as`; `error-state.tsx` `ErrorState message title onRetry`.
- `page-header.tsx` `PageHeader title description actions breadcrumb`; `kbd.tsx` `Kbd`.

`components/app`: `logo.tsx` `Logo size withWordmark` (geometric tile plus «بات‌فورج» at weight 800);
`theme-menu.tsx` `ThemeMenu` (light, dark, system); `providers.tsx` `Providers` (direction, theme, tooltip);
`state-blocks.tsx` (legacy `ErrorNote`, `InfoNote`, `LoadingBlock`, `EmptyState`; prefer the `ui` versions in
new work); `segmented.tsx` (legacy radio-style control; prefer `TabsList variant="segmented"` for views).

`lib`: `theme.tsx` (`ThemeProvider`, `useTheme`, `THEME_INIT_SCRIPT`), `utils.ts` (`cn`, aware of the type
classes so `cn("text-h1","text-fg-muted")` keeps both).

### Shell and routes (Phase 2)

- Routes: every section of a business is a URL under `/bots/[id]`; `lib/routes.ts` `sectionHref(botId, section)`
  is the only place that builds them. Cross-links use `useOpenSection()` (`components/app/shell/use-open-section.ts`),
  never local tab state. Sub-pages (Changes, Reports, Settings) use `SubNav` (`components/app/shell/sub-nav.tsx`).
- Navigation: `lib/nav.ts` `buildNav(collections, capabilities, botId)` is a pure adapter: Overview; Operations
  generated from collections (orders, events, bookings, requests, one item per resource; more than six collapse
  under «سایر داده‌ها»; announcements when its capability is on); Insights; Build; Settings. Count badges are
  attached by item id in `useNavBadges()` (`components/app/shell/nav-list.tsx`).
- Contexts mounted by `app/bots/[id]/layout.tsx` (`components/app/shell/business-root.tsx`): `useBusiness()`
  (bot, collections, capabilities, nav, reload), `useAgentRunContext()` (the agent run; survives navigation),
  `useAssistant()` (open(prefill?), close, toggle, isOpen; Ctrl/⌘+K).
- Frame (`components/app/shell/app-shell.tsx`): ≥1024 a 248px sidebar on the start edge; 640–1023 a 64px icon rail
  with tooltips that expands into a sheet; <640 a top bar plus a fixed five-item bottom tab bar (content reserves
  its height; anything sticky to the viewport bottom must sit above it below 640px). Top bar 56px, content max
  width 1360, padding 24 (16 on mobile). Pages render `PageHeader` (the h1) first; focus moves to it on navigation.

Charts (`components/charts`) use `chart-*` tokens; labels are 12.5 viewBox units (they scale with the chart;
phase work on charts should make them size-stable on narrow screens).

## How to verify a surface

From `frontend/`:

1. `npm run lint`
2. `npx tsc --noEmit`
3. `npm run check:rtl` (and `npm run check:parity` when `lib/types.ts` changed)
4. `NEXT_PUBLIC_MOCK=1 npm run build`
5. `npm run build` (real mode)
6. Browser, mock mode (`NEXT_PUBLIC_MOCK=1 npx next dev -p 3123`; sign in by setting localStorage
   `botforge.mock.user` to `{"id":"mock-user","email":"owner@example.com"}`; force a theme with
   `botforge.theme` = `dark`): screenshot the surface at 1440, 834 and 390 wide, in light and in dark.
   Look for: unreadable text, invisible borders or icons in dark, anything clipped or scrolling sideways at 390,
   mirrored icons, Latin or digit runs reordered inside Persian, focus ring visible by keyboard, one h1 and no
   skipped heading levels, status shown by word plus shape.
7. Keyboard pass: Tab through the surface, open and close every dialog, sheet and menu with Esc.
