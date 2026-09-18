const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const url = process.env.JOBFLOW_TEST_URL || "http://127.0.0.1:7871/";

async function verifyDisclosure(page, kind) {
  const detailsSelector = `#jf-${kind}-details`;
  const bodySelector = `${detailsSelector}-body`;
  await page.locator(detailsSelector).waitFor();
  await page.waitForFunction(
    ([detailsId, bodyId]) => {
      const details = document.querySelector(detailsId);
      const body = document.querySelector(bodyId);
      return details?.getAttribute("aria-owns") === body?.id
        && body?.getAttribute("aria-labelledby");
    },
    [detailsSelector, bodySelector],
    { timeout: 10000 },
  );

  const collapsed = await page.locator(detailsSelector).evaluate((details, selector) => {
    const body = document.querySelector(selector);
    const summary = details.querySelector("summary");
    return {
      owns: details.getAttribute("aria-owns"),
      controls: summary?.getAttribute("aria-controls"),
      expanded: summary?.getAttribute("aria-expanded"),
      labelledBy: body?.getAttribute("aria-labelledby"),
      open: details.open,
      bodyVisible: body ? body.getClientRects().length > 0 : null,
      bodyId: body?.id,
      summaryId: summary?.id,
    };
  }, bodySelector);

  assert.equal(collapsed.owns, collapsed.bodyId);
  assert.equal(collapsed.controls, collapsed.bodyId);
  assert.equal(collapsed.labelledBy, collapsed.summaryId);
  assert.equal(collapsed.expanded, "false");
  assert.equal(collapsed.open, false);
  assert.equal(collapsed.bodyVisible, false);

  await page.locator(`${detailsSelector} > summary`).click();
  const expanded = await page.locator(detailsSelector).evaluate((details, selector) => {
    const body = document.querySelector(selector);
    return {
      open: details.open,
      expanded: details.querySelector("summary")?.getAttribute("aria-expanded"),
      bodyVisible: body ? body.getClientRects().length > 0 : null,
    };
  }, bodySelector);
  assert.equal(expanded.open, true);
  assert.equal(expanded.expanded, "true");
  assert.equal(expanded.bodyVisible, true);
  await page.locator(`${detailsSelector} > summary`).click();
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [
      { width: 1440, height: 1000 },
      { width: 390, height: 844 },
    ]) {
      const page = await browser.newPage({ viewport });
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
      await page.getByRole("button", { name: "일정 만들기" }).waitFor();
      await verifyDisclosure(page, "schedule");
      await verifyDisclosure(page, "unplaced");
      await page.locator("#jf-create-schedule").click();
      await page.getByRole("button", { name: "예시 불러오기" }).click();
      await page.locator("#jf-step-review").waitFor({ state: "visible" });
      await page.getByLabel("검토 완료").check();
      await page.getByRole("button", { name: "캘린더에 반영" }).click();
      await page.locator("#jf-step-calendar").waitFor({ state: "visible" });
      await page.getByRole("button", { name: "캘린더에서 보기" }).click();
      await page.locator("#jf-compose-panel:not(.open)").waitFor({ state: "attached" });
      await verifyDisclosure(page, "schedule");
      await verifyDisclosure(page, "unplaced");
      await page.close();
    }
  } finally {
    await browser.close();
  }
  console.log("desktop/mobile disclosure DOM semantics passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
