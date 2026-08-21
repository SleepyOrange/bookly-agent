const { test, expect } = require('@playwright/test');

test('contact page loads with its own widget instance, genuinely page-agnostic', async ({ page }) => {
  await page.goto('/contact');
  await expect(page.locator('#bookly-widget')).toBeVisible();
  await expect(page.locator('#bw-launcher')).toBeVisible();

  await page.click('#bw-launcher');
  await expect(page.locator('#bookly-widget')).toHaveClass(/open/);
});

test('contact page sidebar "Open chat" button works', async ({ page }) => {
  await page.goto('/contact');
  await page.click('.chat-promo button:has-text("Open chat")');
  await expect(page.locator('#bookly-widget')).toHaveClass(/open/);
});

test('contact form shows a confirmation on submit (no real backend)', async ({ page }) => {
  await page.goto('/contact');
  await page.fill('#cf-name', 'Alice Nguyen');
  await page.fill('#cf-email', 'alice@example.com');
  await page.fill('#cf-message', 'Where is my order?');
  await page.click('#contact-form button[type=submit]');

  await expect(page.locator('#confirm')).toHaveClass(/show/);
  await expect(page.locator('#contact-form')).toBeHidden();
});

test('confirmation panel offers a path into the widget', async ({ page }) => {
  await page.goto('/contact');
  await page.fill('#cf-name', 'Alice Nguyen');
  await page.fill('#cf-email', 'alice@example.com');
  await page.fill('#cf-message', 'test');
  await page.click('#contact-form button[type=submit]');

  await page.click('.confirm button:has-text("Chat with support instead")');
  await expect(page.locator('#bookly-widget')).toHaveClass(/open/);
});

test('footer deep-link on the contact page also pre-fills and sends', async ({ page }) => {
  await page.goto('/contact');
  await page.click('footer button:has-text("Returns")'); // visible label -- the actual question is in data-widget-ask
  await expect(page.locator('#bookly-widget')).toHaveClass(/open/);
  await expect(page.locator('.bw-row.user .bw-bubble').last()).toContainText('return policy');
});
