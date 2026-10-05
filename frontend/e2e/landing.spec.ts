/**
 * SLICES.md §V3 end-to-end bullet 5, as the landing page stands after KAN-1822: an unauthenticated
 * visitor sees one promise, a working GitHub sign-in button, an interactive phone demo and three
 * short tiles. There is no paste form (KAN-1791) and no identity section any more.
 *
 * No `authedPage` fixture and no `login()` here: this is the one test file that must *not*
 * authenticate, and it never touches a cookie or `sessionStorage`.
 */
import { expect, test } from './fixtures'

test('an unauthenticated visitor sees the landing state with GitHub sign-in and no paste form', async ({
  page,
}) => {
  await page.goto('/')

  await expect(page.locator('.shell')).toHaveClass(/unauthenticated/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Markdown for humans and agents.')
  await expect(page.getByTestId('github-signin')).toBeVisible()
  await expect(page.getByTestId('paste-form')).toHaveCount(0)
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
  // The authenticated regions must be absent, not merely hidden.
  await expect(page.locator('.sidebar')).toHaveCount(0)
  await expect(page.getByRole('heading', { level: 2 })).toHaveText([
    'Agent ready',
    'Linked notes',
    'Knowledge graph',
  ])
})

test('the phone demo switches between Read and Edit', async ({ page }) => {
  await page.goto('/')
  const demo = page.getByRole('group', { name: 'Note preview demo' })
  await expect(demo).toBeVisible()

  const read = demo.getByRole('button', { name: 'Read', exact: true })
  const edit = demo.getByRole('button', { name: 'Edit', exact: true })
  await expect(read).toHaveAttribute('aria-pressed', 'true')
  await expect(demo.getByTestId('phone-read')).toBeVisible()
  await expect(demo.getByTestId('phone-edit')).toHaveCount(0)

  await edit.click()
  await expect(edit).toHaveAttribute('aria-pressed', 'true')
  await expect(demo.getByTestId('phone-edit')).toBeVisible()
  await expect(demo.getByTestId('phone-read')).toHaveCount(0)

  // Keyboard: focus Read and press Enter.
  await read.focus()
  await page.keyboard.press('Enter')
  await expect(read).toHaveAttribute('aria-pressed', 'true')

  await demo.getByRole('button', { name: 'Graph', exact: true }).click()
  await expect(demo.getByTestId('phone-graph')).toBeVisible()
})

test('sign-in is visible without scrolling on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  const box = (await page.getByTestId('github-signin').boundingBox())!
  expect(box.y).toBeGreaterThanOrEqual(0)
  expect(box.y + box.height).toBeLessThanOrEqual(844)
})

for (const width of [320, 390, 600, 840, 1440]) {
  test(`the landing page does not scroll sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/')
    await expect(page.getByTestId('phone-demo')).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  })
}
