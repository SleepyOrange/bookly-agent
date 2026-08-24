const { test, expect } = require('@playwright/test');

test('launcher opens and closes the chat panel', async ({ page }) => {
  await page.goto('/');
  const widget = page.locator('#bookly-widget');
  const panel = page.locator('.bw-panel');

  await expect(widget).not.toHaveClass(/open/);
  await expect(panel).toHaveAttribute('aria-hidden', 'true');

  await page.click('#bw-launcher');
  await expect(widget).toHaveClass(/open/);
  await expect(panel).toHaveAttribute('aria-hidden', 'false');
  await expect(page.locator('#bw-log .bw-row')).toHaveCount(1); // the initial greeting

  await page.click('#bw-close');
  await expect(widget).not.toHaveClass(/open/);
});

test('End session clears the chat log back to a fresh greeting', async ({ page }) => {
  await page.goto('/');
  await page.click('#bw-launcher');
  await page.fill('#bw-input', 'what would you recommend?');
  await page.click('#bw-form button[type=submit]');
  await expect(page.locator('.bw-product-card')).toHaveCount(1, { timeout: 10000 });
  await expect(page.locator('#bw-log .bw-row').first()).toBeVisible();
  const rowCountBeforeReset = await page.locator('#bw-log .bw-row').count();
  expect(rowCountBeforeReset).toBeGreaterThan(1); // greeting + user message + reply + card

  await page.click('#bw-reset');

  // back to just the one fresh greeting bubble, and the stale product card is gone too
  await expect(page.locator('#bw-log .bw-row')).toHaveCount(1);
  await expect(page.locator('.bw-product-card')).toHaveCount(0);
  await expect(page.locator('#bw-status-text')).toHaveText('New conversation started');
});

test('End session actually starts a new server-side session, not just a visual clear', async ({ page }) => {
  await page.goto('/');
  await page.click('#bw-launcher');
  await page.fill('#bw-input', 'whats your shipping policy');
  await page.click('#bw-form button[type=submit]');
  const firstSessionId = await page.evaluate(() => sessionStorage.getItem('bookly_session_id'));
  expect(firstSessionId).toBeTruthy();

  await page.click('#bw-reset');
  expect(await page.evaluate(() => sessionStorage.getItem('bookly_session_id'))).toBeNull();

  await page.fill('#bw-input', 'whats your shipping policy');
  await page.click('#bw-form button[type=submit]');
  await expect(page.locator('.bw-row.agent .bw-bubble').last()).toContainText('£4.99', { timeout: 10000 });
  const secondSessionId = await page.evaluate(() => sessionStorage.getItem('bookly_session_id'));
  expect(secondSessionId).toBeTruthy();
  expect(secondSessionId).not.toBe(firstSessionId);
});

test('escape key closes the open panel', async ({ page }) => {
  await page.goto('/');
  await page.click('#bw-launcher');
  await expect(page.locator('#bookly-widget')).toHaveClass(/open/);
  await page.keyboard.press('Escape');
  await expect(page.locator('#bookly-widget')).not.toHaveClass(/open/);
});

test('sending a message shows the user bubble and the reply', async ({ page }) => {
  await page.goto('/');
  await page.click('#bw-launcher');
  await page.fill('#bw-input', 'whats your shipping policy');
  await page.click('#bw-form button[type=submit]');

  await expect(page.locator('.bw-row.user .bw-bubble')).toHaveText('whats your shipping policy');
  const agentBubbles = page.locator('.bw-row.agent .bw-bubble');
  await expect(agentBubbles.last()).toContainText('£4.99', { timeout: 10000 });
});

test('suggestion chip sends its message without typing', async ({ page }) => {
  await page.goto('/');
  await page.click('#bw-launcher');
  await page.click('.bw-suggestions button:has-text("return policy")');
  await expect(page.locator('.bw-row.user .bw-bubble').last()).toContainText('return policy');
  await expect(page.locator('.bw-row.agent .bw-bubble').last()).toContainText('30 days', { timeout: 10000 });
});

test('footer deep-link opens the widget and sends the question automatically', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#bookly-widget')).not.toHaveClass(/open/);

  await page.click('footer button:has-text("Order status")');

  await expect(page.locator('#bookly-widget')).toHaveClass(/open/);
  await expect(page.locator('.bw-row.user .bw-bubble').last()).toHaveText('Where is my order?');
  await expect(page.locator('.bw-row.agent .bw-bubble').last()).toContainText('order ID', { timeout: 10000 });
});

test('a reply naming a real catalog title shows its product card, with cover art', async ({ page }) => {
  await page.goto('/');
  await page.click('#bw-launcher');
  await page.fill('#bw-input', 'what would you recommend?');
  await page.click('#bw-form button[type=submit]');

  await expect(page.locator('.bw-row.agent .bw-bubble').last()).toContainText('Project Hail Mary', { timeout: 10000 });

  const card = page.locator('.bw-product-card');
  await expect(card).toBeVisible();
  await expect(card.locator('.bw-product-title')).toHaveText('Project Hail Mary');
  await expect(card.locator('.bw-product-author')).toHaveText('Andy Weir');
  await expect(card.locator('img')).toHaveAttribute('src', '/static/covers/project-hail-mary.jpg');
});

test('a reply naming no catalog title shows no product card', async ({ page }) => {
  await page.goto('/');
  await page.click('#bw-launcher');
  await page.fill('#bw-input', 'whats your shipping policy');
  await page.click('#bw-form button[type=submit]');

  await expect(page.locator('.bw-row.agent .bw-bubble').last()).toContainText('£4.99', { timeout: 10000 });
  await expect(page.locator('.bw-product-card')).toHaveCount(0);
});

test('bold and bullet markdown render as real formatting, not literal ** and -', async ({ page }) => {
  await page.goto('/');
  await page.click('#bw-launcher');
  await page.fill('#bw-input', 'markdown test please');
  await page.click('#bw-form button[type=submit]');

  const bubble = page.locator('.bw-row.agent .bw-bubble').last();
  await expect(bubble).toContainText('Order status:', { timeout: 10000 });

  await expect(bubble.locator('strong')).toHaveText('Order status:');
  await expect(bubble).toContainText('•'); // bullet marker, not a literal "-"
  const rawText = await bubble.textContent();
  expect(rawText).not.toContain('**');
  expect(rawText.trim().startsWith('-')).toBe(false);
});

test('a reply that looks like HTML renders as inert text, not executed markup', async ({ page }) => {
  let dialogFired = false;
  page.on('dialog', () => { dialogFired = true; });

  await page.goto('/');
  await page.click('#bw-launcher');
  await page.fill('#bw-input', 'this has html in it');
  await page.click('#bw-form button[type=submit]');

  const bubble = page.locator('.bw-row.agent .bw-bubble').last();
  await expect(bubble).toContainText('was not found.', { timeout: 10000 });

  // the <img onerror=...> text is shown as literal characters, not parsed
  // into a real <img> element that would fire onerror
  await expect(bubble.locator('img')).toHaveCount(0);
  expect(dialogFired).toBe(false);
});

test('a product card only stays for the latest reply, not the whole conversation', async ({ page }) => {
  await page.goto('/');
  await page.click('#bw-launcher');

  await page.fill('#bw-input', 'what would you recommend?');
  await page.click('#bw-form button[type=submit]');
  await expect(page.locator('.bw-product-card')).toHaveCount(1, { timeout: 10000 });

  await page.fill('#bw-input', 'whats your shipping policy');
  await page.click('#bw-form button[type=submit]');
  await expect(page.locator('.bw-row.agent .bw-bubble').last()).toContainText('£4.99', { timeout: 10000 });

  // the earlier card is gone, not accumulated -- the chat log still shows
  // both text replies, just not a stale card from an earlier turn
  await expect(page.locator('.bw-product-card')).toHaveCount(0);
  await expect(page.locator('.bw-row.agent .bw-bubble')).toHaveCount(3); // greeting + 2 replies
});

test('nav "Concierge" link opens the widget without sending a message', async ({ page }) => {
  await page.goto('/');
  await page.click('nav a:has-text("Concierge")');
  await expect(page.locator('#bookly-widget')).toHaveClass(/open/);
  await expect(page.locator('.bw-row.user')).toHaveCount(0);
});

test('session id persists across turns within the same page load', async ({ page }) => {
  const seenSessionIds = [];
  page.on('response', async (resp) => {
    if (resp.url().endsWith('/api/chat')) {
      const body = await resp.json().catch(() => null);
      if (body?.session_id) seenSessionIds.push(body.session_id);
    }
  });

  await page.goto('/');
  await page.click('#bw-launcher');
  await page.fill('#bw-input', 'first message');
  await page.click('#bw-form button[type=submit]');
  await page.waitForTimeout(500);
  await page.fill('#bw-input', 'second message');
  await page.click('#bw-form button[type=submit]');
  await page.waitForTimeout(500);

  expect(seenSessionIds.length).toBe(2);
  expect(seenSessionIds[0]).toBe(seenSessionIds[1]);
});

test('the greeting nudge appears and can be dismissed', async ({ page }) => {
  await page.goto('/');
  const nudge = page.locator('#bw-nudge');
  await expect(nudge).toHaveClass(/show/, { timeout: 5000 });

  await page.click('#bw-nudge-close');
  await expect(nudge).not.toHaveClass(/show/);
  await expect(page.locator('#bookly-widget')).not.toHaveClass(/open/); // dismissing shouldn't open the panel
});
