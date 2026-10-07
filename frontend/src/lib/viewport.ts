/**
 * KAN-1826: how much of the layout viewport the soft keyboard covers, from `visualViewport`.
 *
 * On iOS the keyboard shrinks the *visual* viewport and leaves the layout viewport (and so
 * `position: fixed; bottom: 0`) where it was, behind the keyboard. Chrome on Android does the same
 * by default now. The covered strip at the bottom is
 * `layoutHeight - visualViewport.height - visualViewport.offsetTop`, and `offsetTop` matters
 * because iOS scrolls the visual viewport inside the layout one to keep the focused field in view.
 *
 * The arithmetic is pure and tested in node. {@link watchViewport} is the only part that touches a
 * browser, takes its window as an argument, and does nothing where `visualViewport` is missing: the
 * inset is then `0`, the toolbar sits at the bottom of the layout viewport, and the platform's own
 * resize (older browsers shrink the layout viewport instead) does the right thing by itself.
 *
 * Nothing here imports CodeMirror.
 */

/** The three numbers of `VisualViewport` this module reads. */
export interface ViewportMetrics {
  height: number
  offsetTop: number
  scale: number
}

/**
 * Below this a change is browser chrome (a collapsing URL bar is about 50-100px), not a keyboard.
 * Real soft keyboards are 200px and up even in landscape on a phone.
 */
export const KEYBOARD_MIN_INSET = 120

/**
 * The strip at the bottom of the layout viewport that something covers, in whole pixels.
 *
 * A pinch zoom also shrinks the visual viewport, and is not a keyboard, so any scale other than 1
 * reads as `0`. A missing `visualViewport` is `0` too.
 */
export function keyboardInset(layoutHeight: number, visual: ViewportMetrics | null): number {
  if (visual === null || Math.abs(visual.scale - 1) > 0.01) {
    return 0
  }
  return Math.max(0, Math.round(layoutHeight - visual.height - visual.offsetTop))
}

/** Whether an inset is a keyboard rather than browser chrome. */
export function keyboardOpen(inset: number): boolean {
  return inset >= KEYBOARD_MIN_INSET
}

/** The visual viewport's metrics, or `null` where the browser has none. */
export function readViewport(win: Window = window): ViewportMetrics | null {
  const visual = win.visualViewport
  if (visual === null || visual === undefined) {
    return null
  }
  return { height: visual.height, offsetTop: visual.offsetTop, scale: visual.scale }
}

/**
 * Call `onInset` with the current inset now and again whenever it changes, on the visual viewport's
 * `resize` and `scroll`. Returns the unsubscribe.
 */
export function watchViewport(
  onInset: (inset: number) => void,
  win: Window = window,
): () => void {
  let last: number | null = null
  const report = (): void => {
    const next = keyboardInset(win.innerHeight, readViewport(win))
    if (next !== last) {
      last = next
      onInset(next)
    }
  }
  report()
  const visual = win.visualViewport
  if (visual === null || visual === undefined) {
    return () => undefined
  }
  visual.addEventListener('resize', report)
  visual.addEventListener('scroll', report)
  return () => {
    visual.removeEventListener('resize', report)
    visual.removeEventListener('scroll', report)
  }
}
