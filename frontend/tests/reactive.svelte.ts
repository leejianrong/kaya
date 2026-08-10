/**
 * A reactive box, so a test can change a prop and watch a component react.
 *
 * `mount(Component, { props })` reads props lazily, so a getter over a `$state` here makes an
 * ordinary object behave like a reactive prop. Without this, every component test is a single
 * render, and "the editor mounts once *per note* and tears down cleanly on navigation"
 * (SLICES §V3) is unassertable — which is the one thing KAN-553 most needs to be able to check.
 *
 * `.svelte.ts` rather than `.ts` because runes outside a component need the compiler to see the
 * file.
 */
export interface Box<T> {
  value: T
}

export function box<T>(initial: T): Box<T> {
  let value = $state(initial)
  return {
    get value() {
      return value
    },
    set value(next: T) {
      value = next
    },
  }
}
