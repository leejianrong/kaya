<script lang="ts">
  import { untrack } from 'svelte'

  import { ApiError } from '../lib/api'
  import { backlinkLabel, needsFetch, panelState, type PanelState } from '../lib/backlinks'
  import { listBacklinks } from '../lib/notes'
  import { interceptClick, routeHref } from '../lib/router'
  import type { Note } from '../lib/types'

  /**
   * KAN-568's backlinks rail: every note whose body links to the one that is open.
   *
   * SLICES §V5 build-plan step 8, and the demo sentence it serves is *"`kaya backlinks NOTE-3` lists
   * every note linking to it, answered from kaya's own database with pandan down"* — in a browser.
   *
   * ## Three things this component is, said before the mechanics
   *
   * **It is a fourth region of the shell rather than a third pane of `main`** (`App.svelte`'s grid).
   * The two arguments are in that file; the one that belongs here is that a rail placed inside
   * `main` would be a sibling of `{#if previewing}`, and KAN-554 and KAN-962 both paid for the rule
   * that a command about one pane must not disturb another's state. Outside `main` the preview toggle
   * cannot reach this component at all — a *structural* version of the property `EditorPane` gets by
   * being carefully placed.
   *
   * **It reads `Note[]`, not a link record.** `GET /notes/{ref}/backlinks` answers with the same
   * `NoteList` a plain list does (`backend/app/api/links.py`), so `lib/notes.ts` gained one function
   * and `lib/types.ts` gained nothing. A row here is a note, addressed by its ref, and clicking it is
   * the same navigation a sidebar row is.
   *
   * **It shows only inbound links, and `/links` is deliberately not in this rail.** Outbound
   * wikilinks are KAN-567's, rendered as pills *in the document* where the resolved title and column
   * decorate the link a person actually typed; a second listing of the same edges here would be that
   * card's data with worse words. It also matters for what this panel demonstrates: `/links` resolves
   * `KAN-`/`EPIC-` refs against pandan and degrades when pandan is away, while `/backlinks` is a join
   * over two of kaya's own tables and cannot. Putting a degradable list beside a non-degradable one,
   * under one heading, is how R5.1 stops being observable.
   *
   * ## What it does about payload shaping, which is nothing
   *
   * ADR 0004 §Decision exempts this consumer in writing, and `lib/api.ts`'s header says what that
   * does and does not license. No projection, no truncation hint, no `{"count": n}`. The number
   * beside the heading is `panel.notes.length` — a **label on rows already on screen**, which is the
   * call `Sidebar.svelte` already made for its `no path` group and for the same reason. Worth being
   * exact about, because it would be easy to think the count comes from the payload: it does not, and
   * it could not — `NoteList` is `{"notes": [...]}` and `backend/app/api/schemas.py` records that
   * `summary` is deliberately absent from it, because the aggregate is attached inside `render()` and
   * is therefore `kaya-client`'s, not the API's.
   */
  const {
    note,
    onexpired,
  }: {
    note: Note | null
    /**
     * The API refused the credential. **The one failure this component may not handle itself.**
     *
     * `App.svelte` owns the credential lifecycle — acquiring one changes which region renders, and
     * losing one is discovered by a `401` on a request the landing state never made — so a `401`
     * here has to reach `discard()` there rather than being absorbed into {@link failure}. Keyed on
     * the **status**, never on the error code, for the reason `kaya-cli/failures.py` gives: the
     * backend's code vocabulary grows without this client's knowledge, and `authentication_required`
     * and `invalid_token` are already two codes for one meaning.
     */
    onexpired: (reason: string) => void
  } = $props()

  /**
   * The ref whose answer this panel is holding or waiting for — **and the guard's memory as well.**
   *
   * A rune, because the markup renders it: a zero state that does not name its note cannot be told
   * from the previous note's zero state still on screen, and the fetch is asynchronous so the prop
   * moves first. Reading `note.ref` in the markup instead would be a value that changes one flush
   * before the rows it sits above.
   *
   * The effect below reads it through **`untrack`**, which is what stops one variable from having to
   * be two. `EditorPane` keeps `mountedRef` as a plain `let` precisely because "a rune an effect both
   * reads and writes is an effect that retriggers itself"; that argument is about the *read* being
   * tracked, so untracking the read buys the same property without a second copy of the same value
   * to keep in step. The rule is unchanged — this effect does not depend on its own output.
   */
  let subject: string | null = $state(null)

  /** Whether a request is in flight. Beats every other state but `closed`; see `panelState`. */
  let loading = $state(false)

  /** The last failure's prose, or `null`. The API's own message, used verbatim. */
  let failure: string | null = $state(null)

  /** The rows the last successful request returned, in the order it returned them. */
  let found: Note[] = $state([])

  /**
   * The request in flight, if any. **A plain `let`, and it is not aborted from an effect cleanup.**
   *
   * That is `EditorPane`'s teardown lesson at one remove. Svelte runs an effect's cleanup *before*
   * every re-run, and the effect below re-runs whenever the parent hands down a new `note` object —
   * which is the case the identity guard exists to survive. An `AbortController` cancelled from that
   * cleanup would therefore kill an in-flight request on exactly the re-run that is supposed to be a
   * no-op, and the panel would sit on `Loading…` forever with nothing in the DOM to explain it. So
   * the supersede is in {@link load}, immediately beside the request it replaces, and the
   * per-component abort is the second effect below — the one that reads nothing, whose cleanup can
   * only fire on unmount.
   *
   * It doubles as the staleness check: a settled promise applies its result only while
   * `inflight === abort`. Two requests really can be in flight across a fast navigation, and
   * `AbortController` does not order their rejections, so without it a superseded request's
   * `loading = false` lands on top of a live one. Keyed on the **controller's identity** rather than
   * on the ref, because `refresh()` reloads the *same* ref and a ref comparison cannot tell those two
   * apart.
   */
  let inflight: AbortController | undefined

  /** The rail's whole rendering, as one closed value. See `lib/backlinks.ts`. */
  const panel: PanelState = $derived(panelState({ ref: subject, loading, failure, notes: found }))

  /**
   * Ask the API about one ref, replacing whatever was in flight.
   *
   * `found` and `failure` are cleared **before** the request rather than after it, which is the other
   * half of `panelState`'s precedence: a failed refresh must not be able to render the previous
   * answer's rows underneath a "could not load" line, and rows a reader takes as current are worse
   * than no rows at all.
   */
  function load(ref: string): void {
    inflight?.abort()
    const abort = new AbortController()
    inflight = abort
    subject = ref
    found = []
    failure = null
    loading = true
    listBacklinks(ref, { signal: abort.signal }).then(
      (notes) => {
        if (inflight === abort) {
          found = notes
          loading = false
        }
      },
      (error: unknown) => {
        if (inflight === abort) {
          absorb(error)
          loading = false
        }
      },
    )
  }

  /**
   * Ask again for the note already on screen.
   *
   * **There is deliberately no automatic refresh, and the reason is that inbound links are not this
   * tab's to observe.** A note's backlinks change when *another* note's body changes, which happens
   * in another tab, another session or an agent's `kaya note edit`, and this app is not told. A panel
   * that refetched after a save would therefore be right about exactly one of the ways it can go
   * stale — the narrow one where the open note links to its own title, which
   * `backend/app/api/links.py` documents as a real backlink rather than a special case — and silently
   * wrong about the rest, while *looking* live. An always-available button that says what it does is
   * the honest version of the same feature, and it doubles as the recovery path out of `failed`.
   *
   * It does not go through {@link needsFetch}, because it is asking for the ref the guard would
   * refuse: the guard's job is to stop a *re-render* from refetching, not to stop a person.
   */
  function refresh(): void {
    if (subject !== null) {
      load(subject)
    }
  }

  /**
   * A failure, sorted into "the credential is no good" and everything else.
   *
   * The same split `App.svelte`'s `absorb` makes, on the same key, and the same reason it is a status
   * rather than a code. Everything that is not a `401` stays here: a `404` (the note was deleted from
   * under this tab), a `503`, a transport failure. The API's `message` is used verbatim — it is
   * written for a person and no refusal echoes an `Authorization` header — and nothing on this path
   * reads the request, the headers or the credential, so there is no route by which a token reaches
   * this string and therefore the DOM.
   */
  function absorb(error: unknown): void {
    if (error instanceof ApiError && error.isUnauthenticated) {
      onexpired(error.message)
      return
    }
    failure = error instanceof Error ? error.message : 'Could not load backlinks.'
  }

  /**
   * Fetch when the **note** changes, and never when its content does.
   *
   * **Reading the `note` prop registers the whole prop**, so this effect re-runs whenever the parent
   * hands down a new object, whatever moved inside it — `note.ref` and `note.body` are one signal, so
   * reading a narrower field buys nothing. What stops that from becoming a request per keystroke is
   * {@link needsFetch}, which compares the incoming ref against {@link subject}: the identity guard,
   * `lib/editor.ts`'s `needsRemount` one component over, and a pure function for the same reason.
   *
   * The `null` arm is not the same as the guard returning early. "No note" is a state this panel has
   * a rendering for (`closed`), and arriving at it has to cancel a request the previous note started
   * — otherwise a navigation home lands the old note's rows in the rail a moment later.
   */
  $effect(() => {
    const opened = note
    const incoming = opened?.ref ?? null
    if (!needsFetch(untrack(() => subject), incoming)) {
      return
    }
    if (incoming === null) {
      inflight?.abort()
      inflight = undefined
      subject = null
      found = []
      failure = null
      loading = false
      return
    }
    load(incoming)
  })

  /**
   * The component's one once-per-lifetime job: **let go of the request on the way out.**
   *
   * Reads nothing, so it runs exactly once and its cleanup fires only on unmount — which is what
   * makes it the only safe place for the abort (see {@link inflight}). `inflight = undefined` is not
   * housekeeping: it is what makes the settled promise's `inflight === abort` check false, so a
   * response arriving after unmount assigns no rune.
   */
  $effect(() => {
    return () => {
      inflight?.abort()
      inflight = undefined
    }
  })
</script>

<aside class="rail" aria-label="Backlinks">
  <header>
    <h2>Backlinks</h2>
    {#if panel.kind === 'listed'}
      <!-- A label on the rows below it, not an aggregate over a payload — see the docstring, and
           `Sidebar.svelte`'s `no path` count, which is the same call. -->
      <span class="count" data-testid="backlinks-count">{panel.notes.length}</span>
    {/if}
    {#if panel.kind !== 'closed'}
      <button
        type="button"
        class="refresh"
        onclick={refresh}
        disabled={panel.kind === 'loading'}
        data-testid="backlinks-refresh"
      >
        Refresh
      </button>
    {/if}
  </header>

  <!--
    Five arms, one per state, and they are five rather than three because "nothing links here" and
    "the request failed" must not be able to share a sentence. `panelState` is what makes them a
    closed union: collapsing two of them into one `{:else}` stops type-checking rather than merely
    reading badly.
  -->
  {#if panel.kind === 'closed'}
    <p class="empty" data-testid="backlinks-closed">Open a note to see what links to it.</p>
  {:else if panel.kind === 'loading'}
    <p class="empty" data-testid="backlinks-loading">Loading…</p>
  {:else if panel.kind === 'failed'}
    <p class="notice" data-testid="backlinks-error">
      Could not load backlinks for {panel.ref}: {panel.message}
    </p>
  {:else if panel.kind === 'empty'}
    <p class="empty" data-testid="backlinks-empty">Nothing links to {panel.ref} yet.</p>
    <!-- The zero state's second job: say how a backlink is made. A note gets here by mentioning
         this one's title in its body, and `note_link.resolved_id` is what makes the edge survive a
         rename of either end (`app/auth/authorization.py`). -->
    <p class="hint">Another note gets here by mentioning its title in <code>[[…]]</code>.</p>
  {:else}
    <ul data-testid="backlinks">
      {#each panel.notes as linking (linking.ref)}
        <li>
          <a
            class="row"
            href={routeHref({ name: 'note', ref: linking.ref })}
            onclick={(event) => interceptClick(event, `/notes/${linking.ref}`)}
          >
            <!-- Text interpolation, so every byte of a title another person wrote becomes a text
                 node. There is no `{@html}` here and there is none anywhere in `src/`;
                 `tests/no-html-injection.test.ts` asserts that over parsed ASTs. A backlink's title
                 is user-authored content from a *different* note, which makes this the one surface
                 in the app that renders somebody else's prose without the preview's renderer in
                 front of it. -->
            <span class="title">{backlinkLabel(linking)}</span>
            <!-- `path` is legitimately empty (ADR 0008), and an em dash beats a blank line that
                 reads as a rendering bug. Same call as the sidebar's flat list. -->
            <span class="sub">{linking.path === '' ? '—' : linking.path}</span>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</aside>

<style>
  .rail {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    min-width: 0;
    overflow-y: auto;
    padding: 1rem 0.5rem 1.5rem;
    border-left: 1px solid var(--border);
  }

  header {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    padding: 0 0.5rem;
  }

  h2 {
    margin: 0;
    color: var(--muted);
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .count {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.7rem;
  }

  .refresh {
    margin-left: auto;
    padding: 0.15rem 0.45rem;
    border: 1px solid var(--border);
    border-radius: 0.3rem;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: 0.65rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .refresh:disabled {
    cursor: default;
    opacity: 0.5;
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .row {
    display: block;
    min-width: 0;
    padding: 0.3rem 0.5rem;
    border-radius: 0.3rem;
    color: inherit;
    text-decoration: none;
  }

  .row:hover {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
  }

  .title {
    display: block;
    overflow: hidden;
    font-size: 0.85rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sub {
    display: block;
    overflow: hidden;
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.7rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .empty,
  .hint {
    margin: 0;
    padding: 0 0.5rem;
    color: var(--muted);
    font-size: 0.8rem;
  }

  .hint {
    font-size: 0.7rem;
    line-height: 1.4;
  }

  .hint code {
    font-family: var(--mono);
  }

  /* Same shape as the editor's and the preview's failure notices, so the three read as one app. */
  .notice {
    margin: 0 0.25rem;
    padding: 0.6rem 0.75rem;
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 0.35rem;
    font-size: 0.8rem;
  }
</style>
