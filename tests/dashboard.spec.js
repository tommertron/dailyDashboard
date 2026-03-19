// @ts-check
const { test, expect } = require('@playwright/test');

// Wait for the dashboard to finish its initial load
async function waitForDashboard(page) {
  await page.goto('/');
  // At minimum the header and date badge must be visible
  await expect(page.locator('#date-badge')).toBeVisible({ timeout: 15_000 });
}

// ── Page load ────────────────────────────────────────────────────────────────

test('page loads and shows date badge', async ({ page }) => {
  await waitForDashboard(page);
  const text = await page.locator('#date-badge').textContent();
  expect(text?.trim().length).toBeGreaterThan(0);
});

test('AI summary container is present', async ({ page }) => {
  await waitForDashboard(page);
  await expect(page.locator('#ai-summary-text')).toBeVisible();
});

test('shed heat banner is present', async ({ page }) => {
  await waitForDashboard(page);
  await expect(page.locator('#shed-heat-banner')).toBeVisible();
});

// ── Panels render ────────────────────────────────────────────────────────────

const panels = [
  'weather',
  'tasks',
  'smartSchedule',
  'bills',
  'wisdom',
  'shed',
  'home',
  'piStatus',
  'tvShows',
  'links',
];

for (const panel of panels) {
  test(`panel "${panel}" is present in DOM`, async ({ page }) => {
    await waitForDashboard(page);
    // Panels can be hidden by user settings; assert they exist in DOM at minimum
    await expect(page.locator(`[data-panel="${panel}"]`)).toBeAttached();
  });
}

// ── Panel containers load content ────────────────────────────────────────────

test('weather container has content', async ({ page }) => {
  await waitForDashboard(page);
  // Give the async data load a moment
  await page.waitForTimeout(3_000);
  const container = page.locator('#weather-container');
  await expect(container).not.toBeEmpty();
});

test('wisdom container shows a quote', async ({ page }) => {
  await waitForDashboard(page);
  await page.waitForTimeout(3_000);
  const container = page.locator('#wisdom-container');
  await expect(container).not.toBeEmpty();
});

test('todos container renders', async ({ page }) => {
  await waitForDashboard(page);
  await page.waitForTimeout(3_000);
  await expect(page.locator('#todos-container')).toBeVisible();
});

// ── Settings modal ───────────────────────────────────────────────────────────

test('settings modal opens and closes', async ({ page }) => {
  await waitForDashboard(page);
  await page.locator('.settings-btn').click();
  await expect(page.locator('#settings-overlay')).toBeVisible();

  // Close by pressing Escape
  await page.keyboard.press('Escape');
  await expect(page.locator('#settings-overlay')).toBeHidden();
});

test('settings modal has expected panes', async ({ page }) => {
  await waitForDashboard(page);
  await page.locator('.settings-btn').click();
  await expect(page.locator('#settings-pane-preferences')).toBeAttached();
  await expect(page.locator('#settings-pane-api-keys')).toBeAttached();
  await expect(page.locator('#settings-pane-ai-prompts')).toBeAttached();
});

// ── Refresh buttons ──────────────────────────────────────────────────────────

test('wisdom refresh button is clickable', async ({ page }) => {
  await waitForDashboard(page);
  const btn = page.locator('#wisdom-refresh-btn');
  await expect(btn).toBeVisible();
  await btn.click();
  // Should not throw or navigate away
  await expect(page.locator('#wisdom-container')).toBeVisible();
});

test('tasks refresh button is clickable', async ({ page }) => {
  await waitForDashboard(page);
  const btn = page.locator('#todos-refresh-btn');
  await expect(btn).toBeVisible();
  await btn.click();
  await expect(page.locator('#todos-container')).toBeVisible();
});

test('bills refresh button is present', async ({ page }) => {
  await waitForDashboard(page);
  // Bills panel may be hidden in settings; assert button is in DOM
  await expect(page.locator('#money-refresh-btn')).toBeAttached();
});

// ── Smart schedule ───────────────────────────────────────────────────────────

test('smart schedule timeline container is present', async ({ page }) => {
  await waitForDashboard(page);
  await expect(page.locator('#smart-schedule-timeline')).toBeVisible();
});

// ── Add task form ────────────────────────────────────────────────────────────

test('add task form opens and closes', async ({ page }) => {
  await waitForDashboard(page);
  await page.waitForTimeout(3_000); // wait for todos to load

  // Form is only injected when there are tasks; skip if task list is empty
  const formExists = await page.locator('#todo-add-form').count() > 0;
  if (!formExists) {
    test.skip();
    return;
  }

  const addBtn = page.locator('#todos-add-btn');
  await expect(addBtn).toBeVisible();
  await addBtn.click();
  await expect(page.locator('#todo-add-form')).toBeVisible();
  // Cancel
  await page.locator('.todo-add-cancel').click();
  await expect(page.locator('#todo-add-form')).toBeHidden();
});

// ── Thermostat modal ─────────────────────────────────────────────────────────

test('shed thermostat modal opens when thermostat control is clicked', async ({ page }) => {
  await waitForDashboard(page);
  await page.waitForTimeout(3_000);

  // The thermostat button is rendered inside the shed panel after data loads
  const thermostatBtn = page.locator('#shed-container .thermostat-control-btn').first();
  if (await thermostatBtn.isVisible()) {
    await thermostatBtn.click();
    await expect(page.locator('#thermostat-control-overlay')).toBeVisible();
    // Close by clicking overlay
    await page.locator('#thermostat-control-overlay').click({ position: { x: 10, y: 10 } });
  } else {
    test.skip();
  }
});

// ── No JS errors on load ─────────────────────────────────────────────────────

test('no uncaught JS errors on initial load', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  await waitForDashboard(page);
  await page.waitForTimeout(3_000);
  expect(errors).toHaveLength(0);
});
