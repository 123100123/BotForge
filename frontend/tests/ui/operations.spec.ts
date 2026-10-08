import { expect } from "@playwright/test";
import { loginMock, openSection, test } from "./helpers";

test("workshop record form creates, edits, and deletes through HeroUI controls", async ({ page }) => {
  await loginMock(page, "/bots/bot_sepehr");
  await openSection(page, "داده‌ها", 1440);
  await expect(page.getByRole("heading", { name: "مدیریت داده‌ها" })).toBeVisible();

  await page.getByRole("button", { name: "افزودن کارگاه" }).click();
  const form = page.locator('[data-slot="modal-dialog"]');
  await expect(form).toBeVisible();
  await form.getByLabel("عنوان").fill("کارگاه آزمون رابط کاربری");
  await form.getByLabel("توضیحات").fill("ثبت آزمایشی برای بررسی فرم");
  await form.getByLabel("مدرس").fill("مدرس آزمایشی");
  await form.getByRole("button", { name: "سطح" }).click();
  await page.getByRole("option", { name: "متوسط" }).click();
  await form.locator("#field-starts_at").click();
  await expect(form.locator(".rmdp-wrapper")).toBeVisible();
  await form.locator(".rmdp-calendar .rmdp-day:not(.rmdp-disabled):not(.rmdp-day-hidden):visible span").last().click();
  await expect(form.locator("#field-starts_at")).not.toContainText("انتخاب تاریخ و ساعت");
  await form.getByLabel("هزینه (تومان)").fill("1800000");
  await form.getByText("برگزاری آنلاین", { exact: true }).last().click();
  await expect(form.getByRole("switch", { name: "برگزاری آنلاین" })).toBeChecked();
  await form.getByRole("button", { name: "ذخیره", exact: true }).click();
  await expect(form).toBeHidden();
  const row = page.getByRole("row").filter({ hasText: "کارگاه آزمون رابط کاربری" });
  await expect(row).toBeVisible();

  await row.getByRole("button", { name: /ویرایش مورد/ }).click();
  await expect(form).toBeVisible();
  await form.getByLabel("عنوان").fill("کارگاه ویرایش‌شده");
  await form.getByRole("button", { name: "ذخیره", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: "کارگاه ویرایش‌شده" })).toBeVisible();
  await page.getByRole("row").filter({ hasText: "کارگاه ویرایش‌شده" }).getByRole("button", { name: /حذف مورد/ }).click();
  const confirm = page.getByRole("dialog");
  await expect(confirm).toContainText("حذف کارگاه");
  await confirm.getByRole("button", { name: "حذف", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: "کارگاه ویرایش‌شده" })).toHaveCount(0);
});

test("shop orders expand details and accept a status action", async ({ page }) => {
  await loginMock(page, "/bots/bot_sepehr");
  await openSection(page, "داده‌ها", 1440);
  await page.getByRole("navigation", { name: "مجموعه‌های داده" }).getByRole("button", { name: /سفارش‌ها/ }).click();
  await expect(page.getByRole("heading", { name: "سفارش‌ها" }).last()).toBeVisible();
  const placed = page.getByRole("row").filter({ hasText: "ثبت‌شده" }).first();
  await placed.getByRole("button", { name: /جزئیات سفارش/ }).click();
  await expect(page.getByText("اقلام سفارش")).toBeVisible();
  await expect(page.locator('[id^="order-detail-"]').getByText(/فیلتر روغن/)).toBeVisible();
  await placed.getByRole("button", { name: "تأیید سفارش" }).click();
  await expect(page.getByText(/وضعیت سفارش به «تأیید شده» تغییر کرد/)).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "تأیید شده" }).first()).toBeVisible();
});

test("capability dependency preview and config use HeroUI modal and select", async ({ page }) => {
  await loginMock(page, "/bots/bot_sepehr");
  await openSection(page, "قابلیت‌ها", 1440);
  await page.getByRole("button", { name: /موجودی انبار، غیرفعال/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("نیاز دارد به فهرست محصولات");
  await dialog.getByRole("button", { name: "فعال‌کردن" }).click();
  await expect(dialog).toContainText("فقط موجودی انبار فعال می‌شود");
  await dialog.getByRole("button", { name: "تأیید و فعال‌کردن" }).click();
  await expect(dialog).toBeHidden();
  await page.getByRole("button", { name: /موجودی انبار، فعال/ }).click();
  await expect(dialog.getByLabel("آستانهٔ هشدار کم‌موجودی")).toBeVisible();
  await dialog.getByLabel("آستانهٔ هشدار کم‌موجودی").fill("4");
  await dialog.getByRole("button", { name: "ذخیرهٔ تنظیمات" }).click();
  await expect(dialog.getByText("تنظیمات ذخیره شد.")).toBeVisible();
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("reports period and spreadsheet analyst profile/results remain navigable", async ({ page }) => {
  await loginMock(page, "/bots/bot_sepehr");
  await openSection(page, "گزارش‌ها", 1440);
  await expect(page.getByRole("heading", { name: "گزارش‌های کسب‌وکار" })).toBeVisible();
  await page.getByRole("radiogroup", { name: "بازهٔ زمانی" }).getByText("۳۰ روز", { exact: true }).click();
  await expect(page.getByRole("radio", { name: "۳۰ روز" })).toBeChecked();
  await page.getByRole("navigation", { name: "قابلیت‌های دارای گزارش" }).getByRole("button", { name: /رزرو و ثبت‌نام/ }).click();
  await expect(page.getByRole("heading", { name: "رزرو و ثبت‌نام" })).toBeVisible();

  await page.getByRole("radiogroup", { name: "بخش گزارش‌ها" }).getByText("تحلیلگر داده", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "تحلیل‌گر داده" })).toBeVisible();
  await page.getByLabel("انتخاب فایل اکسل یا CSV").setInputFiles({
    name: "ui-operations.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("title,amount\nUI check,42\n"),
  });
  await expect(page.getByRole("heading", { name: /بررسی فایل ui-operations.csv/ })).toBeVisible();
  await page.getByRole("button", { name: "بررسی فایل‌های قبلی" }).click();
  await page.getByRole("option", { name: /sales.xlsx/ }).click();
  await expect(page.getByRole("heading", { name: /بررسی فایل sales.xlsx/ })).toBeVisible();
  await page.getByRole("tab", { name: /هزینه‌ها/ }).click();
  await expect(page.getByRole("tab", { name: /هزینه‌ها/ })).toHaveAttribute("aria-selected", "true");

  await page.getByRole("button", { name: "ویرایش", exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("ویرایش پروفایل");
  await dialog.getByText("گزارش روزانهٔ کارکنان", { exact: true }).click();
  await dialog.getByRole("button", { name: "ذخیره", exact: true }).click();
  await expect(dialog).toBeHidden();
  await page.getByRole("button", { name: /sales-new-format.xlsx/ }).click();
  await expect(page.getByText(/مطابقت ندارد/)).toBeVisible();
});

test("settings sections keep selects and switches reachable", async ({ page }) => {
  await loginMock(page, "/bots/bot_sepehr");
  await openSection(page, "تنظیمات", 1440);
  await page.getByRole("button", { name: "تیم", exact: true }).click();
  await expect(page.getByRole("heading", { name: "تیم", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "نقش رضا کریمی" }).click();
  await page.getByRole("option", { name: "مدیر" }).click();
  await expect(page.getByRole("button", { name: "نقش رضا کریمی" })).toContainText("مدیر");
  await page.getByRole("button", { name: "گروه‌ها", exact: true }).click();
  await expect(page.getByRole("heading", { name: "گروه‌ها", exact: true })).toBeVisible();
  await expect(page.getByRole("listitem").getByText("گروه مشتریان (نمونه)")).toBeVisible();
  await page.getByRole("button", { name: "اعلان و زمان‌بندی" }).click();
  await page.getByRole("button", { name: "مخاطب اعلان" }).click();
  await page.getByRole("option", { name: "همکاران" }).click();
  await expect(page.getByRole("button", { name: "مخاطب اعلان" })).toContainText("همکاران");
  await page.getByText("گروه مشتریان (نمونه)", { exact: true }).last().click();
  await expect(page.getByRole("checkbox", { name: "گروه مشتریان (نمونه)" })).toBeChecked();
  const weekly = page.getByRole("switch", { name: "فعال بودن خلاصهٔ هفتگی" });
  await page.getByText("خلاصهٔ هفتگی", { exact: true }).click();
  await expect(weekly).toBeChecked();
  await page.getByRole("button", { name: "ذخیرهٔ زمان‌بندی" }).click();
  await expect(page.getByText("زمان‌بندی ذخیره شد.")).toBeVisible();
});

test("capability pending save blocks dismissal and error feedback retains focus", async ({ page }) => {
  // Extend the fixture client's 120ms latency so the pending state is deterministic.
  await page.addInitScript(() => {
    const nativeTimeout = window.setTimeout.bind(window);
    window.setTimeout = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => nativeTimeout(handler, timeout === 120 ? 800 : timeout, ...args)) as typeof window.setTimeout;
  });
  await loginMock(page, "/bots/bot_sepehr");
  await openSection(page, "قابلیت‌ها", 1440);
  await page.getByRole("button", { name: /موجودی انبار، غیرفعال/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "فعال‌کردن", exact: true }).click();
  await dialog.getByRole("button", { name: "تأیید و فعال‌کردن" }).click();
  await expect(dialog).toBeHidden();
  await page.getByRole("button", { name: /موجودی انبار، فعال/ }).click();
  await dialog.getByLabel("آستانهٔ هشدار کم‌موجودی").fill("4");
  await dialog.getByRole("button", { name: "ذخیرهٔ تنظیمات" }).click();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "بستن", exact: true })).toBeDisabled();
  await expect(dialog.getByText("تنظیمات ذخیره شد.")).toBeVisible();
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await dialog.getByLabel("آستانهٔ هشدار کم‌موجودی").fill("-1");
  await dialog.getByRole("button", { name: "ذخیرهٔ تنظیمات" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});
