const { test, expect } = require('@playwright/test');

test('signed out by default, sign-in link visible in the nav', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#bookly-auth-slot #auth-signin')).toBeVisible();
});

test('unknown email shows an error and keeps the modal open', async ({ page }) => {
  await page.goto('/');
  await page.click('#auth-signin');
  await expect(page.locator('#bookly-auth-modal')).toHaveClass(/open/);

  await page.fill('#auth-email', 'nobody@example.com');
  await page.fill('#auth-password', 'whatever');
  await page.click('#auth-submit');

  await expect(page.locator('#auth-error')).toHaveClass(/show/);
  await expect(page.locator('#auth-error')).toContainText('No account found');
  await expect(page.locator('#bookly-auth-modal')).toHaveClass(/open/); // didn't close on failure
});

test('signing in with any password for a known account updates the nav and persists on reload', async ({ page }) => {
  await page.goto('/');
  await page.click('#auth-signin');
  await page.fill('#auth-email', 'alice@example.com');
  await page.fill('#auth-password', 'literally-anything');
  await page.click('#auth-submit');

  await expect(page.locator('#bookly-auth-modal')).not.toHaveClass(/open/);
  await expect(page.locator('#bookly-auth-slot')).toContainText('Alice Nguyen');

  // the login cookie should survive a full page reload, not just the SPA-ish state
  await page.reload();
  await expect(page.locator('#bookly-auth-slot')).toContainText('Alice Nguyen');
});

test('signing out reverts the nav to signed-out state', async ({ page }) => {
  await page.goto('/');
  await page.click('#auth-signin');
  await page.fill('#auth-email', 'bob@example.com');
  await page.fill('#auth-password', 'x');
  await page.click('#auth-submit');
  await expect(page.locator('#bookly-auth-slot')).toContainText('Bob Ramirez');

  await page.click('#auth-signout');
  await expect(page.locator('#bookly-auth-slot #auth-signin')).toBeVisible();

  await page.reload();
  await expect(page.locator('#bookly-auth-slot #auth-signin')).toBeVisible(); // cookie actually cleared, not just the DOM
});

test('the chat widget greets a signed-in customer by name', async ({ page }) => {
  await page.goto('/');
  await page.click('#auth-signin');
  await page.fill('#auth-email', 'alice@example.com');
  await page.fill('#auth-password', 'x');
  await page.click('#auth-submit');
  await expect(page.locator('#bookly-auth-slot')).toContainText('Alice Nguyen');

  await page.click('#bw-launcher');
  await expect(page.locator('.bw-row.agent .bw-bubble').first()).toContainText('Alice');
});

test('login is available on the contact page too, same as the widget', async ({ page }) => {
  await page.goto('/contact');
  await expect(page.locator('#bookly-auth-slot #auth-signin')).toBeVisible();
  await page.click('#auth-signin');
  await page.fill('#auth-email', 'alice@example.com');
  await page.fill('#auth-password', 'x');
  await page.click('#auth-submit');
  await expect(page.locator('#bookly-auth-slot')).toContainText('Alice Nguyen');
});
