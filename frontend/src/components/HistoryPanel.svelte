<script lang="ts">
  import { untrack } from 'svelte'

  import { ApiError } from '../lib/api'
  import { isSelected, needsFetch, panelState, type PanelState } from '../lib/history'
  import { listVersions, restoreVersion } from '../lib/notes'
  import type { Note, NoteVersion } from '../lib/types'

  /**
   * R13/KAN-1064/1065/1066's History tab: every body a note's `POST`/`PATCH` has ever written,
   * click one to preview it, Restore to write it back.
   *
   * **`BacklinksPanel.svelte`'s twin**, deliberately built to the same shape rather than a fresh
   * one invented for this card — same five-state `panelState`, same identity guard, same
   * `AbortController` supersede-in-`load` / abort-on-unmount split, same `401` handoff to
   * `App.svelte`'s `onexpired`. `RightRail.svelte` is what makes the two siblings under one tab
   * strip rather than a component picking its own placement; this file owns only what is different
   * about *this* tab's data — a click selects a row instead of navigating, and there is a write.
   *
   * **Full bodies, not snippets**, matching `backend/app/api/schemas.py`'s `NoteVersionRead` design
   * call: the list response already carries every version's whole text, so "preview" here is
   * choosing which one of `found` to show, never a second request.
   *
   * **Restore is `restoreVersion`, sugar over the same `PATCH` the editor's own Save button uses**
   * (`lib/notes.ts`), and it is *always* guarded: `opened.updated_at` — the freshest value this
   * component has, straight off the `note` prop — goes in as `if_updated_at` on every restore, so a
   * restore that races a concurrent edit gets ADR 0009's `409` exactly like any other write
   * (BREADBOARD.md's R13, and `tests/integration/test_note_versions_api.py`'s
   * `test_a_stale_precondition_on_a_restore_is_a_409_exactly_like_any_other_edit`). There is no
   * "force restore" the way there is no `--force` anywhere else in this product (ADR 0009).
   */
  const {
    note,
    onexpired,
    onrestored,
  }: {
    note: Note | null
    /** The API refused the credential — handed to `App.svelte`, which owns the credential
     *  lifecycle. See `BacklinksPanel`'s identical prop for the full argument. */
    onexpired: (reason: string) => void
    /**
     * A restore succeeded. **Not the same seam as `EditorPane`'s `onupdated`.** That one updates
     * only the sidebar's `notes` row, because a title/path-only save never changes what the editor
     * is already showing. A restore changes `body`, and the editor did not type it — so this seam
     * has to also reach the open `note` itself, which is what makes `EditorPane`'s own external-
     * update path (`lib/editor.ts`'s `syncDocument`) push the restored text into the live view.
     * `App.svelte` is what does both; see its `noteRestored`.
     */
    onrestored: (stored: Note) => void
  } = $props()

  /** The ref whose answer this tab is holding or waiting for — see `BacklinksPanel`'s identical
   *  field for the full argument (it doubles as the identity guard's memory). */
  let subject: string | null = $state(null)

  /** Whether a request is in flight. Beats every other state but `closed`; see `panelState`. */
  let loading = $state(false)

  /** The last list failure's prose, or `null`. The API's own message, used verbatim. */
  let failure: string | null = $state(null)

  /** The rows the last successful request returned, in the order it returned them. */
  let found: NoteVersion[] = $state([])

  /** The request in flight, if any. See `BacklinksPanel`'s identical field for why the abort lives
   *  in {@link load} and not in this effect's cleanup. */
  let inflight: AbortController | undefined

  /** The id of the version currently previewed, or `null` for none. Cleared on every fetch — a
   *  selection naming a row from the *previous* note would be a stale preview wearing a new note's
   *  chrome. */
  let selected: number | null = $state(null)

  /** Whether a restore request is in flight. */
  let restoring = $state(false)

  /** The last restore failure's prose, or `null`. Cleared whenever a new row is selected or a
   *  restore starts, so a stale refusal cannot sit under a different selection. */
  let restoreFailure: string | null = $state(null)

  /** The tab's whole rendering, as one closed value. See `lib/history.ts`. */
  const panel: PanelState = $derived(
    panelState({ ref: subject, loading, failure, versions: found }),
  )

  /** The selected row itself, or `null` — derived rather than stored twice, so `selected` (an id)
   *  and the row it names can never disagree. */
  const selectedVersion = $derived(found.find((version) => isSelected(selected, version)) ?? null)

  /**
   * Ask the API about one ref, replacing whatever was in flight. See `BacklinksPanel.load` for the
   * precedence this follows (`found`/`failure` cleared before the request, staleness keyed on the
   * controller's identity).
   */
  function load(ref: string): void {
    inflight?.abort()
    const abort = new AbortController()
    inflight = abort
    subject = ref
    found = []
    failure = null
    selected = null
    restoreFailure = null
    loading = true
    listVersions(ref, { signal: abort.signal }).then(
      (versions) => {
        if (inflight === abort) {
          found = versions
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

  /** Ask again for the note already on screen — the recovery path out of `failed`, and how a fresh
   *  restore's own new version shows up without a second, bespoke re-fetch. */
  function refresh(): void {
    if (subject !== null) {
      load(subject)
    }
  }

  /** A failure, sorted into "the credential is no good" and everything else — see `BacklinksPanel`'s
   *  identical `absorb` for the full argument. */
  function absorb(error: unknown): void {
    if (error instanceof ApiError && error.isUnauthenticated) {
      onexpired(error.message)
      return
    }
    failure = error instanceof Error ? error.message : 'Could not load history.'
  }

  /** Toggle a row's selection: clicking the one already previewed closes the preview. */
  function toggle(version: NoteVersion): void {
    selected = isSelected(selected, version) ? null : version.id
    restoreFailure = null
  }

  /**
   * Write the selected version's body back, guarded by the open note's own `updated_at`.
   *
   * A no-op while nothing is selected, no note is open, or a restore is already in flight — the
   * button is disabled for the same three reasons, this is the defence for a click that lands
   * anyway (a queued double-click, a test dispatching the handler directly).
   */
  async function restore(): Promise<void> {
    const opened = note
    const chosen = selectedVersion
    if (opened === null || chosen === null || restoring) {
      return
    }
    restoring = true
    restoreFailure = null
    try {
      const stored = await restoreVersion(opened.ref, chosen.body, opened.updated_at)
      onrestored(stored)
      selected = null
      // The restore itself cut a new version (`app/note_versions.py`'s `cut_version` does not know
      // or care that this write was a restore) — refresh so it appears rather than waiting for some
      // other reason to re-open this tab.
      refresh()
    } catch (error) {
      if (error instanceof ApiError && error.isUnauthenticated) {
        onexpired(error.message)
      } else if (error instanceof ApiError && error.isConflict) {
        restoreFailure = error.message
      } else {
        restoreFailure = error instanceof Error ? error.message : 'Could not restore.'
      }
    } finally {
      restoring = false
    }
  }

  /** Fetch when the **note** changes, and never when its content does — see `BacklinksPanel`'s
   *  identical effect for the full argument; nothing about it changes for this tab. */
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
      selected = null
      restoreFailure = null
      return
    }
    load(incoming)
  })

  /** Let go of the request on the way out. See `BacklinksPanel`'s identical effect. */
  $effect(() => {
    return () => {
      inflight?.abort()
      inflight = undefined
    }
  })
</script>

<div class="history" aria-label="History">
  <header>
    {#if panel.kind === 'listed'}
      <span class="count" data-testid="history-count">{panel.versions.length}</span>
    {/if}
    {#if panel.kind !== 'closed'}
      <button
        type="button"
        class="refresh"
        onclick={refresh}
        disabled={panel.kind === 'loading'}
        data-testid="history-refresh"
      >
        Refresh
      </button>
    {/if}
  </header>

  {#if panel.kind === 'closed'}
    <p class="empty" data-testid="history-closed">Open a note to see its history.</p>
  {:else if panel.kind === 'loading'}
    <p class="empty" data-testid="history-loading">Loading…</p>
  {:else if panel.kind === 'failed'}
    <p class="notice" data-testid="history-error">
      Could not load history for {panel.ref}: {panel.message}
    </p>
  {:else if panel.kind === 'empty'}
    <p class="empty" data-testid="history-empty">No saved versions yet.</p>
  {:else}
    <ul data-testid="history-versions">
      {#each panel.versions as version, index (version.id)}
        <li>
          <button
            type="button"
            class="row"
            class:selected={isSelected(selected, version)}
            onclick={() => toggle(version)}
            data-testid="history-row"
          >
            <span class="when">{new Date(version.created_at).toLocaleString()}</span>
            {#if index === 0}
              <span class="current">current</span>
            {/if}
          </button>
        </li>
      {/each}
    </ul>

    {#if selectedVersion !== null}
      <div class="preview" data-testid="history-preview">
        <pre>{selectedVersion.body}</pre>
        <button
          type="button"
          class="restore"
          onclick={restore}
          disabled={restoring}
          data-testid="history-restore"
        >
          {restoring ? 'Restoring…' : 'Restore this version'}
        </button>
        {#if restoreFailure !== null}
          <p class="notice" data-testid="history-restore-error">{restoreFailure}</p>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  .history {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    min-width: 0;
  }

  header {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    padding: 0 0.5rem;
  }

  .count {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.7rem;
  }

  .refresh,
  .restore {
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

  .refresh {
    margin-left: auto;
  }

  .refresh:disabled,
  .restore:disabled {
    cursor: default;
    opacity: 0.5;
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .row {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    width: 100%;
    padding: 0.3rem 0.5rem;
    border: none;
    border-radius: 0.3rem;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    text-align: left;
  }

  .row:hover {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
  }

  .row.selected {
    background: color-mix(in srgb, var(--accent) 18%, transparent);
  }

  .when {
    overflow: hidden;
    font-size: 0.8rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .current {
    padding: 0.05rem 0.3rem;
    border-radius: 0.2rem;
    background: color-mix(in srgb, var(--accent) 25%, transparent);
    color: var(--muted);
    font-size: 0.6rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .preview {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    margin: 0 0.5rem;
    padding: 0.5rem;
    border: 1px solid var(--border);
    border-radius: 0.35rem;
  }

  .preview pre {
    max-height: 14rem;
    margin: 0;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: var(--mono);
    font-size: 0.75rem;
  }

  .restore {
    align-self: flex-start;
  }

  .empty {
    margin: 0;
    padding: 0 0.5rem;
    color: var(--muted);
    font-size: 0.8rem;
  }

  /* Same shape as the editor's and the backlinks rail's failure notices, so every notice in the
     shell reads as one system. */
  .notice {
    margin: 0 0.25rem;
    padding: 0.6rem 0.75rem;
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 0.35rem;
    font-size: 0.8rem;
  }
</style>
