import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import assert from "node:assert/strict";
await mkdir("artifacts", { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 1000 },
  deviceScaleFactor: 1,
});
const errors = [];
page.on("pageerror", (err) => errors.push(err.message));
try {
  await page.goto("http://localhost:4317");
  await page.waitForFunction(
    () => !document.body.textContent.includes("载入工作区…"),
  );
  if (await page.getByRole("button", { name: "打开示例论文" }).count())
    await page.getByRole("button", { name: "打开示例论文" }).click();
  else {
    await page.getByRole("button", { name: "切换项目", exact: true }).click();
    await page.getByRole("button", { name: "示例项目", exact: true }).click();
  }
  await page.locator(".paper canvas").waitFor({ timeout: 120000 });
  await page.waitForFunction(
    () => document.querySelectorAll(".textLayer span").length > 20,
  );
  await page.waitForTimeout(600);
  const canvasCheck = await page.locator(".paper canvas").evaluate((c) => {
    const data = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let nonWhite = 0;
    for (let i = 0; i < data.length; i += 4)
      if (data[i] < 220 && data[i + 1] < 220 && data[i + 2] < 220) nonWhite++;
    return { width: c.width, height: c.height, nonWhite };
  });
  assert.ok(canvasCheck.nonWhite > 3000, JSON.stringify(canvasCheck));
  await page.getByRole("button", { name: "添加位置批注", exact: true }).click();
  const paper = await page.locator(".paper").boundingBox();
  await page.mouse.click(paper.x + paper.width * 0.5, paper.y + 170);
  await page
    .getByRole("textbox", { name: "批注意见" })
    .fill("请在摘要里进一步明确本文的贡献范围，不要加入没有证据的性能数字。");
  await page.getByRole("button", { name: "添加批注", exact: true }).click();
  await page
    .locator(".comment")
    .filter({ hasText: "请在摘要里进一步明确" })
    .waitFor();
  assert.equal(await page.locator(".pin").count(), 1);
  await page.screenshot({ path: "artifacts/desktop.png", fullPage: true });
  await page.getByRole("button", { name: "标记已解决", exact: true }).click();
  await page.getByLabel("批注筛选").selectOption("resolved");
  await page.getByRole("button", { name: "重新打开", exact: true }).waitFor();
  await page.getByRole("button", { name: "重新打开", exact: true }).click();
  await page.getByLabel("批注筛选").selectOption("open");
  await page
    .locator(".comment")
    .filter({ hasText: "请在摘要里进一步明确" })
    .waitFor();
  await page.getByRole("button", { name: "审稿 Skills", exact: false }).click();
  assert.equal(await page.locator(".skill-card").count(), 8);
  await page.screenshot({ path: "artifacts/skills.png", fullPage: true });
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await page.reload();
  await page
    .locator(".comment")
    .filter({ hasText: "请在摘要里进一步明确" })
    .waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(600);
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "mobile page must not overflow",
  );
  await page.getByLabel("PDF 缩放").selectOption("1.5");
  await page.waitForFunction(
    () => document.querySelector(".paper canvas").width > 850,
  );
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "zoom stays inside PDF viewport",
  );
  await page.getByLabel("PDF 缩放").selectOption("fit");
  await page.waitForFunction(
    () => document.querySelector(".paper canvas").width < 400,
  );
  await page.screenshot({ path: "artifacts/mobile.png", fullPage: true });
  await page.getByRole("button", { name: "审稿 Skills", exact: false }).click();
  await page.screenshot({
    path: "artifacts/mobile-skills.png",
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ success: true, canvasCheck, errors }));
} finally {
  await browser.close();
}
