const { test, expect } = require('@playwright/test');

test('storefront loads and shows the catalog', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Bookly/);
  const cards = page.locator('.card');
  await expect(cards.first()).toBeVisible();
  const count = await cards.count();
  expect(count).toBeGreaterThan(5); // full 10-book catalog should have loaded via /api/catalog
});

test('book covers actually loaded (not the CSS fallback)', async ({ page }) => {
  await page.goto('/');
  const firstCoverImg = page.locator('.cover-img').first();
  await expect(firstCoverImg).toBeVisible();
  // naturalWidth stays 0 until the image finishes loading -- poll rather
  // than reading it once immediately after the element appears. If it
  // failed to load, the JS fallback (a .cover-fallback div) would have
  // replaced <img> entirely and this locator would stop resolving.
  await expect.poll(() => firstCoverImg.evaluate((img) => img.naturalWidth)).toBeGreaterThan(0);
});

test('search filters the catalog to matching titles only', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.card')).toHaveCount(10);

  await page.fill('#search', 'Dune');
  await expect(page.locator('.card')).toHaveCount(1);
  await expect(page.locator('.card .title')).toHaveText('Dune');

  await page.fill('#search', 'zzzznotarealtitle');
  await expect(page.locator('.card')).toHaveCount(0);
  await expect(page.locator('#empty-state')).toBeVisible();
});

test('add to cart increments the cart badge and shows confirmation', async ({ page }) => {
  await page.goto('/');
  const badge = page.locator('#cart-count');
  await expect(badge).not.toHaveClass(/show/);

  const firstAddBtn = page.locator('.add-btn').first();
  await firstAddBtn.click();

  await expect(badge).toHaveClass(/show/);
  await expect(badge).toHaveText('1');
  await expect(firstAddBtn).toHaveText('Added ✓');

  // second item -> counter increments, doesn't reset
  await page.locator('.add-btn').nth(1).click();
  await expect(badge).toHaveText('2');
});

test('clicking the cart icon opens the support widget instead of a real checkout', async ({ page }) => {
  await page.goto('/');
  await page.click('#cart-btn');
  await expect(page.locator('#bookly-widget')).toHaveClass(/open/);
});
