import { test } from '@e2e-dev/web';
import { expect } from 'e2e';
test('login page renders', async ({ app, screen }) => {
  await app.open('/login');
  await expect(screen.getByRole('button', 'Войти')).toBeVisible();
  await expect(screen).toHaveScreenshot('login.png');
});
test('unauthenticated root redirects to login', async ({ app, browser }) => {
  await app.open('/');
  await expect(browser).toHaveURL(/\/login/);
});
test('login EN differs from RU baseline', async ({ app, screen }) => {
  await app.open('/login');
  await screen.getByRole('button', 'EN').click();
  await expect(screen).toHaveScreenshot('login.png');
});
