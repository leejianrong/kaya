/**
 * KAN-1823: the logo, against the real app image.
 *
 * Two things only a real stack can say: the favicon/manifest URLs come back as themselves with the
 * right content type (the SPA fallback answers an unknown path with `index.html` and a 200, so a
 * missing or mis-routed icon would not fail loudly), and the mark sits in the header without
 * pushing the page sideways at the widths the shell has layouts for.
 */
import { expect, test } from './fixtures'

const ASSETS: [string, string][] = [
  ['/favicon.svg', 'image/svg+xml'],
  ['/favicon.ico', 'image/vnd.microsoft.icon'],
  ['/apple-touch-icon.png', 'image/png'],
  ['/icon-192.png', 'image/png'],
  ['/icon-512.png', 'image/png'],
  ['/icon-maskable-512.png', 'image/png'],
  ['/og.png', 'image/png'],
  ['/manifest.webmanifest', 'application/manifest+json'],
]

for (const [path, type] of ASSETS) {
  test(`${path} is served as ${type}, not swallowed by the SPA fallback`, async ({ request }) => {
    const response = await request.get(path)
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type'].split(';')[0]).toBe(type)
    expect((await response.body()).subarray(0, 15).toString().toLowerCase()).not.toContain(
      '<!doctype html',
    )
  })
}

test('the manifest names kaya and every icon in it resolves', async ({ request }) => {
  const manifest = await (await request.get('/manifest.webmanifest')).json()
  expect(manifest.name).toBe('kaya')
  for (const icon of manifest.icons as { src: string }[]) {
    expect((await request.get(icon.src)).status()).toBe(200)
  }
})

for (const width of [320, 390, 600, 840, 1440]) {
  test(`signed out, the header mark is visible and nothing scrolls sideways at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/')
    await expect(page.getByTestId('github-signin')).toBeVisible()

    await expect(page.locator('.topbar .brand [data-testid="logo"]')).toBeVisible()
    await expect(page.locator('.topbar .brand')).toContainText('kaya')
    // The landing's own, larger mark above the heading.
    await expect(page.locator('.hero [data-testid="logo"]')).toBeVisible()

    const { scrollWidth, innerWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
  })
}

for (const width of [390, 1440]) {
  test(`signed in, the header mark is visible and nothing scrolls sideways at ${width}px`, async ({
    authedPage: page,
  }) => {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/')
    await expect(page.locator('.topbar .brand [data-testid="logo"]')).toBeVisible()
    await expect(page.locator('.topbar .brand')).toContainText('kaya')

    const { scrollWidth, innerWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
  })
}
