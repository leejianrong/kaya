<script lang="ts">
  import EditorPane from './components/EditorPane.svelte'
  import Sidebar from './components/Sidebar.svelte'
  import { ApiError } from './lib/api'
  import { credentialState } from './lib/auth'
  import { getNote, listNotes } from './lib/notes'
  import { currentRoute, interceptClick, onNavigate, type Route } from './lib/router'
  import type { Note } from './lib/types'

  /**
   * The shell: three regions, the route, and the two reads the regions need. Nothing else.
   *
   * What this file is *not* allowed to become is the place the app's logic accumulates. Three cards
   * run after this one and each replaces exactly one file — KAN-553 `EditorPane.svelte`, KAN-554
   * `Sidebar.svelte`, KAN-555 the landing state — which only works if the regions own their own
   * behaviour and this file owns the layout and the route.
   *
   * There is deliberately no build-status table here. KAN-723: the one this replaced hard-coded
   * `done: false` against `kaya-client` and `kaya-cli`, both of which shipped in V2a/V2b, and the
   * false claim reached the built bundle. It was a second copy of CLAUDE.md's package table and it
   * drifted twice inside one epic, so the fix was to delete the list rather than correct the flags.
   */

  let route: Route = $state(currentRoute())
  let notes: Note[] = $state([])
  let note: Note | null = $state(null)
  let listing = $state(true)
  let failure: string | null = $state(null)

  const authed = credentialState() === 'set'

  $effect(() => onNavigate((next) => (route = next)))

  $effect(() => {
    if (!authed) {
      listing = false
      return
    }
    const abort = new AbortController()
    listNotes({ signal: abort.signal })
      .then((found) => (notes = found))
      .catch((error: unknown) => (failure = describe(error)))
      .finally(() => (listing = false))
    return () => abort.abort()
  })

  $effect(() => {
    // Reads `route` so it re-runs on navigation, and nothing else — the list above must not refetch
    // every time you open a note.
    const opened = route.name === 'note' ? route.ref : null
    if (opened === null || !authed) {
      note = null
      failure = null
      return
    }
    const abort = new AbortController()
    failure = null
    getNote(opened, { signal: abort.signal })
      .then((found) => (note = found))
      .catch((error: unknown) => {
        note = null
        failure = describe(error)
      })
    return () => abort.abort()
  })

  /**
   * A refusal as one line of prose.
   *
   * The API's own `message` is used verbatim — it is written for a human and the backend never puts
   * a credential in one. Nothing here reads the request, the headers or the credential, so there is
   * no path by which the token reaches this string and therefore the DOM.
   */
  function describe(error: unknown): string {
    if (error instanceof ApiError) {
      return error.message
    }
    if (error instanceof Error && error.name === 'AbortError') {
      return ''
    }
    return error instanceof Error ? error.message : 'Something went wrong.'
  }
</script>

<div class="shell">
  <header class="topbar">
    <a class="brand" href="/" onclick={(event) => interceptClick(event, '/')}>kaya</a>
    <span class="tagline">markdown notes, API-first</span>
    <!--
      `set` or `not set`, and never a fragment. `kaya config show` is the reference: pandan printed
      `set (…c_DE)` and those four characters are a contiguous piece of a live credential in a
      surface documented as safe to share. A browser is worse — a screenshot is one keystroke away.
    -->
    <span class="credential" data-testid="credential-state">token {credentialState()}</span>
  </header>

  {#if authed}
    <Sidebar {notes} {route} loading={listing} />
    <main>
      {#if route.name === 'unknown'}
        <p class="notice">
          Nothing lives at <code>{route.path}</code>. Pick a note from the sidebar.
        </p>
      {:else}
        <EditorPane {note} error={failure === '' ? null : failure} />
      {/if}
    </main>
  {:else}
    <!-- One honest line, not a landing page. KAN-555 owns the landing state and the PAT paste form,
         and it needs `lib/auth.ts`'s seam and nothing from this file. -->
    <main class="unauthenticated">
      <p class="notice">
        No pandan token in this tab. kaya mints no credentials of its own (ADR 0002) — sign-in lands
        in KAN-555.
      </p>
    </main>
  {/if}
</div>

<style>
  .shell {
    display: grid;
    grid-template-areas: 'topbar topbar' 'sidebar main';
    grid-template-columns: minmax(12rem, 18rem) 1fr;
    grid-template-rows: auto 1fr;
    height: 100dvh;
  }

  .shell:has(.unauthenticated) {
    grid-template-areas: 'topbar' 'main';
    grid-template-columns: 1fr;
  }

  .topbar {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    grid-area: topbar;
    padding: 0.85rem 1.25rem;
    border-bottom: 1px solid var(--edge);
  }

  .brand {
    color: inherit;
    font-size: 1.05rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    text-decoration: none;
  }

  .tagline {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .credential {
    margin-left: auto;
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.75rem;
  }

  .shell > :global(.sidebar) {
    grid-area: sidebar;
  }

  main {
    grid-area: main;
    min-width: 0;
    overflow-y: auto;
  }

  .unauthenticated {
    padding: 3rem 1.5rem;
  }

  .notice {
    max-width: 34rem;
    margin: 0;
    padding: 1.5rem;
    color: var(--muted);
  }
</style>
