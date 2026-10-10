/**
 * KAY-141: the Tokens page's preset selector and chips, in a real browser at the three widths the
 * shell cares about (compact 390, medium 720, expanded 1440) in both colour schemes.
 *
 * Each width asserts the page never scrolls sideways. Set `KAYA_SHOT_DIR` to also write a PNG per
 * width and scheme (how the PR's screenshots were taken); unset, nothing is written.
 */
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

import { expect, test } from './fixtures'

const WIDTHS = [
  { name: '1440', width: 1440, height: 900 },
  { name: '720', width: 720, height: 900 },
  { name: '390', width: 390, height: 844 },
] as const

const PRESETS = [
  { scope: 'write', label: 'Full access' },
  { scope: 'write-no-delete', label: 'No delete' },
  { scope: 'read', label: 'Read only' },
] as const

test('mint one token per preset and see each as a chip, at every width and scheme', async ({
  authedPage: page,
}) => {
  await page.goto('/tokens')
  await expect(page.getByTestId('create-form')).toBeVisible()

  const labels = await page.locator('#token-scope option').allTextContents()
  expect(labels.map((label) => label.trim())).toEqual(PRESETS.map((preset) => preset.label))

  // The app may have minted its own automatic token for this session, so match ours by name.
  const mine = page.locator('[data-testid="token-list"] li', { hasText: 'preset ' })

  for (const [made, preset] of PRESETS.entries()) {
    await page.locator('#token-name').fill(`preset ${preset.scope} long name for wrapping`)
    await page.locator('#token-scope').selectOption(preset.scope)
    await expect(page.getByTestId('preset-help')).not.toHaveText('')
    await page.getByRole('button', { name: 'Create token' }).click()
    // `created-secret` stays up from the previous token, so wait on the list growing instead.
    await expect(mine).toHaveCount(made + 1)
  }

  await expect(mine).toHaveCount(3)
  for (const [index, preset] of PRESETS.entries()) {
    await expect(mine.nth(index).getByTestId('preset-chip')).toHaveText(preset.label)
  }

  const shots = process.env.KAYA_SHOT_DIR
  if (shots) {
    mkdirSync(shots, { recursive: true })
  }
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme })
    for (const size of WIDTHS) {
      await page.setViewportSize({ width: size.width, height: size.height })
      const { scrollWidth, innerWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }))
      expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
      if (shots) {
        await page.screenshot({ path: join(shots, `tokens-${size.name}-${scheme}.png`) })
      }
    }
  }

  // Leave nothing behind: revoke every token this test minted.
  while ((await mine.count()) > 0) {
    await mine.first().getByRole('button', { name: 'Revoke' }).click()
    await page.waitForTimeout(150)
  }
})
