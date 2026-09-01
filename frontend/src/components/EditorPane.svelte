<script lang="ts">
  import { untrack } from 'svelte'

  import type { EditorView } from '@codemirror/view'

  import { ApiError } from '../lib/api'
  import { needsFetch } from '../lib/backlinks'
  import { type ConflictVersions, keepMinePatch } from '../lib/conflict'
  import { conflictVersions, needsRemount, syncDocument } from '../lib/editor'
  import { deleteNote, listLinks, updateNote } from '../lib/notes'
  import type { Link, Note, NoteUpdate } from '../lib/types'
  import ConflictBanner from './ConflictBanner.svelte'

  /**
   * `lib/codemirror.ts`, named as a **type** so naming it costs nothing.
   *
   * `typeof import(…)` is erased by `verbatimModuleSyntax` exactly like an `import type` is, so this
   * line does not put the module in the entry chunk — the only thing that reaches it is the
   * `import()` in the loader below, which is what makes it a chunk of its own.
   */
  type EditorKit = typeof import('../lib/codemirror')

  const {
    note,
    error,
    ondocument,
    ondirty,
    ondeleted,
  }: {
    note: Note | null
    error: string | null
    /**
     * **KAN-969's seam: whether the open note holds content the last save does not**, fired
     * whenever {@link dirty} changes.
     *
     * Same shape as `ondocument` below and untracked for the identical reason: the parent
     * (`App.svelte`) needs this to decide whether a same-tab navigation should ask before it
     * discards anything, and reading the callback must not be able to make this component's mount
     * effect depend on its own output. So it is read only inside `untrack`, from an effect that reads
     * nothing but `dirty` itself — never from the mount effect, which already *writes* `dirty` on a
     * remount but must never read it back.
     *
     * `dirty` is not new here — it already drives this pane's own "unsaved changes" status row. This
     * prop only republishes a value the component already computed for its own template; it is
     * deliberately not a second, independently-derived notion of "unsaved" in `App.svelte`, which is
     * exactly the trap CLAUDE.md's "a structural guard does not cover a behavioural claim" section
     * warns about — two definitions of the same fact drift the first time either side's changes.
     */
    ondirty?: (dirty: boolean) => void
    /**
     * **The document seam: what the editor is showing right now, whenever that changes.**
     *
     * Named for the thing rather than for its first consumer. KAN-554's live preview is one reader;
     * V5's wikilink pills and backlinks panel (KAN-567/568) need the same value, and none of them
     * should have to reach for it. It publishes the **view's** `state.doc`, not the note's `body`,
     * because the two differ the moment you type and every consumer wants what is on screen.
     *
     * Fired once per mounted note with the initial document, then on every `docChanged` transaction —
     * including the ones this component dispatches itself (`syncDocument`, and KAN-556's
     * `keepTheirs`), because from a reader's point of view those are the document changing.
     *
     * ## Two rules this seam must not break, and how it doesn't
     *
     * **It must not re-run the `$effect` below.** The callback is read through {@link untrack} in
     * {@link publish}, so a parent that hands down a new closure per render — the ordinary case, since
     * the parent's own state changes on every keystroke it receives — cannot make this component's
     * mount effect a dependency of its own output. That matters most because `syncDocument` dispatches
     * *from inside* that effect: without `untrack`, the prop would be read while the effect was
     * collecting dependencies, and a per-keystroke effect re-run would be one closure identity away.
     * `needsRemount` still takes no body parameter, so even a re-run could not remount.
     *
     * **It must not put a Svelte node in CM6's subtree** (PLAN §S9). It cannot: it hands a `string`
     * out and takes nothing back, so a consumer renders into its own element or nowhere.
     */
    ondocument?: (document: string) => void
    /**
     * KAN-1041's seam: fired with the ref once `DELETE` succeeds. `App.svelte` removes the row from
     * the sidebar's own `notes` list and navigates home — this component knows nothing about either,
     * the same split `ondirty` already makes for "is there something to lose".
     */
    ondeleted?: (ref: string) => void
  } = $props()

  /**
   * Hand the current document to {@link ondocument}, if anyone asked for it.
   *
   * `untrack` is the load-bearing word — see the prop's docstring. It is *reading the prop* that has
   * to be untracked, not calling it, which is why the read is inside the callback rather than hoisted.
   */
  function publish(document: string): void {
    untrack(() => ondocument)?.(document)
  }

  /** {@link publish}'s sibling for {@link ondirty} — see that prop's docstring. */
  function publishDirty(value: boolean): void {
    untrack(() => ondirty)?.(value)
  }

  /**
   * The element CodeMirror owns.
   *
   * PLAN §S9 and ADR 0001 §2: **Svelte never renders inside CM6's subtree.** KAN-552 put this
   * boundary in before the editor existed, precisely so this card would not have to move it, and
   * `tests/editor-container.test.ts` parses this file to assert the container below has zero template
   * children. Nothing in the markup may put a node in there — not a word of text, not an `{#if}`,
   * not a `{@html}` — because from that moment CM6's transactions and Svelte's rerenders are editing
   * one subtree and PLAN §Open risks' update loop is live.
   */
  let host: HTMLDivElement | undefined = $state()

  /**
   * The CodeMirror module, once it has arrived — **KAN-767, and the only reason this component is
   * asynchronous at all.**
   *
   * CM6 is ~100 KB gzip and `lib/codemirror.ts` is reached through a dynamic `import()`, so it is its
   * own chunk and an unauthenticated visitor pasting a PAT never fetches it. That makes the editor's
   * arrival an event, and where that event is handled is the whole of this card's correctness.
   *
   * **It is a rune, and the mount effect *reads* it — so the mount effect stays synchronous.** That
   * is the design, stated as the thing it avoids: the obvious implementation puts the `await` inside
   * the mount effect, and then two runs of that effect can be in flight at once. Svelte runs an
   * effect's cleanup *before* every re-run, so a cleanup firing while run A is still awaiting sees
   * `view === undefined` and has nothing to destroy; A then resolves and builds a view into a host
   * that run B is also building into, or into one that is being torn down. Two views in one
   * container, or an orphan nobody holds a reference to — and both are invisible from a green test
   * suite. Reading a rune instead means the load resolves *once*, per component, and every mount is
   * the same straight-line code KAN-553 wrote: read the deps, guard, build. There is nothing to
   * cancel because nothing races.
   *
   * `null` behaves exactly like `host === undefined` did already — a state the effect returns out of
   * and is re-entered from — which is why it costs one clause below and no new shape.
   */
  let kit: EditorKit | null = $state(null)

  /**
   * The live view, the ref it was built for, and ADR 0009's precondition. **Plain `let`, not
   * `$state`.**
   *
   * `view` and `mountedRef` are read *and* written by the `$effect` below, and a rune that an effect
   * both reads and writes is an effect that retriggers itself — the update loop again, arriving
   * through the reactivity system instead of through CM6. They are bookkeeping for an imperative
   * object, they are never read by the markup, and so they must stay outside the graph.
   *
   * `basedOn` is different and *is* a rune: the header shows it, and it has to change when a save
   * returns a new stamp.
   */
  let view: EditorView | undefined
  let mountedRef: string | null = null
  /**
   * The last body this component took **from the prop**, and the reason it exists is data loss.
   *
   * The echo guard asks "is this already the document?"; this asks "is this even an update?". They
   * catch disjoint cases and neither covers the other. A parent that hands down a *new object with
   * unchanged content* while you are typing — which is exactly the parent the identity guard is
   * written for — produces an incoming body that differs from the editor's document (you typed) but
   * is not new (nobody changed the note). Dispatching there would replace your in-flight edit with
   * the server's copy, silently, on a re-render that changed nothing. So the incoming document is
   * only applied when the *source* moved, and the echo guard then decides whether that value needs a
   * transaction at all.
   */
  let appliedBody = ''

  /**
   * The `updated_at` this edit is based on — ADR 0009's precondition, carried as an **opaque
   * string**.
   *
   * Never parsed, never reformatted, never round-tripped through a `Date`. The comparison on the
   * backend is exact to the microsecond and `new Date(s).toISOString()` rounds to milliseconds, so a
   * token touched anywhere on this path refuses *every* correct write. It is set from the note the
   * view was built for and re-set from the **response** of a successful save; nothing here ever
   * fetches it. A read-before-write would look safer and would disable the guarantee — the token
   * would then name a version read microseconds ago rather than the version this edit was made
   * against, so the `409` would only fire on a race inside that window.
   */
  let basedOn: string | null = $state(null)

  let dirty = $state(false)
  let saving = $state(false)
  /** What the last save did, as one line. Cleared by the next edit. */
  let saved: string | null = $state(null)
  /** A refusal that is not ADR 0009's, or one whose two versions did not parse. */
  let refusal: string | null = $state(null)
  /**
   * ADR 0009's `409`, held whole — and what `ConflictBanner` renders (KAN-556).
   *
   * Both notes arrive complete because a side-by-side of two prose bodies needs both bodies whole
   * (`backend/app/api/concurrency.py`), and a client cannot reconstruct one from a patch it no longer
   * holds. Cleared on a successful resolution and **replaced** by a fresh `409`, never cleared at the
   * *start* of a write: the banner has to stay on the screen while the resolution it launched is in
   * flight, or the buttons vanish under the cursor.
   */
  let conflict: ConflictVersions | null = $state(null)
  /**
   * Whether the stored version moved *between* two refusals.
   *
   * The note can change again while the banner is open — that is the whole shape of this feature —
   * and "keep mine" is guarded, so it can be refused a second time by a third writer. Comparing the
   * two `stored` stamps is what tells a genuinely new conflict from the same one refused again (a
   * plain Save after a `409` re-sends the same stale precondition and is refused identically, which
   * is correct and is *not* news).
   */
  let movedAgain = $state(false)
  /**
   * What a resolution that made no request did, as one line. Cleared by the next edit.
   *
   * Separate from `saved` because "kept theirs" is emphatically not a save: nothing was written, and
   * saying `saved` there would claim the server holds text it does not.
   */
  let resolution: string | null = $state(null)
  /**
   * The editor's chunk never arrived (KAN-767). Rendered as a notice, **beside** the container.
   *
   * A lazy chunk is one more request, so it is one more thing that can fail — offline, or a deploy
   * that replaced the asset while this tab was open. Left unhandled the symptom is an empty bordered
   * rectangle and no explanation, which is the worst of the two states this card chooses between. It
   * is its own rune rather than folded into `refusal` because that one means "the server refused a
   * write", and telling a load failure apart from a refused save is exactly what a bug report needs.
   */
  let unavailable: string | null = $state(null)

  /**
   * KAN-1041, BREADBOARD.md A2: whether the Delete button is armed — the two-step confirm the card
   * asks for, with no native `confirm()` and no modal library. The first click arms it; the second,
   * while still armed, is the actual delete.
   *
   * Reset in the mount effect's remount branch below, alongside `dirty`/`refusal` and friends — this
   * component is mounted once for the app's whole lifetime and only the *note* changes underneath
   * it, so without that reset, arming Delete on one note and then opening another without confirming
   * would leave the next note's button one click from deleting **it** instead.
   */
  let deleteArmed = $state(false)
  let deleting = $state(false)
  /** A delete `DELETE` refused or failed to reach the server. Cleared by the next attempt. */
  let deleteError: string | null = $state(null)

  /**
   * KAN-567: the open note's outbound wikilinks, as `/links` last answered — what
   * `lib/codemirror.ts`'s pill decoration reads.
   *
   * **This component fetches `/links` itself, keyed on the `note` prop, exactly as
   * `BacklinksPanel.svelte` fetches its own data about the same prop** — a sibling state machine
   * rather than a value threaded down from `App.svelte`, which stays the shell that owns layout and
   * routing and nothing about one pane's data. `linksFor` and `linksInflight` are plain `let`s for
   * the reason `mountedRef` and `view` are: bookkeeping an effect both reads and writes must stay
   * outside the reactivity graph or the effect retriggers itself. `links` is `$state` because the
   * mount effect below reads it as a dependency, which is what pushes a later answer into an
   * already-live view via `setWikilinks`.
   *
   * **The reconciliation window this leaves, stated rather than left implicit**: `/links` reflects
   * the note's last *saved* body (`note_link` reconciles on save, KAN-562), never what is currently
   * typed. So a `[[...]]` typed since the last save has no row here yet and renders as an unresolved
   * pill — indistinguishable, from this component's side, from a link the API genuinely could not
   * resolve. That is deliberate rather than a gap: guessing a resolution kaya's own database does
   * not have would show a caller something it cannot back up (`lib/wikilinks.ts`'s
   * `matchingLink`). The window narrows itself on every successful save, below, which is exactly
   * the moment a fresh answer becomes available.
   */
  let links: Link[] = $state([])
  let linksFor: string | null = null
  let linksInflight: AbortController | undefined
  /**
   * The last `links` array actually pushed into the live view — `appliedBody`'s sibling for the same
   * reason. Compared by **identity**: a re-render that hands down a new `note` object for the same
   * ref and body still re-runs the mount effect below, and without this the same array would be
   * dispatched to CM6 again on every such re-render, a transaction with nothing in it to justify one.
   * `links` only ever changes to a genuinely new array (a fresh `/links` answer), so identity is
   * exactly the right comparison — unlike the echo guard's, which has to compare *content* because a
   * new string can legitimately equal the old one.
   */
  let appliedLinks: Link[] = []

  /** Ask `/links` again for `ref`, replacing whatever request was already in flight. */
  function loadLinks(ref: string): void {
    linksInflight?.abort()
    const abort = new AbortController()
    linksInflight = abort
    linksFor = ref
    listLinks(ref, { signal: abort.signal }).then(
      (found) => {
        if (linksInflight === abort) {
          links = found
        }
      },
      () => {
        // A failed `/links` fetch degrades to "no pill looks resolved" rather than an error banner —
        // the pill is decoration, not the note, and ADR 0003 already makes the route itself resilient
        // to a down pandan; a transport failure reaching *this* request is rarer still and no more
        // deserving of interrupting an edit than a slow decoration would be.
        if (linksInflight === abort) {
          links = []
        }
      },
    )
  }

  /**
   * Fetch `/links` when the **note** changes, and never when its content does — `BacklinksPanel`'s
   * `needsFetch` one component over, reused rather than duplicated because the comparison it makes
   * (identity of the ref, not of the object) is exactly the same question asked about the same prop.
   */
  $effect(() => {
    const opened = note
    const incoming = opened?.ref ?? null
    if (!needsFetch(linksFor, incoming)) {
      return
    }
    if (incoming === null) {
      linksInflight?.abort()
      linksInflight = undefined
      linksFor = null
      links = []
      return
    }
    loadLinks(incoming)
  })

  /** The component's own once-per-lifetime job for this fetch: let go of it on the way out. */
  $effect(() => {
    return () => {
      linksInflight?.abort()
      linksInflight = undefined
    }
  })

  /**
   * KAN-969: tell the parent whenever `dirty` changes.
   *
   * Its own effect, reading nothing else — not `note`, not `kit`, not `host` — so it cannot become a
   * reason the mount effect below re-runs, and the mount effect cannot be mistaken for the place this
   * belongs. `dirty` is read here **tracked**, which is the whole point: this is the one place that
   * is supposed to re-run when it changes. `ondirty` itself is still read through `untrack`, inside
   * {@link publishDirty} — the callback identity must not become a second dependency of this effect
   * either, or a parent handing down a fresh closure every render would run it needlessly, exactly the
   * concern `ondocument`'s docstring raises for the mount effect.
   */
  $effect(() => {
    publishDirty(dirty)
  })

  /**
   * Mount CodeMirror once per note, and hand it every later document as a transaction.
   *
   * **Reading the `note` prop registers it as a dependency**, so this effect re-runs whenever the
   * parent hands down a new object — per keystroke, if some future parent does that. That is not
   * avoidable by reading a narrower field: `note.ref` and `note.body` are the same signal read.
   * What is avoidable is *remounting*, which is what {@link needsRemount} decides.
   *
   * **So the teardown is not in this effect's cleanup, and that is a deliberate departure from
   * KAN-552's rehearsal.** Svelte runs an effect's cleanup *before* every re-run, so a
   * `return () => view.destroy()` here would destroy the view on the very content change the
   * identity guard exists to survive — the guard would return early into a view that had already
   * been torn down. The per-note destroy therefore sits in the body, immediately beside the
   * construction it replaces, and the per-component destroy is the second effect below, which reads
   * nothing and whose cleanup can only fire on unmount.
   *
   * **KAN-767 added `kit` to the reads and one clause to the guard, and changed nothing else about
   * this effect — deliberately.** It does not `await`, so every property above survives verbatim.
   * All three dependencies are read *before* the early return, because that is what registers them:
   * returning above the `note` read would leave this effect unsubscribed from the note and the pane
   * would never open a second one.
   *
   * **KAN-567 added `links` to the reads, for the same reason `kit` was added and nothing else.**
   * `links` is `$state`, written by the fetch effect above whenever a `/links` answer arrives — the
   * very first one (racing this effect's own build), and every later one after a save reconciles
   * `note_link` server-side. Reading it here means a fresh answer reaches the pill decoration
   * whichever branch below runs: `needsRemount`'s "same note" branch pushes it onto the view that is
   * already live, and a rebuild seeds the new view with it directly.
   */
  $effect(() => {
    const parent = host
    const opened = note
    const loaded = kit
    const currentLinks = links
    if (parent === undefined || loaded === null) {
      return
    }
    const incomingRef = opened?.ref ?? null
    const incomingBody = opened?.body ?? ''

    // --- Guard 1 of 2: the identity guard (see lib/editor.ts). ---
    if (!needsRemount(view !== undefined, mountedRef, incomingRef)) {
      // Same note, so the document goes in as a transaction and never as a remount — but only if the
      // prop actually moved (see `appliedBody`), and then only if guard 2 of 2 — the echo guard,
      // inside `syncDocument` — finds it is not already the value the editor holds.
      if (incomingBody !== appliedBody) {
        appliedBody = incomingBody
        syncDocument(view as EditorView, incomingBody)
      }
      if (currentLinks !== appliedLinks) {
        appliedLinks = currentLinks
        loaded.setWikilinks(view as EditorView, currentLinks)
      }
      return
    }

    view?.destroy()
    view = build(loaded, parent, opened, currentLinks)
    mountedRef = incomingRef
    appliedBody = incomingBody
    appliedLinks = currentLinks
    basedOn = opened?.updated_at ?? null
    dirty = false
    saved = null
    refusal = null
    conflict = null
    movedAgain = false
    resolution = null
    deleteArmed = false
    deleting = false
    deleteError = null
    // A newly built view has a document nobody has been told about — no transaction happened, so the
    // update listener never fired. Read it off the view rather than from `incomingBody`, so the seam's
    // one promise ("what the editor is showing") is true even if those two ever diverge.
    publish(view.state.doc.toString())
  })

  /**
   * KAN-969's second navigation surface: a tab close or a reload, which `lib/router.ts`'s guard
   * cannot see at all — `beforeunload` fires once the browser has already decided to leave, on a
   * page the SPA's own router never gets a say over. So this has to be asked directly, from the one
   * event that exists to be asked.
   *
   * Reads `dirty` **at the moment the browser asks**, not through the reactive graph: a DOM event
   * listener's callback runs outside any effect's synchronous pass, so reading a rune inside it
   * registers no dependency and cannot retrigger anything. That is what makes it safe to attach this
   * listener exactly once, in the effect below that already owns the component's other
   * once-per-lifetime job, rather than adding and removing it every time `dirty` flips — the listener
   * itself never has to change, only what it decides on the day it fires.
   *
   * No browser has shown a custom string in this dialog in years; `event.returnValue` is set to a
   * non-empty value only because some engines still check for one before showing their own fixed
   * prompt. The only thing `preventDefault()` buys is that native prompt appearing at all, and it is
   * called **only** while `dirty` — an unconditional listener would turn every routine reload into a
   * dialog, which is exactly how a warning trains someone to click through it without reading it.
   */
  function confirmBeforeUnload(event: BeforeUnloadEvent): void {
    if (!dirty) {
      return
    }
    event.preventDefault()
    event.returnValue = ''
  }

  /**
   * The component's three once-per-lifetime jobs: **fetch the editor, listen for the tab closing,
   * and give both back.**
   *
   * Reads nothing, so it runs exactly once and its cleanup fires only when the component is
   * destroyed — which is what makes it safe to put `view.destroy()` in, and is also what makes it the
   * right place for KAN-767's `import()` and KAN-969's `beforeunload` listener alike. One run means
   * one load and one listener, which is the property the mount effect above leans on when it treats
   * `kit` as a value that only ever arrives, and the property that stops this component from
   * accumulating a second `beforeunload` handler every time it happens to re-run for an unrelated
   * reason (it does not re-run at all, but the listener's lifetime should not depend on that).
   *
   * The two live together because they share `live`, which stops a component unmounted mid-flight from
   * coming back and assigning a rune afterwards. **Measured honesty about that flag:** deleting it does
   * *not* redden `tests/editor-lazy-mount.test.ts`, because Svelte 5 does not re-run a destroyed
   * component's effects — the write lands on a rune nobody reads and no view is built either way. It is
   * kept because it is two lines, because it means the design does not *depend* on that detail of
   * Svelte's scheduler, and because the version without it reads as though nobody considered the case.
   * But what actually holds the property is the shape above, and the test pins the outcome rather than
   * the flag: do not cite `live` as the guard.
   *
   * SLICES §V3 asks for "mounts once per note and tears down cleanly on navigation (no leaked
   * listeners)". Navigation is the effect above; this is the pane going away.
   */
  $effect(() => {
    let live = true
    globalThis.addEventListener?.('beforeunload', confirmBeforeUnload)
    // The one `import()` in this component, and the reason CodeMirror is a chunk rather than a third
    // of the entry bundle. A rejection is a real state — offline, or a deploy that replaced the asset
    // under an open tab — and an unexplained empty rectangle is a worse answer than a sentence.
    import('../lib/codemirror').then(
      (loaded) => {
        if (live) {
          kit = loaded
        }
      },
      () => {
        if (live) {
          unavailable = 'The editor could not be loaded. Reload the page to try again.'
        }
      },
    )
    return () => {
      live = false
      globalThis.removeEventListener?.('beforeunload', confirmBeforeUnload)
      view?.destroy()
      view = undefined
      mountedRef = null
    }
  })

  /**
   * The view for one note, built by the module that owns CodeMirror's values.
   *
   * What is left here is only what is about the *note*: whether there is one to edit, which words the
   * zero state says, and the four runes a document change moves. The extension set and the theme are
   * `lib/codemirror.ts`, because they cannot be written without a CodeMirror value in scope and that
   * value is the thing KAN-767 defers. `links` (KAN-567) seeds the pill decoration's first paint;
   * `setWikilinks` is how a later `/links` answer reaches this same view afterwards.
   */
  function build(
    loaded: EditorKit,
    parent: HTMLElement,
    opened: Note | null,
    currentLinks: Link[],
  ): EditorView {
    const editable = opened !== null
    return loaded.createView({
      parent,
      doc: opened?.body ?? '',
      editable,
      placeholder: editable ? 'Write markdown…' : 'No note open.',
      links: currentLinks,
      onSave: onSaveKey,
      onChange: (document) => {
        dirty = true
        saved = null
        // Including the transaction `keepTheirs` dispatches — from CM6's side that is an edit like
        // any other, which is why that function sets its own two runes *after* the dispatch rather
        // than before it.
        resolution = null
        // The document seam. The view's document and not the note's `body`: this is the value on
        // screen, which is the only one a preview or a link panel can honestly render.
        publish(document)
      },
    })
  }

  /**
   * CM6 keybindings are synchronous and return whether they handled the key. The save is not, so the
   * promise is deliberately dropped here and every failure is reported through the runes below.
   */
  function onSaveKey(): boolean {
    void save()
    return true
  }

  /** The Save button and `Mod-s`: the document as it stands, guarded on the version it was based on. */
  function save(): Promise<void> {
    const current = view
    if (current === undefined) {
      return Promise.resolve()
    }
    // `if_updated_at` present is the guarded write; **omitting it is the plain overwrite**, by
    // specification (ADR 0009). There is no `--force` in the CLI and there is no override here, for
    // the same reason: the unguarded write is spelled by not sending something.
    const precondition = basedOn
    return write({
      body: current.state.doc.toString(),
      ...(precondition === null ? {} : { if_updated_at: precondition }),
    })
  }

  /**
   * "Keep mine": the refused write again, aimed at the version that refused it.
   *
   * The crossing — `body` from `attempted`, `if_updated_at` from `stored` — is
   * {@link keepMinePatch}, and it is a pure function in `lib/conflict.ts` rather than three lines
   * here because it is the **second** place in this SPA a precondition is built. Both stamps stay
   * opaque strings; a `Date` anywhere on either path refuses every correct write.
   */
  function keepMine(): Promise<void> {
    const versions = conflict
    return versions === null ? Promise.resolve() : write(keepMinePatch(versions))
  }

  /**
   * "Keep theirs": **no request at all**, and the caller's text is replaced in place.
   *
   * Nothing needs writing, because the stored version already *is* what the server holds — the whole
   * `409` was kaya refusing to overwrite it. So this is a discard, and three things make it one the
   * user is not surprised by:
   *
   * - The stored body goes in through `syncDocument`, the same **transaction** every external update
   *   uses (PLAN §S9: never a remount). So CM6's undo history survives, and the discarded text is one
   *   ⌘/Ctrl-Z away for as long as the pane lives. The banner says so before the click, and
   *   `resolution` says it again after. That is the only copy there is — ADR 0009 §Consequences:
   *   there is no revision history, so "keep theirs" really does discard.
   *   **`isolateHistory` is what makes "one undo" true**, and it was found by the test for it going
   *   red rather than reasoned out: CM6 groups adjacent changes into one history event, so a discard
   *   clicked within `newGroupDelay` (500 ms) of the last keystroke merged into the user's own typing
   *   and a single undo threw *that* away as well — the promise on the button reversing itself into
   *   the data loss ADR 0009 exists to prevent. `'full'` isolates on both sides, so a keystroke
   *   afterwards cannot join the discard's event either.
   * - `basedOn` becomes the stored stamp, so the *next* save is guarded against the version now in
   *   the editor. Leaving it would refuse that save with the stale precondition it already refused.
   * - `dirty` is cleared **after** the dispatch, because the update listener sets it: the document
   *   now equals the stored body, so there is genuinely nothing unsaved.
   *
   * `appliedBody` is deliberately *not* touched. It means "the last body taken from the prop", and
   * this body did not come from the prop — writing it here would make a later re-render carrying the
   * (older) prop body look like an update and dispatch it straight over the version just chosen.
   */
  function keepTheirs(): void {
    const versions = conflict
    const current = view
    // `kit` is non-null whenever `view` is — a view can only exist because the module arrived — but
    // TypeScript cannot see that, and asserting it would be the one place a refactor could make the
    // claim false without anything complaining. `HISTORY_ISOLATION` lives in the lazy module because
    // `isolateHistory` is a `@codemirror/commands` value; see `lib/codemirror.ts`.
    const loaded = kit
    if (versions === null || current === undefined || loaded === null || saving) {
      return
    }
    syncDocument(current, versions.stored.body, loaded.HISTORY_ISOLATION)
    basedOn = versions.stored.updated_at
    dirty = false
    conflict = null
    movedAgain = false
    refusal = null
    saved = null
    resolution = 'kept theirs · your text is one undo away (⌘/Ctrl-Z) until you edit again'
  }

  /**
   * The one `PATCH` in this component, shared by the Save button and by "keep mine".
   *
   * One write path rather than two, so the precondition is forwarded the same way whichever button
   * asked — and so a future card cannot fix a bug in one of them. What differs between the callers is
   * only *which* body and *which* stamp go in, which is exactly what the parameter is.
   *
   * `conflict` is not cleared on the way in. The banner must survive its own resolution's round trip,
   * and a fresh `409` replaces it below rather than flickering through empty.
   */
  async function write(update: NoteUpdate): Promise<void> {
    const opened = note
    const current = view
    if (opened === null || current === undefined || saving) {
      return
    }

    saving = true
    refusal = null
    saved = null
    resolution = null
    try {
      const stored = await updateNote(opened.ref, update)
      // The next edit is based on the version the server just wrote. Straight off the response, still
      // an opaque string.
      basedOn = stored.updated_at
      // Against the body that was **sent**, not a flat `false`. A save is a round trip and you can
      // type during it; clearing the flag unconditionally would mark those keystrokes saved when the
      // request that finished had never seen them, and the next `409` would be a mystery. It is also
      // what leaves the pane honest after a "keep mine" the user typed past.
      dirty = current.state.doc.toString() !== update.body
      saved = `saved · now at ${stored.updated_at}`
      conflict = null
      movedAgain = false
      // KAN-562 reconciles `note_link` against the body a save just wrote, so this is the moment a
      // `[[...]]` typed since the last fetch can first have an answer — re-fetch rather than wait for
      // the note prop to change (it may not: saving the open note does not navigate away from it).
      loadLinks(stored.ref)
    } catch (failure) {
      if (failure instanceof ApiError && failure.isConflict) {
        const versions = conflictVersions(failure.details)
        // Two `stored` stamps apart, not "a second 409": a plain Save after a refusal re-sends the
        // same stale precondition and is refused identically, which is correct and is not news. The
        // note having moved *again* while the banner was open is.
        const previous = conflict?.stored.updated_at ?? null
        movedAgain = versions !== null && previous !== null && previous !== versions.stored.updated_at
        conflict = versions
        // A `409` whose extras did not parse is still a `409`. Say so rather than showing nothing.
        refusal = versions === null ? failure.message : null
      } else {
        refusal = failure instanceof Error ? failure.message : 'Could not save.'
      }
    } finally {
      saving = false
    }
  }

  /**
   * The Delete button's click handler: arm on the first click, delete on the second.
   *
   * Two clicks rather than a `confirm()` or a banner (BREADBOARD.md A2) — the button's own label
   * carries the question, so there is nothing else to build or to place. A click while a delete is
   * already in flight is a no-op rather than a second request.
   */
  function clickDelete(): void {
    if (deleting) {
      return
    }
    if (!deleteArmed) {
      deleteArmed = true
      return
    }
    void performDelete()
  }

  /** Disarm without deleting — the way out of a Delete clicked by mistake. */
  function cancelDelete(): void {
    deleteArmed = false
  }

  /**
   * The one `DELETE` in this component. No precondition to send (ADR 0009's guard is body-only, and
   * there is no body left to guard once the row is gone) and no `--force`-style override — deleting
   * twice in a row is refused by the server as a `404` the second time, which is already the correct
   * answer.
   */
  async function performDelete(): Promise<void> {
    const opened = note
    if (opened === null || deleting) {
      return
    }
    deleting = true
    deleteError = null
    try {
      await deleteNote(opened.ref)
      ondeleted?.(opened.ref)
    } catch (failure) {
      deleteError = failure instanceof Error ? failure.message : 'Could not delete.'
      deleteArmed = false
    } finally {
      deleting = false
    }
  }
</script>

<section class="pane" aria-label="Editor">
  {#if error}
    <p class="notice">{error}</p>
  {:else if note}
    <header>
      <h2>{note.title}</h2>
      <p class="meta">
        <code>{note.ref}</code>
        <!-- A note may legitimately have no path (ADR 0008: path is metadata, not identity), and
             two of the seeded notes do. Say so rather than rendering an empty element. -->
        <span class="path">{note.path === '' ? '(no path)' : note.path}</span>
        <!-- `basedOn` and not `note.updated_at`: after a save the prop is stale, and the version
             this edit is guarded against is the only honest thing to show here. -->
        <span class="stamp" title="ADR 0009's precondition, carried as an opaque string"
          >based on {basedOn}</span
        >
      </p>
    </header>

    <div class="bar">
      <button type="button" onclick={() => void save()} disabled={saving || !dirty}>
        {saving ? 'Saving…' : 'Save'}
      </button>
      <span class="hint">⌘/Ctrl-S</span>
      <span class="state" data-testid="save-state">
        <!-- `dirty` outranks `saved`, because you can type during a round trip: a save that
             finished is old news the moment the document moved past what it sent. -->
        {#if saving}
          saving…
        {:else if dirty}
          unsaved changes
        {:else if saved}
          {saved}
        {:else if resolution}
          <!-- A resolution that wrote nothing. It cannot say `saved`, because the server does not
               hold this text — see `keepTheirs`. -->
          {resolution}
        {:else}
          no changes
        {/if}
      </span>
      <button
        type="button"
        class="delete"
        onclick={clickDelete}
        disabled={deleting}
        data-testid="delete-button"
      >
        {#if deleting}
          Deleting…
        {:else if deleteArmed}
          Confirm delete?
        {:else}
          Delete
        {/if}
      </button>
      {#if deleteArmed && !deleting}
        <button type="button" class="delete-cancel" onclick={cancelDelete} data-testid="delete-cancel">
          Cancel
        </button>
      {/if}
    </div>

    {#if deleteError}
      <p class="conflict" data-testid="delete-error">{deleteError}</p>
    {/if}
  {:else}
    <p class="notice">Pick a note from the sidebar.</p>
  {/if}

  {#if conflict}
    <!--
      ADR 0009's affordance (KAN-556), and a **sibling** of the editor container below — never a
      child of it. PLAN §S9: Svelte renders nothing inside CM6's subtree, and a banner that grew into
      the editor's element would be the update loop with a friendly face.

      The banner writes nothing. This component owns the write path, the precondition and the view, so
      both buttons come back here: `keepMine` re-`PATCH`es and `keepTheirs` dispatches a transaction.
    -->
    <ConflictBanner
      versions={conflict}
      busy={saving}
      {movedAgain}
      onkeepmine={() => void keepMine()}
      onkeeptheirs={keepTheirs}
    />
  {/if}

  {#if refusal}
    <p class="conflict" data-testid="save-error">{refusal}</p>
  {/if}

  {#if unavailable}
    <!-- KAN-767's lazy chunk failing to arrive. A **sibling** of the container below, like every
         other message in this pane: the empty container is the honest rendering of "there is no
         editor", and a word of Svelte-owned text inside it would be PLAN §S9 broken by the notice
         that explains why S9's occupant is missing. -->
    <p class="conflict" data-testid="editor-unavailable">{unavailable}</p>
  {/if}

  <!--
    S9's container. Svelte owns this element and **never its children** — no {#if}, no {#each},
    no {@html}, no text interpolation may go inside it. `new EditorView({ parent })` is the only
    thing that writes in here, and `tests/editor-container.test.ts` asserts over this file's parsed
    template that it stays that way.
  -->
  <div class="editor-host" bind:this={host}></div>
</section>

<style>
  .pane {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    min-width: 0;
    height: 100%;
    padding: 1.5rem;
  }

  h2 {
    margin: 0;
    font-size: 1.35rem;
    letter-spacing: -0.01em;
  }

  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin: 0.35rem 0 0;
    color: var(--muted);
    font-size: 0.85rem;
  }

  .stamp {
    font-family: var(--mono);
  }

  .notice {
    margin: 0;
    color: var(--muted);
  }

  .bar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  button {
    padding: 0.35rem 0.9rem;
    border: 1px solid var(--edge);
    border-radius: 0.35rem;
    color: var(--paper);
    background: var(--accent);
    font: inherit;
    font-size: 0.85rem;
    cursor: pointer;
  }

  button:disabled {
    color: var(--muted);
    background: transparent;
    cursor: default;
  }

  .hint,
  .state {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.75rem;
  }

  .delete,
  .delete-cancel {
    background: transparent;
    color: var(--muted);
  }

  /* Pushed to the end of the bar, away from Save — a destructive control gets its own end of the
     row rather than sitting beside the one you press routinely. */
  .delete {
    margin-left: auto;
  }

  .delete:hover:not(:disabled) {
    border-color: color-mix(in srgb, #c0392b 55%, var(--edge));
    color: #c0392b;
  }

  .conflict {
    margin: 0;
    padding: 0.75rem 1rem;
    border: 1px solid var(--edge);
    border-left: 3px solid var(--accent);
    border-radius: 0.35rem;
    font-size: 0.85rem;
  }

  .editor-host {
    flex: 1;
    min-height: 12rem;
    overflow: auto;
    padding: 0.25rem 0;
    border: 1px solid var(--edge);
    border-radius: 0.4rem;
  }
</style>
