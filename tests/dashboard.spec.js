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

// ── Raindrop link modal (shared helper) ──────────────────────────────────────

async function openModalFromPanel(page, containerSelector, itemSelector) {
  await page.waitForTimeout(3_000);
  const item = page.locator(containerSelector).locator(itemSelector).first();
  if (await item.count() === 0) return false;
  await item.click();
  await expect(page.locator('#fav-link-overlay')).toHaveClass(/visible/, { timeout: 5_000 });
  return true;
}

// ── Favourites panel modal ────────────────────────────────────────────────────

test('tapping a favourite link opens the action modal', async ({ page }) => {
  await waitForDashboard(page);
  const opened = await openModalFromPanel(page, '#links-favourites-container', '.raindrop-link-btn');
  if (!opened) return;

  await expect(page.locator('#fav-modal-title')).not.toBeEmpty();
  await expect(page.locator('#fav-modal-open-btn')).toBeVisible();
  await expect(page.locator('#fav-modal-edit-btn')).toBeVisible();
  await expect(page.locator('#fav-modal-todoist-btn')).toBeVisible();
  await expect(page.locator('#fav-modal-fav-btn')).toBeVisible();
});

test('favourite modal closes when backdrop is clicked', async ({ page }) => {
  await waitForDashboard(page);
  const opened = await openModalFromPanel(page, '#links-favourites-container', '.raindrop-link-btn');
  if (!opened) return;

  await page.locator('#fav-link-overlay').click({ position: { x: 10, y: 10 } });
  await expect(page.locator('#fav-link-overlay')).not.toHaveClass(/visible/);
});

test('favourite modal "Open Link" has valid href', async ({ page }) => {
  await waitForDashboard(page);
  const opened = await openModalFromPanel(page, '#links-favourites-container', '.raindrop-link-btn');
  if (!opened) return;

  const href = await page.locator('#fav-modal-open-btn').getAttribute('href');
  expect(href).toMatch(/^https?:\/\//);
});

test('favourite modal "Edit in Raindrop" has raindrop.io href', async ({ page }) => {
  await waitForDashboard(page);
  const opened = await openModalFromPanel(page, '#links-favourites-container', '.raindrop-link-btn');
  if (!opened) return;

  const href = await page.locator('#fav-modal-edit-btn').getAttribute('href');
  expect(href).toMatch(/raindrop\.io/);
});

test('favourite modal "Remove Favourite" button removes item optimistically', async ({ page }) => {
  await waitForDashboard(page);
  await page.waitForTimeout(3_000);
  const container = page.locator('#links-favourites-container');
  const items = container.locator('.raindrop-link-btn');
  if (await items.count() === 0) return;

  const firstId = await items.first().getAttribute('data-id');
  await items.first().click();
  await expect(page.locator('#fav-link-overlay')).toHaveClass(/visible/);

  // Click Remove — modal should close immediately
  await page.locator('#fav-modal-fav-btn').click();
  await expect(page.locator('#fav-link-overlay')).not.toHaveClass(/visible/);

  // Item should be gone from DOM immediately (optimistic removal)
  await expect(container.locator(`[data-id="${firstId}"]`)).toHaveCount(0);
});

test('favourite modal action buttons meet 44px touch target', async ({ page }) => {
  await waitForDashboard(page);
  const opened = await openModalFromPanel(page, '#links-favourites-container', '.raindrop-link-btn');
  if (!opened) return;

  for (const id of ['#fav-modal-open-btn', '#fav-modal-edit-btn', '#fav-modal-todoist-btn', '#fav-modal-fav-btn']) {
    const box = await page.locator(id).boundingBox();
    expect(box, `${id} must have a bounding box`).not.toBeNull();
    expect(box.height, `${id} height`).toBeGreaterThanOrEqual(44);
  }
});

// ── Random links modal ────────────────────────────────────────────────────────

test('tapping a random link opens the action modal', async ({ page }) => {
  await waitForDashboard(page);
  const opened = await openModalFromPanel(page, '#links-random-container', '.raindrop-link-btn');
  if (!opened) return;

  await expect(page.locator('#fav-modal-title')).not.toBeEmpty();
  await expect(page.locator('#fav-modal-open-btn')).toBeVisible();
  await expect(page.locator('#fav-modal-edit-btn')).toBeVisible();
  await expect(page.locator('#fav-modal-todoist-btn')).toBeVisible();
  await expect(page.locator('#fav-modal-fav-btn')).toBeVisible();
});

test('random link modal shows correct favourite toggle label', async ({ page }) => {
  await waitForDashboard(page);
  await page.waitForTimeout(3_000);
  const btn = page.locator('#links-container .raindrop-link-btn').first();
  if (await btn.count() === 0) return;

  const isFav = (await btn.getAttribute('data-is-fav')) === 'true';
  await btn.click();
  await expect(page.locator('#fav-link-overlay')).toHaveClass(/visible/);

  const favBtnText = await page.locator('#fav-modal-fav-btn').textContent();
  if (isFav) {
    expect(favBtnText).toContain('Remove');
  } else {
    expect(favBtnText).toContain('Add');
  }
});

test('random link modal closes when backdrop is clicked', async ({ page }) => {
  await waitForDashboard(page);
  const opened = await openModalFromPanel(page, '#links-random-container', '.raindrop-link-btn');
  if (!opened) return;

  await page.locator('#fav-link-overlay').click({ position: { x: 10, y: 10 } });
  await expect(page.locator('#fav-link-overlay')).not.toHaveClass(/visible/);
});

// ── No JS errors on load ─────────────────────────────────────────────────────

test('no uncaught JS errors on initial load', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  await waitForDashboard(page);
  await page.waitForTimeout(3_000);
  expect(errors).toHaveLength(0);
});

// ── Home Stats page ───────────────────────────────────────────────────────────

async function waitForHomeStats(page) {
  await page.goto('/home-stats.html');
  await expect(page.locator('.stats-header')).toBeVisible({ timeout: 10_000 });
}

test('home-stats page loads with header and back button', async ({ page }) => {
  await waitForHomeStats(page);
  await expect(page.locator('.back-btn')).toBeVisible();
  await expect(page.locator('.stats-header h1')).toContainText('Home Stats');
});

test('home-stats both chart sections are present', async ({ page }) => {
  await waitForHomeStats(page);
  await expect(page.locator('#shed-section')).toBeVisible();
  await expect(page.locator('#home-section')).toBeVisible();
});

test('home-stats shed chart renders bars (not just loading)', async ({ page }) => {
  await waitForHomeStats(page);
  await page.waitForTimeout(5_000);
  const container = page.locator('#heater-chart-container');
  await expect(container).not.toBeEmpty();
  // Should have actual bar elements, not just a loading/error message
  const bars = container.locator('.heater-chart-bar-container');
  expect(await bars.count()).toBeGreaterThan(0);
});

test('home-stats home chart renders bars (not just loading)', async ({ page }) => {
  await waitForHomeStats(page);
  await page.waitForTimeout(5_000);
  const container = page.locator('#home-heater-chart-container');
  await expect(container).not.toBeEmpty();
  const bars = container.locator('.heater-chart-bar-container');
  expect(await bars.count()).toBeGreaterThan(0);
});

test('home-stats chart bars have non-zero rendered height on mobile', async ({ page }) => {
  await waitForHomeStats(page);
  await page.waitForTimeout(5_000);

  // The .heater-chart-bars wrapper must have measurable height
  const shedBarsBox = await page.locator('#shed-heater-chart-bars').boundingBox();
  expect(shedBarsBox, 'shed chart bars must be in viewport').not.toBeNull();
  expect(shedBarsBox.height).toBeGreaterThan(50);

  const homeBarsBox = await page.locator('#home-heater-chart-bars').boundingBox();
  expect(homeBarsBox, 'home chart bars must be in viewport').not.toBeNull();
  expect(homeBarsBox.height).toBeGreaterThan(50);
});

test('home-stats temp SVG line is rendered in shed chart', async ({ page }) => {
  await waitForHomeStats(page);
  await page.waitForTimeout(5_000);
  const svg = page.locator('#shed-heater-chart-bars .heater-chart-temp-line');
  expect(await svg.count()).toBeGreaterThan(0);
});

test('home-stats back button navigates to dashboard', async ({ page }) => {
  await waitForHomeStats(page);
  await page.locator('.back-btn').click();
  await expect(page).toHaveURL('/');
});

test('home-stats no uncaught JS errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  await waitForHomeStats(page);
  await page.waitForTimeout(5_000);
  expect(errors).toHaveLength(0);
});
