import { chromium } from "@playwright/test";
import { strict as assert } from "node:assert";
import fs from "node:fs";

const origin = process.env.SMOKE_BASE_URL;
if (!origin)
  throw new Error(
    "Run through scripts/verify_phase2.py backend/tests/integration/test_frontend.py",
  );
const edge = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const browser = await chromium.launch({
  headless: true,
  ...(fs.existsSync(edge) ? { executablePath: edge } : {}),
});
let page;
try {
  page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    baseURL: origin,
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(origin);
  await page
    .getByLabel("Password", { exact: true })
    .fill("ephemeral-test-password");
  await page.getByRole("button", { name: "Sign in →", exact: true }).click();
  await page.getByText("Employee workspace", { exact: true }).waitFor();
  fs.mkdirSync("test-results", { recursive: true });
  await page.screenshot({ path: "test-results/welcome.png", fullPage: true });
  await page
    .getByLabel("Message People assistant")
    .fill("My remaining leave balance");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await page.getByText("Leave balance", { exact: true }).waitFor();
  const taskId = (await page.getByTestId("task-id").textContent()).trim();
  assert(taskId);
  const composer = page.locator("#message");
  assert(await composer.isEnabled());
  await composer.fill("Use plain language");
  await page.getByRole("button", { name: "Send note", exact: true }).click();
  await page
    .locator(".note p")
    .filter({ hasText: "Use plain language" })
    .waitFor();
  let snapshot = await (await page.request.get("/api/v1/_test/inspect")).json();
  assert.equal(snapshot.notes, 1);
  assert.equal(snapshot.requests, 0);
  assert.equal(snapshot.task_id, taskId);
  await page.request.post("/api/v1/_test/release");
  await page.getByText(/In plain language:/).waitFor();
  assert.equal(
    (await page.getByTestId("task-id").textContent()).trim(),
    taskId,
  );
  await page.getByLabel("Start date", { exact: true }).fill("2027-01-04");
  await page.getByLabel("End date", { exact: true }).fill("2027-01-06");
  await page
    .getByRole("button", { name: "Prepare proposal", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Confirm booking", exact: true })
    .waitFor();
  snapshot = await (await page.request.get("/api/v1/_test/inspect")).json();
  assert.equal(snapshot.requests, 0);
  assert.equal(snapshot.balance, "12.00");
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "Confirm booking", exact: true })
    .scrollIntoViewIfNeeded();
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  );
  await page.screenshot({
    path: "test-results/approval-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByRole("button", { name: "Confirm booking", exact: true })
    .click();
  await page
    .getByText("Leave booked. Remaining balance: 9.00 days.", { exact: true })
    .waitFor();
  snapshot = await (await page.request.get("/api/v1/_test/inspect")).json();
  assert.equal(snapshot.requests, 1);
  assert.equal(snapshot.balance, "9.00");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByLabel("Username", { exact: true }).fill("leila");
  await page
    .getByLabel("Password", { exact: true })
    .fill("ephemeral-test-password");
  await page.getByRole("button", { name: "Sign in →", exact: true }).click();
  await page.getByText("HR workspace", { exact: true }).waitFor();
  // An inaccessible task must show a helpful error and clear the previous workspace.
  await page.route("**/api/v1/conversations/*/tasks", (route) =>
    route.fulfill({
      status: 403,
      contentType: "application/json",
      body: '{"error":{"code":"forbidden"}}',
    }),
  );
  await page.getByLabel("Message People assistant").fill("My balance");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "permission" }).waitFor();
  await page.unroute("**/api/v1/conversations/*/tasks");
  assert.equal(
    await page
      .getByText("Leave booked. Remaining balance: 9.00 days.", { exact: true })
      .count(),
    0,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await composer.isVisible());
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  );
  fs.mkdirSync("test-results", { recursive: true });
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: "test-results/workspace.png", fullPage: true });
  assert.deepEqual(errors, []);
  console.log(
    "SMOKE PASS: real login + SSE, same-ID mid-run note, no hidden booking, human confirmation, tenant switch, permission error, mobile layout.",
  );
} catch (error) {
  if (page) {
    await page.screenshot({ path: "test-results/failure.png", fullPage: true });
    console.error(await page.locator("body").innerText());
  }
  throw error;
} finally {
  await browser.close();
}
