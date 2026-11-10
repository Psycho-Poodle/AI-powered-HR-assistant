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
  assert.equal(await page.getByTestId("leave-request-form").count(), 0);
  async function sendCompleted(message) {
    await page
      .getByRole("button", { name: "Send message", exact: true })
      .waitFor();
    await composer.fill(message);
    const queued = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        /\/conversations\/[^/]+\/tasks$/.test(new URL(r.url()).pathname),
    );
    await page
      .getByRole("button", { name: "Send message", exact: true })
      .click();
    const id = (await (await queued).json()).task_id;
    await page.waitForFunction(
      (id) =>
        document
          .querySelector('[data-testid="task-id"]')
          ?.textContent.trim() === id,
      id,
    );
    await page
      .getByRole("button", { name: "Send message", exact: true })
      .waitFor();
  }
  for (const message of [
    "Hello",
    "Explain the late attendance policy",
    "Maybe leave?",
  ]) {
    await sendCompleted(message);
    if (message.includes("policy"))
      await page
        .getByText(/one-day pay cut/)
        .first()
        .waitFor();
    assert.equal(await page.getByTestId("leave-request-form").count(), 0);
  }
  await sendCompleted("Help me apply for three days of leave");
  await page.getByTestId("leave-request-form").waitFor();
  await page.getByLabel("Start date", { exact: true }).fill("2027-01-04");
  await page.getByLabel("End date", { exact: true }).fill("2027-01-06");
  await page.getByRole("button", { name: /New conversation/ }).click();
  assert.equal(await page.getByTestId("leave-request-form").count(), 0);
  await page
    .getByRole("button", { name: /My remaining leave balance/ })
    .click();
  await page.getByTestId("leave-request-form").waitFor();
  await page.getByRole("button", { name: "Request 1", exact: true }).click();
  await page.getByText(/In plain language:/).waitFor();
  assert.equal(await page.getByTestId("leave-request-form").count(), 0);
  await page.getByRole("button", { name: "Request 5", exact: true }).click();
  await page.getByTestId("leave-request-form").waitFor();
  assert.equal(
    await page.getByLabel("Start date", { exact: true }).inputValue(),
    "2027-01-04",
  );
  assert.equal(
    await page.getByLabel("End date", { exact: true }).inputValue(),
    "2027-01-06",
  );
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
  await page.getByRole("button", { name: "Request 1", exact: true }).click();
  await page.getByText(/In plain language:/).waitFor();
  await page.getByRole("button", { name: "Request 5", exact: true }).click();
  await page.getByText("CONFIRMED", { exact: true }).waitFor();
  assert.equal(await page.getByTestId("leave-request-form").count(), 0);
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
