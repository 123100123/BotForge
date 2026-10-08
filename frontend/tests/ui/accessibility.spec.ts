import { expect } from "@playwright/test";
import { test, loginMock, openSection } from "./helpers";

test("keyboard focus stays in the dialog and returns to its trigger", async ({ page }) => {
  await loginMock(page);
  const trigger = page.getByRole("button", { name: "ربات جدید", exact: true });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});

test("200 percent layout zoom and reduced motion retain reachable workspace controls", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await loginMock(page, "/bots/bot_sepehr");
  // CSS zoom exercises doubled text/control sizes and reflow within the same viewport.
  await page.addStyleTag({ content: "html { zoom: 2; }" });
  await expect(page.getByRole("heading", { name: "کارگاه‌های سپهر" })).toBeVisible();
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior)).toBe("auto");
  const zoomedWidth = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  const overflow = await page.evaluate(() => [...document.querySelectorAll("body *")].filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1 || el.getBoundingClientRect().left < -1).slice(0, 8).map((el) => ({ tag: el.tagName, classes: el.className, text: el.textContent?.slice(0, 60) })));
  expect(zoomedWidth.scroll, JSON.stringify(overflow)).toBeLessThanOrEqual(zoomedWidth.client + 1);
  await page.addStyleTag({ content: "html { zoom: 1; }" });
  await page.setViewportSize({ width: 720, height: 900 });
  await openSection(page, "تنظیمات", 720);
  await page.getByRole("button", { name: "اعلان و زمان‌بندی" }).click();
  await expect(page.getByRole("switch").first()).toBeVisible();
});

test("shared theme text and action colors meet normal-text contrast", async ({ page }) => {
  await loginMock(page);
  for (const theme of ["روشن", "تیره"]) {
    await page.getByRole("button", { name: `حالت ${theme}` }).click();
    const ratios = await page.evaluate(() => {
      const tokens = getComputedStyle(document.documentElement);
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const ctx = canvas.getContext("2d")!;
      function luminance(token: string) {
        ctx.fillStyle = tokens.getPropertyValue(token).trim();
        ctx.fillRect(0, 0, 1, 1);
        const channels = [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3).map((v) => {
          const n = v / 255;
          return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
        });
        return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
      }
      return [["--foreground", "--background"], ["--muted", "--surface"], ["--muted", "--surface-secondary"], ["--accent-foreground", "--accent"]].map(([text, surface]) => {
        const a = luminance(text), b = luminance(surface);
        return { pair: `${text}/${surface}`, ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
      });
    });
    for (const { pair, ratio } of ratios) expect(ratio, `${theme}: ${pair}`).toBeGreaterThanOrEqual(4.5);
  }
});
