<script lang="ts">
  import { untrack } from 'svelte'

  import DeviceApproval from './components/DeviceApproval.svelte'
  import EditorPane from './components/EditorPane.svelte'
  import EditorToolbar from './components/EditorToolbar.svelte'
  import GraphView from './components/GraphView.svelte'
  import Landing from './components/Landing.svelte'
  import Logo from './components/Logo.svelte'
  import ModeSwitch from './components/ModeSwitch.svelte'
  import NavColumn from './components/NavColumn.svelte'
  import PandanConnect from './components/PandanConnect.svelte'
  import PreviewPane from './components/PreviewPane.svelte'
  import BottomSheet from './components/BottomSheet.svelte'
  import RightRail from './components/RightRail.svelte'
  import Sidebar from './components/Sidebar.svelte'
  import Settings from './components/Settings.svelte'
  import Tokens from './components/Tokens.svelte'
  import { ApiError } from './lib/api'
  import { clearToken, credentialState } from './lib/auth'
  import { fetchCurrentUser } from './lib/identity'
  import { createNote, getNote, listNotes } from './lib/notes'
  import {
    currentRoute,
    interceptClick,
    navigate,
    onNavigate,
    routeHref,
    setNavigationGuard,
    type Route,
  } from './lib/router'
  import {
    modeAvailable,
    readStoredMode,
    resolveMode,
    writeStoredMode,
    type NoteMode,
  } from './lib/noteMode'
  import {
    readStoredPaneOpen,
    resolvePaneOpen,
    shellRegions,
    writeStoredPaneOpen,
  } from './lib/shell'
import { type EditorCommands, toolbarShown } from './lib/toolbar'
import { watchViewport } from './lib/viewport'
  import type { Note } from './lib/types'
  import { currentWindowClass, watchWindowClass, type WindowClass } from './lib/windowClass'

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
   * `accept()` and `discard()` live in this file. **KAN-1791 removed the one thing `Landing.svelte`
   * used to do with a credential** — the paste form that called `setToken` and then `accept()` — so
   * `Landing.svelte` now holds no token at all; GitHub sign-in is a full-page redirect, and `authed`
   * flips because the mount-time session check below finds the fresh cookie, never because
   * `Landing.svelte` told it to. `Tokens.svelte`'s "Use this token now" is the one place left that
   * still calls `setToken` and then this file's `accept()`.
   *
   * KAN-1818 made the shell responsive. Which regions render is `lib/shell.ts`'s pure
   * `shellRegions(windowClass, route, authed)`; the grid that places them is this file's CSS, keyed
   * to the same breakpoints (`lib/windowClass.ts`). Compact (<600px) shows the note list and the
   * note as separate screens under a bottom navigation bar; the header lost its Tokens and pandan
   * links, which live under Settings now.
   *
   * KAN-568 added the **fourth** region, and it is a deliberate exception to the sentence above
   * rather than a drift past it. `BacklinksPanel` could have been a third column of `.split`, and
   * that placement is the one thing this file gets to decide: it would make the rail a sibling of
   * `{#if shownMode !== 'edit'}`, so a toggle about the editor's preview would be one edit away from
   * reflowing or discarding a panel that is about neither pane. KAN-554 and KAN-962 both paid for
   * that rule. Outside `main` the mode switch cannot reach the rail at all, which is the
   * structural version of the property rather than the carefully-placed one — and the rail is not a
   * pane of the document, so it does not want one of `.split`'s `minmax(0, 1fr)` tracks either.
   *
   * There is deliberately no build-status table here. KAN-723: the one this replaced hard-coded
   * `done: false` against `kaya-client` and `kaya-cli`, both of which shipped in V2a/V2b, and the
   * false claim reached the built bundle. It was a second copy of CLAUDE.md's package table and it
   * drifted twice inside one epic, so the fix was to delete the list rather than correct the flags.
   *
   * KAN-1739 added `route.name === 'tokens'` as a **peer of the whole `authed`/`Landing` branch**,
   * not a case nested inside it — the one deliberate exception to "everything but the shell needs a
   * credential" that `authed` otherwise enforces. `Tokens.svelte` reaches kaya's own cookie-session
   * identity (`lib/identity.ts`, ADR 0012), which is a wholly different credential from the one
   * `authed` tracks, and minting your first `kaya_pat_…` cannot itself require a credential already
   * present in the tab. It owns its own session check entirely; this file only routes to it
   * and hands it the same `accept` callback `Landing` gets, so a freshly minted token can flip
   * `authed` and leave `/tokens` without a second credential ever passing through this file.
   *
   * KAN-1743's `route.name === 'device'` is the same exception for the same reason — `verification_
   * uri_complete` is very plausibly the *first* URL a fresh machine's browser ever opens for kaya,
   * so `DeviceApproval.svelte` reaches the identical cookie-session seam `Tokens.svelte` does, and
   * must be reachable with no `authed` bearer in this tab at all.
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
   * `Sidebar`'s `oncreate` (KAN-1040, BREADBOARD.md A1): create the note, then navigate to it.
   *
   * `navigate()` runs before the list refresh below, so a same-tab guard veto (KAN-969, unsaved
   * editor content elsewhere) is asked before this file does any more work — and either way the
   * note now exists, so the list is refreshed to include it regardless of whether the navigation
   * itself went through. A `404`-flavoured failure has no home here; the only failures `createNote`
   * can produce are validation and auth, both already `absorb()`'s job.
   */
  async function createAndOpen(title: string): Promise<void> {
    try {
      const created = await createNote({ title })
      justCreatedRef = created.ref
      navigate(routeHref({ name: 'note', ref: created.ref }))
      const term = query.trim()
      notes = await listNotes({ q: term === '' ? undefined : term })
    } catch (error) {
      absorb(error)
    }
  }

  /**
   * `EditorPane`'s `ondeleted` (KAN-1041, BREADBOARD.md A2): the note is already gone server-side by
   * the time this fires, so `notes` drops it by filtering rather than by a re-fetch — the same reason
   * `discard()` clears state directly instead of re-asking a server that would just say "not found".
   *
   * `editorDirty` is cleared before navigating so `confirmNavigation` does not ask whether to discard
   * unsaved changes to a note that, by the time the question would be asked, no longer exists to save
   * them to — the two-click Delete already was the deliberate act this guard exists to gate.
   */
  function noteDeleted(ref: string): void {
    notes = notes.filter((found) => found.ref !== ref)
    editorDirty = false
    navigate('/')
  }

  /**
   * `EditorPane`'s `onupdated` (KAN-1042/1043, BREADBOARD.md A3/A4): a title- or path-only `PATCH`
   * succeeded, so the matching row in `notes` is replaced with the fresh record.
   *
   * `notes` and the open `note` come from two separate fetches (`listNotes` vs. `getNote`), so the
   * row in `notes` is a *different object* from the one `EditorPane` just edited — there is nothing
   * to mutate in place, only to replace. Assigning `notes[index]` rather than reassigning the whole
   * array is what lets `Sidebar`'s existing subscription (and its tree grouping) pick up the move
   * with no new wiring there.
   */
  function noteUpdated(stored: Note): void {
    const index = notes.findIndex((found) => found.ref === stored.ref)
    if (index !== -1) {
      notes[index] = stored
    }
  }

  /**
   * `RightRail`'s `onrestored` (R13/KAN-1066): a History-tab restore succeeded, so both the sidebar
   * row **and** the open note are replaced with the fresh record.
   *
   * **Not the same as {@link noteUpdated}, and the difference is deliberate.** A title/path-only
   * save never changes what `EditorPane` is already showing — it typed the new title itself — so
   * `noteUpdated` only touches `notes`. A restore changes `body`, and the editor did not type it:
   * the restored text exists only in the History tab's preview and in the response this callback
   * receives. Reassigning `note` here is what pushes it into the editor, because `note` is the one
   * prop `EditorPane`'s own effect watches for an *external* body change — `needsRemount` (`lib/
   * editor.ts`) depends only on the ref, so this does not remount the view; it dispatches the new
   * text as a transaction, the identical path a stale-precondition "keep theirs" already uses.
   */
  function noteRestored(stored: Note): void {
    noteUpdated(stored)
    if (note?.ref === stored.ref) {
      note = stored
    }
  }

  /**
   * Whether this tab has a credential — **reactive**, and KAN-555 is why.
   *
   * It was a `const` read once at mount, which was honest while there was no way to acquire a
   * credential without reloading. Now there is: `Tokens.svelte`'s "Use this token now" calls
   * `accept()` below and the effects re-run off this rune, so a freshly minted bearer reaches the
   * note list without a reload — and GitHub sign-in reaches it too, through the mount-time session
   * check just below rather than through `accept()` at all. It also runs backwards, which is the
   * half that matters more — `discard()` puts the app back in the landing state the moment the API
   * says the credential is no good.
   */
  let authed = $state(credentialState() === 'set')

  /**
   * The one-time mount check for a cookie-only session (ADR 0012's two credential types — a bearer
   * and a `kayaauth` cookie — this file only ever needs to ask about the second one, and only once).
   *
   * `apiRequest` (`lib/api.ts`) now trusts a live cookie session for every note-API call directly, so
   * a tab that has no bearer at all is no longer necessarily a logged-out tab — it might be a reload
   * of a browser that signed in with GitHub and never minted a bearer at all. `authed`'s own initializer
   * above already covers the *other* case for free: a bearer already in `sessionStorage` is a
   * known-good signal, so `authed` starts `true` synchronously and this effect's body below never
   * needs to run for that tab. What is left is the cookie-only tab, and `fetchCurrentUser()` (`lib/
   * identity.ts`) is the one call that can tell it apart from a genuinely logged-out one — it hits
   * the cookie-authenticated `GET /users/me` and resolves to a `CurrentUser` or `null`, never
   * throwing for the logged-out case, the same shape `Tokens.svelte`'s own mount check already uses.
   *
   * **Never mints or stores anything.** The bootstrap this replaced (KAN-1739/PR #178) had to call
   * `POST /api/v1/tokens` and stash the result in `sessionStorage`, because `apiRequest` back then
   * could not yet trust the cookie on its own — that call site was the actual bug this rewrite fixes:
   * it manufactured a second, forgotten credential every time this effect ran, and "Clear token" only
   * ever cleared *that* one. This effect only ever reads; a cookie-only session stays cookie-only for
   * the rest of the tab's life, and every later note-API call keeps authenticating off the cookie.
   *
   * **Guarded to run exactly once per mount, for the same reason the bootstrap it replaced guarded
   * itself.** An effect that reads `authed` and sometimes writes it back would refire the instant
   * `authed` changes for *any* reason — including a later `401` (`discard()`, below) — and a rerun at
   * that moment would be exactly backwards: it would immediately re-ask `/users/me` about a session
   * that request just said doesn't work. `checkedSessionOnMount` starting `true` whenever a bearer is
   * already present (mirroring `authed`'s own initializer) is what keeps that first fast-path tab from
   * ever running this effect's body at all, now or after a later discard.
   */
  let checkedSessionOnMount = credentialState() === 'set'

  $effect(() => {
    if (authed || checkedSessionOnMount) {
      return
    }
    checkedSessionOnMount = true
    fetchCurrentUser()
      .then((user) => {
        if (user !== null) {
          authed = true
        }
      })
      .catch(() => {
        // No live cookie session either — genuinely logged out. Landing is already what renders for
        // `!authed`; there is nothing further to do or report.
      })
  })

  /** The API's own words for why the last credential was refused. Shown by the landing state. */
  let rejected: string | null = $state(null)

  /**
   * How the open note is shown: Read, Edit or Split (KAN-1819; it replaced KAN-554's header Preview
   * toggle). Which modes exist and what a note opens in is `lib/noteMode.ts`; this is the state.
   *
   * **`EditorPane` is deliberately outside every `{#if}` the mode controls, and that placement is the
   * whole of the switch's correctness.** Inside one, the editor would be a *different component
   * instance* every time the mode changed — `$effect` cleanup, `view.destroy()`, a fresh
   * `EditorState` — so choosing Read would throw away your unsaved edit and your undo history on a
   * command that is about how the note is *shown*. The mode reaches the pane only as the `mode`
   * prop, which the template reads and the mount effect does not; Read hides the editor with CSS
   * rather than removing it, so the live document keeps flowing and the preview shows unsaved text.
   * `tests/preview.test.ts` and `tests/note-mode-switch.test.ts` assert the same `EditorView` object
   * survives every switch, holding the same text.
   *
   * Resolved when the open note changes (remembered choice for this size class, else the default —
   * and a note just made through New note opens in Edit below expanded), and written back, per class,
   * only when the *person* picks a mode.
   */
  let mode: NoteMode = $state(
    resolveMode({
      windowClass: currentWindowClass(),
      stored: readStoredMode(currentWindowClass()),
      justCreated: false,
    }),
  )

  /** The ref `createAndOpen` just made, until the first resolution that sees it consumes it. */
  let justCreatedRef: string | null = null

  function chooseMode(next: NoteMode): void {
    mode = next
    writeStoredMode(windowClass, next)
  }

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
   * Whether the open note's editor holds content the last save does not — `EditorPane`'s own
   * `dirty`, republished through its `ondirty` seam (KAN-969).
   *
   * **Its own rune, deliberately not folded into `note`,** for the identical reason `liveDocument`
   * above is not: `note` is the editor's *input*, and the only things that may ever assign it are the
   * note fetch further down and `discard()`. Writing a per-keystroke-derived flag into it would put
   * exactly the round trip through this file that `liveDocument`'s docstring already refuses, and for
   * the same reason — it would give `EditorPane`'s own identity guard something to reason about that
   * it must never see.
   */
  let editorDirty = $state(false)

  function noteDirty(value: boolean): void {
    editorDirty = value
  }

  /**
   * The one thing {@link setNavigationGuard} asks before a same-tab navigation moves: is there
   * unsaved editor content, and if so, does the person actually want to lose it.
   *
   * **A native `confirm()`, not a component.** Both would say the same one sentence — there is no
   * diff to show here, unlike `ConflictBanner`'s two whole notes, so the comparison that justifies a
   * bespoke component there does not carry over. Building one anyway would need a second piece of
   * app-wide state (the "pending navigation" a custom dialog has to hold while it waits for a click),
   * which is exactly what `router.ts`'s guard slot was designed to let this file avoid owning.
   * `confirm()` is also **synchronous**, which is what lets `interceptClick`'s existing
   * `preventDefault()`-then-`navigate()` shape stay exactly as it is: an async confirmation would have
   * to hold that decision open across a promise, with nothing stopping a second click (or the back
   * button) from landing while the first is still waiting on an answer.
   *
   * `globalThis.confirm` rather than a bare `confirm`, matching `router.ts`'s own convention for
   * anything that might not exist in an environment running this code — and failing **open** (let the
   * navigation through) rather than closed if it somehow is not there, the same direction
   * `globalThis.history` and `globalThis.location` already fail in that file. A test environment with
   * no `confirm` should not be a test environment that can never navigate.
   */
  function confirmNavigation(): boolean {
    if (!editorDirty) {
      return true
    }
    return globalThis.confirm?.('This note has unsaved changes. Leave without saving?') ?? true
  }

  /**
   * Register the navigation guard for as long as this shell is mounted, and hand it back on the way
   * out. `App.svelte` is mounted for the app's whole lifetime in practice, but a test mounts and
   * unmounts many instances in one process, and `router.ts`'s guard slot is module-level state shared
   * by all of them — leaving a previous instance's guard registered would have one test's `confirm()`
   * answer a different test's click.
   */
  $effect(() => {
    setNavigationGuard(confirmNavigation)
    return () => setNavigationGuard(null)
  })

  /**
   * The window size class (KAN-1818), kept live from `matchMedia`. `expanded` where there is none,
   * so every non-browser test sees the original four-region layout.
   */
  let windowClass: WindowClass = $state(currentWindowClass())

  $effect(() => watchWindowClass((next) => (windowClass = next)))

  const regions = $derived(shellRegions(windowClass, route, authed))
  const compact = $derived(windowClass === 'compact')

  /** The open note's ref, or `null` — a derived so the effect below re-runs on a *different* note,
   *  never on a re-assignment of the same route. */
  const openRef = $derived(route.name === 'note' ? route.ref : null)

  $effect(() => {
    const ref = openRef
    if (ref === null) {
      return
    }
    const fresh = ref === justCreatedRef
    justCreatedRef = null
    // `windowClass` is read untracked: a resize must not re-pick the mode under someone who is
    // typing. The one resize rule (Split falls back to Edit) is `shownMode`'s, below.
    const current = untrack(() => windowClass)
    mode = resolveMode({ windowClass: current, stored: readStoredMode(current), justCreated: fresh })
  })

  /** What is actually on screen: `mode`, except that Split cannot outlive the width that offers it,
   *  and a route with no note (the empty `/`) is the editor's "pick a note" notice alone. */
  const shownMode: NoteMode = $derived(
    route.name !== 'note' ? 'edit' : modeAvailable(mode, windowClass) ? mode : 'edit',
  )

  /**
   * KAN-1826: the mobile formatting toolbar. `editorCommands` and `editorFocused` come up out of
   * `EditorPane` through two callbacks, so this file never touches the editor itself; the toolbar
   * goes back down the same way, as an interface. It shows while a note is being edited with focus
   * in the editor on a compact or medium window (`toolbarShown`), which is when a soft keyboard is
   * up. `keyboardInset` is only watched while it shows.
   */
  let editorCommands: EditorCommands | null = $state(null)
  let editorFocused = $state(false)
  let keyboardInset = $state(0)

  const toolbarOn = $derived(
    toolbarShown({
      windowClass,
      mode: shownMode,
      focused: editorFocused,
      inNote: route.name === 'note',
    }),
  )

  // A hidden editor (Read) keeps a stale "focused" in Chrome, which fires no blur for it.
  $effect(() => {
    if (shownMode !== 'edit') {
      editorFocused = false
    }
  })

  $effect(() => {
    if (!toolbarOn) {
      keyboardInset = 0
      return
    }
    return watchViewport((inset) => (keyboardInset = inset))
  })

  // The keyboard coming up or the toolbar appearing moves the editor's bottom edge. CodeMirror does
  // not re-reveal the caret on a resize, so ask once the layout has settled.
  $effect(() => {
    if (!toolbarOn) {
      return
    }
    void keyboardInset
    const frame = requestAnimationFrame(() => editorCommands?.revealCaret())
    return () => cancelAnimationFrame(frame)
  })

  /**
   * KAN-1827: the backlinks/history surface. `regions.supporting` (`lib/shell.ts`) says which kind
   * this window class gets; this file owns the open/closed state and nothing else.
   *
   * - **sheet** (compact): never remembered, closed on every navigation (a tapped backlink lands on
   *   the other note with the sheet gone) and when the window leaves compact.
   * - **pane** (medium, expanded): closed by default so the document keeps the width, and the
   *   person's choice is remembered per window class in `localStorage` (`lib/shell.ts`).
   *
   * The rail is in the grid only while the pane is open, so a grid column and its content always
   * agree (a column with no rail would be a stripe of empty page).
   */
  const supporting = $derived(regions.supporting)
  let sheetOpen = $state(false)
  let paneOpen = $derived(
    resolvePaneOpen(supporting, readStoredPaneOpen(untrack(() => windowClass))),
  )

  $effect(() => {
    void route
    sheetOpen = false
  })

  $effect(() => {
    if (supporting.kind !== 'sheet') {
      sheetOpen = false
    }
  })

  function toggleSupporting(): void {
    if (supporting.kind === 'sheet') {
      sheetOpen = !sheetOpen
    } else {
      paneOpen = !paneOpen
      writeStoredPaneOpen(windowClass, paneOpen)
    }
  }

  const railed = $derived(supporting.kind === 'pane' && paneOpen)

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
   * Reached exactly one way now: the API refusing a request with a `401`. **Clear token** used to be
   * the other way in, and KAN-1791 removed it — it only ever cleared the `sessionStorage` mirror, so
   * clicking it flipped this file to the landing state while the real `kayaauth` cookie session
   * underneath stayed alive server-side; it looked like a sign-out and was not one. Kaya's own
   * sign-out (`Tokens.svelte`, `POST /auth/logout`) is the real way to end a session now, and it ends
   * the thing that actually authenticates this tab rather than a mirror of it.
   *
   * `reason` is the API's message — every remaining caller (`absorb()` below, and the `onexpired`
   * callbacks `GraphView`/`RightRail`/`BacklinksPanel` hand this file) passes one. The parameter stays
   * typed `string | null` regardless, because narrowing it is unrelated churn for a type this function
   * costs nothing to keep general.
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

<div
  class="shell"
  class:unauthenticated={!authed}
  class:tokens-or-device={authed && (route.name === 'tokens' || route.name === 'device')}
  class:railed
  class:compact
  class:toolbar-open={toolbarOn}
  data-window-class={windowClass}
>
  <header class="topbar">
    {#if compact && authed && route.name === 'note'}
      <!-- KAN-1818: real navigation (a link to `/`), so the browser's and the OS's back button and
           this arrow agree. -->
      <a
        class="back"
        href="/"
        aria-label="Back to notes"
        onclick={(event) => interceptClick(event, '/')}
        data-testid="back-to-list"
      >
        <span aria-hidden="true">&larr;</span> Notes
      </a>
    {:else}
      <a class="brand" href="/" onclick={(event) => interceptClick(event, '/')}>
        <Logo size={26} />
        <span>kaya</span>
      </a>
    {/if}
    <span class="tagline">markdown for humans and agents</span>
    {#if supporting.kind !== 'none'}
      <!-- KAN-1827: one button, two surfaces. A sheet is a dialog the button opens; a pane is a
           region the button shows and hides. -->
      <button
        class="toggle"
        class:on={supporting.kind === 'sheet' ? sheetOpen : paneOpen}
        aria-expanded={supporting.kind === 'sheet' ? sheetOpen : paneOpen}
        aria-haspopup={supporting.kind === 'sheet' ? 'dialog' : undefined}
        aria-controls={supporting.kind === 'pane' ? 'supporting-pane' : undefined}
        onclick={toggleSupporting}
        data-testid="toggle-details"
      >
        Links
      </button>
    {/if}
  </header>

  {#if regions.nav}
    <NavColumn {route} />
  {/if}

  {#if route.name === 'tokens'}
    <main>
      <Tokens onaccept={accept} />
    </main>
  {:else if route.name === 'device'}
    <main>
      <DeviceApproval />
    </main>
  {:else if authed}
    {#if regions.list}
      <Sidebar {notes} {route} loading={listing} {query} onsearch={search} oncreate={createAndOpen} />
    {/if}
    {#if regions.main}
      <main>
        {#if route.name === 'unknown'}
          <p class="notice">
            Nothing lives at <code>{route.path}</code>. Pick a note from the list.
          </p>
        {:else if route.name === 'graph'}
          <!-- KAN-1050: read-only, so it takes no note-lifecycle callbacks — `onexpired` is the one
               failure it cannot absorb itself, for the same reason `BacklinksPanel`'s cannot. -->
          <GraphView onexpired={discard} />
        {:else if route.name === 'settings'}
          <!-- KAN-1815: reads and writes one resource (`/api/v1/preferences`), no note-lifecycle
               callbacks, for the same reason `PandanConnect` below has none. -->
          <Settings />
        {:else if route.name === 'pandan'}
          <!-- ADR 0012's amendment (KAN-1741): connecting a pandan account has no note-lifecycle
               callbacks of its own either, for the same reason `GraphView` above has none — it
               reads and writes exactly one resource (`/api/v1/pandan-link`) that no other region
               touches. -->
          <PandanConnect />
        {:else}
          <!--
            The editor and its preview, side by side. `EditorPane` is **outside** the `{#if}` below on
            purpose (see `mode`), and the preview is its **sibling** rather than anything nested
            in it — PLAN §S9: Svelte never renders inside CM6's subtree. The document travels from
            one to the other through `ondocument` and `liveDocument`, which is a published prop
            rather than a reach into the editor's internals; see `liveDocument` on why it is not
            `note.body`.
          -->
          <div class="note-screen" style:--kb-inset="{keyboardInset}px">
            {#if route.name === 'note'}
              <!-- KAN-1819: above the note, not in the header — it is about this note, and on a
                   phone the header has no room. A sibling of `.split`, so it can never be the
                   thing that remounts the editor. -->
              <div class="mode-bar">
                <ModeSwitch mode={shownMode} {windowClass} onchange={chooseMode} />
              </div>
            {/if}
            <div class="split" data-mode={shownMode}>
              <EditorPane
                {note}
                mode={shownMode}
                error={failure === '' ? null : failure}
                ondocument={publishDocument}
                ondirty={noteDirty}
                ondeleted={noteDeleted}
                onupdated={noteUpdated}
                oncommands={(next) => (editorCommands = next)}
                onfocuschange={(focused) => (editorFocused = focused)}
              />
              {#if shownMode !== 'edit'}
                <PreviewPane {note} source={liveDocument} reading={shownMode === 'read'} />
              {/if}
            </div>
            {#if toolbarOn}
              <EditorToolbar commands={editorCommands} inset={keyboardInset} />
            {/if}
          </div>
        {/if}
      </main>
    {/if}
    {#if railed}
      <!--
        KAN-568's rail — the fourth region, and **outside `main` on purpose** (see `railed`). It
        takes the note rather than the route's ref, so it never asks about a ref the note fetch has
        not confirmed exists, and it hands a `401` back to `discard()` because this file owns the
        credential lifecycle and no region may absorb one. R13/KAN-1064 added a second tab
        (`RightRail.svelte`) beside the original Backlinks one; `onrestored` is the one seam that
        tab needed from this file, because a restore has to reach the open `note`, not just the
        sidebar row (see `noteRestored`).
      -->
      <RightRail {note} onexpired={discard} onrestored={noteRestored} />
    {/if}
    {#if supporting.kind === 'sheet' && sheetOpen}
      <BottomSheet label="Links and history" onclose={() => (sheetOpen = false)}>
        <RightRail id="sheet-rail" {note} onexpired={discard} onrestored={noteRestored} />
      </BottomSheet>
    {/if}
  {:else}
    <!-- KAN-555's landing state. KAN-1791 removed its paste form — GitHub sign-in is a full-page
         redirect now, so this file hands it `rejected` and never sees a token at all. -->
    <Landing {rejected} onaccept={accept} />
  {/if}
</div>

<style>
  /*
    KAN-1818. Written base = medium (600-839px): a slim nav rail, the list beside the note, the
    rail *below* the note. `min-width: 840px` is expanded (the original four regions);
    `max-width: 599.98px` is compact (one screen at a time, bottom navigation bar). The numbers
    mirror `lib/windowClass.ts` and `tests/window-class.test.ts` checks them. Every grid track that
    holds content is `minmax(0, …)`, so nothing keeps a laptop-width minimum on a phone.
  */
  .shell {
    display: grid;
    grid-template-areas: 'topbar topbar' 'nav main';
    grid-template-columns: 3.75rem minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
    height: 100dvh;
  }

  /* The list region, whenever there is one (`Sidebar` places itself by class, below). */
  .shell:has(> :global(.sidebar)) {
    grid-template-areas: 'topbar topbar topbar' 'nav sidebar main';
    grid-template-columns: 3.75rem clamp(11rem, 28vw, 16rem) minmax(0, 1fr);
  }

  /* KAN-568's fourth region, present only while a note route is open (see `railed`): below the
     document on medium, beside it on expanded. The list spans both rows (named twice) because it is
     a column, not something that stacks. */
  .shell.railed {
    grid-template-areas: 'topbar topbar topbar' 'nav sidebar main' 'nav sidebar rail';
    grid-template-columns: 3.75rem clamp(11rem, 28vw, 16rem) minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr) auto;
  }

  .shell.railed > :global(.right-rail) {
    max-height: 40dvh;
    border-top: 1px solid var(--outline-variant);
    border-left: 0;
  }

  /* No sidebar, no nav column, without a credential: there is nothing to list or switch between,
     and either one beside a sign-in page reads as a broken app rather than as a locked one. */
  .shell.unauthenticated {
    grid-template-areas: 'topbar' 'main';
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
  }

  @media (min-width: 840px) {
    .shell {
      grid-template-columns: 7rem minmax(0, 1fr);
    }

    .shell:has(> :global(.sidebar)) {
      grid-template-columns: 7rem clamp(11rem, 28vw, 16rem) minmax(0, 1fr);
    }

    .shell.railed {
      grid-template-areas: 'topbar topbar topbar topbar' 'nav sidebar main rail';
      grid-template-columns: 7rem clamp(11rem, 28vw, 16rem) minmax(0, 1fr) clamp(10rem, 16vw, 14rem);
      grid-template-rows: auto minmax(0, 1fr);
    }

    .shell.railed > :global(.right-rail) {
      max-height: none;
      border-top: 0;
      border-left: 1px solid var(--outline-variant);
    }

    .shell.unauthenticated {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  .topbar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    grid-area: topbar;
    min-width: 0;
    padding: 0.85rem 1.25rem;
    background: var(--surface-container-low);
    border-bottom: 1px solid var(--outline-variant);
  }

  /* The toggles sit at the right edge of the bar. */
  .topbar > .toggle:first-of-type {
    margin-left: auto;
  }

  .brand {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
  }

  .brand,
  .back {
    color: inherit;
    font-size: var(--type-title-medium-size);
    font-weight: 600;
    letter-spacing: -0.01em;
    text-decoration: none;
  }

  .tagline {
    color: var(--on-surface-variant);
    font-size: var(--type-body-medium-size);
  }

  .shell > :global(.sidebar) {
    grid-area: sidebar;
  }

  /* R13/KAN-1064 wrapped the fourth region in `RightRail.svelte` (the tab strip beside Backlinks),
     so the direct child under `.shell` is `.right-rail`; `BacklinksPanel`'s own `.rail` is one level
     deeper. */
  .shell > :global(.right-rail) {
    grid-area: rail;
  }

  /* Same door as `.sidebar` above: the child component owns its own element, so the parent places
     it by class rather than by wrapping it in a div that exists only to be positioned. */
  .shell > :global(.landing) {
    grid-area: main;
  }

  main {
    grid-area: main;
    min-width: 0;
    min-height: 0;
    overflow-y: auto;
  }

  /* KAN-1819: the note screen is the mode switch above the document area. `.split` fills what the
     switch leaves; `min-height: 0` lets its grid track (and the editor's own scrolling) shrink. */
  .note-screen {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
  }

  /* KAN-1826: the toolbar is fixed to the visible bottom, so the editor stops above it: the
     keyboard's inset plus the toolbar's own height (2.75rem, `EditorToolbar`'s button). */
  .shell.toolbar-open .note-screen {
    padding-bottom: calc(var(--kb-inset, 0px) + 2.75rem);
  }

  .mode-bar {
    flex: none;
    padding: 0.75rem 1.5rem 0;
  }

  /* One track by default (Edit). `minmax(0, …)` always, not `1fr`: a `1fr` track has an `auto`
     minimum, so one long unbroken line in a fenced code block would widen the editor and push the
     preview off the pane. */
  .split {
    display: grid;
    flex: 1;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr);
    min-height: 0;
  }

  /* Edit: the editor alone. Capped to a readable measure and centred so it does not stretch across
     a wide pane. */
  .split[data-mode='edit'] > :global(.pane) {
    width: 100%;
    max-width: 72ch;
    margin-inline: auto;
  }

  /* Read: the document alone, as a column of text (~65ch) centred in the pane. The editor is still
     mounted inside `.pane`, hidden by `EditorPane`'s own `reading` class; the page scrolls, not the
     box. */
  .split[data-mode='read'] {
    display: block;
    overflow-y: auto;
  }

  .split[data-mode='read'] > :global(.pane),
  .split[data-mode='read'] > :global(.preview) {
    max-width: 65ch;
    margin-inline: auto;
  }

  /* Split (expanded only): editor 55 / preview 45. */
  .split[data-mode='split'] {
    grid-template-columns: minmax(0, 55fr) minmax(0, 45fr);
  }

  /* Under about a laptop's width two columns are two cramped columns. Stacking keeps both usable, and
     the editor stays first so the thing you type in is the thing you see. */
  @media (max-width: 60rem) {
    .split[data-mode='split'] {
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto;
      flex: none;
    }
  }

  .toggle {
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--outline);
    border-radius: var(--shape-full);
    background: transparent;
    color: var(--on-surface-variant);
    cursor: pointer;
    font: inherit;
    font-size: var(--type-body-small-size);
  }

  .toggle.on {
    border-color: transparent;
    background: var(--secondary-container);
    color: var(--on-secondary-container);
  }

  .notice {
    max-width: 34rem;
    margin: 0;
    padding: 1.5rem;
    color: var(--on-surface-variant);
  }

  /* Compact: one screen at a time, the navigation bar along the bottom. The list and `main` never
     coexist here (`shellRegions`), so both claim the one content area. */
  @media (max-width: 599.98px) {
    .shell,
    .shell:has(> :global(.sidebar)),
    .shell.unauthenticated {
      grid-template-areas: 'topbar' 'main' 'rail' 'nav';
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto minmax(0, 1fr) auto auto;
    }

    /* KAN-1826: the toolbar takes the bottom edge while a note is being edited. */
    .shell.toolbar-open > :global(.nav-column) {
      display: none;
    }

    /* KAN-1826: a phone's keyboard leaves about half the screen. While the editor has focus the
       document gets it: the title and path step aside, and the editor may shrink below its usual
       minimum. Save and the mode switch stay: on an iPhone there is no key to dismiss the keyboard,
       and switching to Read is how a person leaves editing. Everything is back once focus leaves. */
    .shell.toolbar-open .note-screen :global(.pane > header) {
      display: none;
    }

    .shell.toolbar-open .note-screen :global(.editor-host) {
      min-height: 0;
    }

    .shell.toolbar-open .mode-bar {
      padding-top: 0.25rem;
    }

    .shell.toolbar-open .note-screen :global(.pane) {
      gap: 0.5rem;
      padding-block: 0.5rem;
    }

    .shell > :global(.sidebar) {
      grid-area: main;
      border-right: 0;
    }

    .topbar {
      align-items: center;
      gap: 0.5rem;
      min-height: 3.5rem;
      padding: 0.25rem 1rem;
    }

    .tagline {
      display: none;
    }

    .back {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      min-height: 2.75rem;
      margin-left: -0.5rem;
      padding: 0 0.5rem;
    }

    .toggle {
      min-height: 2.75rem;
      padding: 0 0.75rem;
      font-size: var(--type-body-medium-size);
    }

    .mode-bar {
      padding: 0.5rem 1rem 0;
    }
  }
</style>
