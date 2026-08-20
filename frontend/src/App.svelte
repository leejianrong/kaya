<script lang="ts">
  import EditorPane from './components/EditorPane.svelte'
  import Landing from './components/Landing.svelte'
  import PreviewPane from './components/PreviewPane.svelte'
  import Sidebar from './components/Sidebar.svelte'
  import { ApiError } from './lib/api'
  import { clearToken, credentialState } from './lib/auth'
  import { getNote, listNotes } from './lib/notes'
  import { currentRoute, interceptClick, onNavigate, type Route } from './lib/router'
  import type { Note } from './lib/types'

  /**
   * The shell: three regions, the route, and the two reads the regions need. Nothing else.
   *
   * What this file is *not* allowed to become is the place the app's logic accumulates. Three cards
   * run after KAN-552 and each replaces exactly one file — KAN-553 `EditorPane.svelte`, KAN-554
   * `Sidebar.svelte`, KAN-555 `Landing.svelte` — which only works if the regions own their own
   * behaviour and this file owns the layout and the route.
   *
   * KAN-555 kept to that with one exception it had to make here: the *credential lifecycle*. The
   * landing state cannot own it, because acquiring a credential changes which region renders, and
   * losing one is discovered by a `401` on a request the landing state never made. So `authed`,
   * `accept()` and `discard()` live in this file, and `Landing.svelte` is still the only thing that
   * ever holds a token — it calls `setToken` and then a callback, and hands nothing back.
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

  /**
   * KAN-559: the **committed** search term, `''` for "list everything". Owned here, not in
   * `Sidebar`, because it drives the fetch below and `Sidebar` is presentation over the notes it is
   * handed — the same split `notes`/`listing` already make. `Sidebar`'s own `draft` state is the
   * text not yet submitted; this is what the last submit actually asked for.
   */
  let query = $state('')

  /** `Sidebar`'s `onsearch`: commit the trimmed term, which is what re-runs the fetch below. */
  function search(term: string): void {
    query = term
  }

  /**
   * Whether this tab has a credential — **reactive**, and KAN-555 is why.
   *
   * It was a `const` read once at mount, which was honest while there was no way to acquire a
   * credential without reloading. Now there is: the paste form calls `accept()` below and the
   * effects re-run off this rune, so a paste reaches the note list without a reload. It also runs
   * backwards, which is the half that matters more — `discard()` puts the app back in the landing
   * state the moment the API says the credential is no good.
   */
  let authed = $state(credentialState() === 'set')

  /** The API's own words for why the last credential was refused. Shown by the landing state. */
  let rejected: string | null = $state(null)

  /**
   * Whether the preview is on the screen. KAN-554.
   *
   * **`EditorPane` is deliberately outside the `{#if}` this controls, and that placement is the whole
   * of the toggle's correctness.** Inside it, the editor would be a *different component instance*
   * every time the preview appeared or disappeared — `$effect` cleanup, `view.destroy()`, a fresh
   * `EditorState` — so toggling the preview would throw away your unsaved edit and your undo history
   * on a command that is about the pane beside it. `tests/preview.test.ts` types, toggles twice and
   * asserts the same `EditorView` object is still there holding the same text.
   */
  let previewing = $state(true)

  /**
   * The document the editor is showing right now, out of `EditorPane`'s `ondocument` seam.
   *
   * **A rune of its own, deliberately not written back into `note`.** That separation is what keeps a
   * keystroke from reaching the `$effect` that owns the `EditorView`: `note` is the editor's *input*,
   * and only the fetch below and `discard()` ever assign it, so the identity guard and the
   * `appliedBody` guard in `EditorPane.svelte` never see a content change they have to reason about.
   * Writing the live document into `note.body` here is the plausible-looking mistake — it would not
   * remount (`needsRemount` takes no body parameter, and it must keep taking none) but it would put a
   * per-keystroke round trip through this file between CM6 and itself, with only the echo guard
   * standing between that and PLAN §Open risks' update loop.
   *
   * `publishDocument` is a **named function declaration** rather than an inline arrow, so its identity
   * is stable across every update this component makes. `EditorPane` reads the prop through `untrack`
   * and therefore does not depend on that; handing a component a fresh closure per keystroke is still
   * a bad habit whether or not the callee defends against it.
   */
  let liveDocument = $state('')

  function publishDocument(document: string): void {
    liveDocument = document
  }

  /**
   * `set` or `not set`, and this file does not get to spell either word.
   *
   * The value comes from the seam, which is the only thing allowed to describe a credential to a
   * person — never a prefix, a suffix, a length or a mask (`lib/auth.ts`, and pandan's
   * `set (…c_DE)`). The `void authed` is what makes it re-read: the credential lives in
   * `sessionStorage`, which is not reactive, so a header derived from the seam alone would still
   * say `not set` after a successful paste.
   */
  const credential = $derived.by(() => {
    void authed
    return credentialState()
  })

  $effect(() => onNavigate((next) => (route = next)))

  $effect(() => {
    if (!authed) {
      listing = false
      return
    }
    listing = true
    const abort = new AbortController()
    // `query` is read directly, which is what makes this effect re-run on every committed search —
    // an empty string sends no `q` at all (backend/app/api/search.py's own rule: a search box that
    // has been cleared must send no `q`, never `q=`), so clearing the box is indistinguishable on
    // the wire from a `note list` that never searched.
    const term = query.trim()
    listNotes({ q: term === '' ? undefined : term, signal: abort.signal })
      .then((found) => (notes = found))
      .catch(absorb)
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
        absorb(error)
      })
    return () => abort.abort()
  })

  /**
   * A failure, sorted into "the credential is no good" and everything else.
   *
   * A `401` is the only status this app can *act* on, and the action is to stop pretending it has a
   * credential. Keyed on the **status** rather than on the error code, for the reason
   * `kaya-cli/failures.py` gives: the backend's code vocabulary grows without this client's
   * knowledge, and `authentication_required` / `invalid_token` are already two codes for one
   * meaning.
   */
  function absorb(error: unknown): void {
    if (error instanceof ApiError && error.isUnauthenticated) {
      discard(error.message)
      return
    }
    failure = describe(error)
  }

  /**
   * The token is stored (the landing state did it); proceed.
   *
   * The `authed` write is what re-runs the effects above, so the note list arrives without a
   * reload. Nothing here touches the credential itself — this function never sees it.
   */
  function accept(): void {
    rejected = null
    failure = null
    authed = true
  }

  /**
   * Forget the credential and go back to the landing state.
   *
   * Reached two ways, and both are required: the API refusing it with a `401`, and the person
   * clicking **Clear token**. The second exists because the first only covers one shape of being
   * stuck — a valid token for the wrong account, or a `503` from a sleeping pandan, leaves a user
   * looking at a failure with no way to change credentials. A state you can only leave through
   * devtools is a bug, so the way out is a button rather than an instruction.
   *
   * `reason` is the API's message or `null` for a deliberate clear; there is nothing to explain
   * when the user did it on purpose.
   */
  function discard(reason: string | null): void {
    clearToken()
    notes = []
    note = null
    failure = null
    query = ''
    rejected = reason
    authed = false
  }

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

<div class="shell" class:unauthenticated={!authed}>
  <header class="topbar">
    <a class="brand" href="/" onclick={(event) => interceptClick(event, '/')}>kaya</a>
    <span class="tagline">markdown notes, API-first</span>
    {#if authed}
      <button
        class="toggle"
        class:on={previewing}
        aria-pressed={previewing}
        onclick={() => (previewing = !previewing)}
        data-testid="toggle-preview"
      >
        Preview
      </button>
    {/if}
    <!--
      `set` or `not set`, and never a fragment. `kaya config show` is the reference: pandan printed
      `set (…c_DE)` and those four characters are a contiguous piece of a live credential in a
      surface documented as safe to share. A browser is worse — a screenshot is one keystroke away.
    -->
    <span class="credential" data-testid="credential-state">token {credential}</span>
    {#if authed}
      <!-- The way out, always available while a credential is held. See `discard()`. -->
      <button class="clear" onclick={() => discard(null)} data-testid="clear-token">
        Clear token
      </button>
    {/if}
  </header>

  {#if authed}
    <Sidebar {notes} {route} loading={listing} {query} onsearch={search} />
    <main>
      {#if route.name === 'unknown'}
        <p class="notice">
          Nothing lives at <code>{route.path}</code>. Pick a note from the sidebar.
        </p>
      {:else}
        <!--
          The editor and its preview, side by side. `EditorPane` is **outside** the `{#if}` below on
          purpose (see `previewing`), and the preview is its **sibling** rather than anything nested in
          it — PLAN §S9: Svelte never renders inside CM6's subtree. The document travels from one to
          the other through `ondocument` and `liveDocument`, which is a published prop rather than a
          reach into the editor's internals; see `liveDocument` on why it is not `note.body`.
        -->
        <div class="split" class:solo={!previewing}>
          <EditorPane
            {note}
            error={failure === '' ? null : failure}
            ondocument={publishDocument}
          />
          {#if previewing}
            <PreviewPane {note} source={liveDocument} />
          {/if}
        </div>
      {/if}
    </main>
  {:else}
    <!-- KAN-555's landing state, which owns everything about the paste including the credential
         itself: this file hands it `rejected` and gets back a callback, and never sees a token. -->
    <Landing {rejected} onaccept={accept} />
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

  /* No sidebar without a credential: there is nothing to list, and an empty rail beside a
     sign-in page reads as a broken app rather than as a locked one. */
  .shell.unauthenticated {
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

  /* Same door as `.sidebar` above: the child component owns its own element, so the parent places
     it by class rather than by wrapping it in a div that exists only to be positioned. */
  .shell > :global(.landing) {
    grid-area: main;
  }

  main {
    grid-area: main;
    min-width: 0;
    overflow-y: auto;
  }

  .split {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    height: 100%;
  }

  /* `minmax(0, …)` on both tracks, not `1fr 1fr`: a `1fr` track has an `auto` minimum, so one long
     unbroken line in a fenced code block would widen the editor and push the preview off the pane. */
  .split.solo {
    grid-template-columns: minmax(0, 1fr);
  }

  /* Under about a laptop's width two columns are two cramped columns. Stacking keeps both usable, and
     the editor stays first so the thing you type in is the thing you see. */
  @media (max-width: 60rem) {
    .split {
      grid-template-columns: minmax(0, 1fr);
      height: auto;
    }
  }

  .toggle {
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--edge);
    border-radius: 0.3rem;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: 0.75rem;
  }

  .toggle.on {
    border-color: color-mix(in srgb, var(--accent) 45%, var(--edge));
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    color: var(--accent);
  }

  .clear {
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--edge);
    border-radius: 0.3rem;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: 0.75rem;
  }

  .notice {
    max-width: 34rem;
    margin: 0;
    padding: 1.5rem;
    color: var(--muted);
  }
</style>
