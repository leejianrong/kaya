<!--
  ADR 0009's `409`, as something a person can act on (KAN-556).

  The affordance the ADR promised — *"renders a conflict banner offering keep mine, keep theirs, or a
  side-by-side view"* — and without it the precondition is a status code nobody sees.

  Three things about this component are decisions rather than layout:

  - **It is a sibling of `EditorPane`'s editor container, never a child.** PLAN §S9 and ADR 0001 §2:
    Svelte renders nothing inside CM6's subtree, so the banner sits beside `<div class="editor-host">`
    in the pane's own flow. `tests/editor-container.test.ts` parses the pane and would name this
    component as a template child of the container if anyone moved it, and
    `tests/conflict-banner.test.ts` asserts the rendered banner is outside it with the live view
    untouched.
  - **It writes nothing and holds no state that outlives the conflict.** The two buttons call up into
    the pane, which owns the write path, the precondition and the `EditorView`. The only rune here is
    whether the comparison is expanded.
  - **"Mine" and "theirs" are this component's words.** The API says `attempted` and `stored` because
    the same `409` body reaches the CLI and a future MCP tool, where "mine" names nobody
    (`backend/app/api/concurrency.py`). The mapping is fixed there, not chosen here:
    `attempted` → mine, `stored` → theirs.
-->
<script lang="ts">
  import {
    compareMetadata,
    type ConflictVersions,
    splitOnChange,
  } from '../lib/conflict'

  const {
    versions,
    busy = false,
    movedAgain = false,
    onkeepmine,
    onkeeptheirs,
  }: {
    /** The two whole notes off the `409`. Both bodies arrive complete; see `concurrency.py`. */
    versions: ConflictVersions
    /** A resolution is in flight. Both buttons are one `PATCH` away from each other's outcome. */
    busy?: boolean
    /** The stored version changed *again* between one refusal and the next. See the pane. */
    movedAgain?: boolean
    /** Write `attempted.body` guarded on `stored.updated_at`. The pane does it; see `keepMinePatch`. */
    onkeepmine: () => void
    /** Discard the caller's text and take the stored body. No request at all. */
    onkeeptheirs: () => void
  } = $props()

  /**
   * Whether the two bodies are shown.
   *
   * **Open by default**, which is the one place this component takes a position. ADR 0009's whole
   * argument is that "your write was refused" is not actionable and that the caller needs both
   * versions in front of it; a comparison behind a button would make the destructive choice the
   * cheap one and the informed choice the extra click. The columns scroll inside their own box
   * instead, so a 3,000-word runbook does not push the editor off the screen.
   */
  let comparing = $state(true)

  const split = $derived(splitOnChange(versions.attempted.body, versions.stored.body))
  const identical = $derived(split.mine.changed === '' && split.theirs.changed === '')
  const metadata = $derived(compareMetadata(versions))
  /** `title Weekly review, path journal/2026/08/weekly-review.md` — see `compareMetadata`. */
  const agreed = $derived(
    metadata.agreed.map((field) => `${field.name} ${field.value === '' ? '(none)' : field.value}`),
  )
</script>

<section class="conflict" data-testid="conflict" role="alert" aria-label="Save conflict">
  <p class="lede">
    <strong>Not saved.</strong>
    {#if movedAgain}
      <!--
        The note moved again while the banner was open, so the version on the right is not the one
        this user read a moment ago. Saying so is the difference between "my click did nothing" and
        "someone is writing to this note right now".

        Its own `data-testid`, because the claim has to be assertable on its own: the static prose
        below contains the word "again" too, and a test searching the banner's text for it would
        pass whether this sentence rendered or not.
      -->
      <span data-testid="conflict-moved-again"
        >This note changed <strong>again</strong> while you were deciding, so nothing was written. The
        stored version below is the new one.</span
      >
    {:else}
      Someone else wrote to this note since you opened it, so nothing was written — not the body, and
      not the title or path if you had changed them either. ADR 0009 refuses a guarded write whole.
    {/if}
  </p>

  <p class="stamps">
    You edited the version stamped
    <code data-testid="conflict-attempted">{versions.attempted.updated_at}</code>; the stored version
    is <code data-testid="conflict-stored">{versions.stored.updated_at}</code>.
  </p>

  <div class="actions">
    <!--
      `type="button"` on all three: this component is rendered inside no form today, and a default
      submit button that finds one tomorrow navigates the page away from an unsaved note.
    -->
    <button type="button" onclick={onkeepmine} disabled={busy} data-testid="conflict-keep-mine">
      {busy ? 'Writing…' : 'Keep mine'}
    </button>
    <button type="button" onclick={onkeeptheirs} disabled={busy} data-testid="conflict-keep-theirs">
      Keep theirs
    </button>
    <button
      type="button"
      onclick={() => (comparing = !comparing)}
      aria-expanded={comparing}
      data-testid="conflict-toggle"
    >
      {comparing ? 'Hide side by side' : 'Side by side'}
    </button>
  </div>

  <p class="warning">
    <strong>Keep mine</strong> writes your text over theirs, guarded on the stored version so it
    fails the same way again if the note moves once more.
    <strong>Keep theirs</strong>
    makes no request at all — it replaces the editor's document with the stored body and throws your
    text away. There is no revision history (ADR 0009), so until you type again your only copy of it
    is the editor's undo: <kbd>⌘/Ctrl-Z</kbd>.
  </p>

  {#if comparing}
    <div class="compare" data-testid="conflict-side-by-side">
      <div class="side">
        <h3>Mine <span class="tag">not written</span></h3>
        <!--
          Three text segments, and the middle one is the region that provably contains every
          difference (`splitOnChange` — a bound, not a diff). Written on one line with no spaces
          between the tags because this is a `<pre>`: Svelte preserves whitespace in here, so a
          prettier layout would insert newlines the note does not have. `tests/conflict-banner.test.ts`
          asserts each `<pre>`'s text is the body byte for byte.
        -->
        <pre
          class="body"
          data-testid="conflict-mine-body">{split.mine.before}<mark>{split.mine.changed}</mark>{split.mine.after}</pre>
      </div>
      <div class="side">
        <h3>Theirs <span class="tag">stored now</span></h3>
        <pre
          class="body"
          data-testid="conflict-theirs-body">{split.theirs.before}<mark>{split.theirs.changed}</mark>{split.theirs.after}</pre>
      </div>
    </div>

    {#if identical}
      <!-- Reachable: a write that only *touched* the body carries it, and ADR 0009 guards on the
           field being present rather than on its value having changed. Without this line the user
           stares at two identical panes looking for the difference. -->
      <p class="note" data-testid="conflict-identical">
        The two bodies are identical — someone else's write moved the version stamp without changing
        the text you were editing.
      </p>
    {/if}

    {#if agreed.length > 0}
      <!-- `concurrency.py`'s second "looks like a bug and is not": the fields a write did not send
           are filled from the *stored* note on both sides, because kaya never saw this caller's base
           version. So they are listed once, as shared, rather than as two identical columns
           inviting a choice between them. -->
      <p class="note" data-testid="conflict-agreed">
        Both versions agree on {agreed.join(', ')} — your write did not change those, and the
        refusal fills them in from the stored note on both sides, so identical here is correct rather
        than a bug.
      </p>
    {/if}

    {#each metadata.differing as field (field.name)}
      <p class="note" data-testid="conflict-differing">
        <code>{field.name}</code>: mine <code>{field.mine}</code>, theirs <code>{field.theirs}</code
        >. <strong>Keep mine</strong> writes the body only, so this stays as theirs either way.
      </p>
    {/each}
  {/if}
</section>

<style>
  .conflict {
    padding: 0.75rem 1rem;
    border: 1px solid var(--edge);
    border-left: 3px solid var(--accent);
    border-radius: 0.35rem;
    font-size: 0.85rem;
  }

  .lede,
  .stamps,
  .warning,
  .note {
    margin: 0 0 0.5rem;
  }

  .stamps,
  .warning,
  .note {
    color: var(--muted);
  }

  .stamps {
    font-size: 0.8rem;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin: 0.75rem 0;
  }

  button {
    padding: 0.3rem 0.7rem;
    border: 1px solid var(--edge);
    border-radius: 0.3rem;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    font-size: 0.8rem;
  }

  button[data-testid='conflict-keep-mine'] {
    border-color: var(--accent);
    color: var(--accent);
  }

  button:disabled {
    color: var(--muted);
    border-color: var(--edge);
    cursor: default;
  }

  .compare {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
    gap: 0.75rem;
  }

  .side {
    min-width: 0;
  }

  h3 {
    display: flex;
    gap: 0.4rem;
    align-items: baseline;
    margin: 0 0 0.3rem;
    font-size: 0.85rem;
  }

  .tag {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.7rem;
    font-weight: 400;
  }

  /* Scrolls inside its own box rather than growing: the banner sits above the editor, and a long
     note would otherwise push the thing you are deciding about off the screen. */
  .body {
    max-height: 14rem;
    margin: 0;
    overflow: auto;
    padding: 0.5rem;
    border: 1px solid var(--edge);
    border-radius: 0.3rem;
    color: var(--ink);
    font-family: var(--mono);
    font-size: 0.75rem;
    /* The bodies are prose and the columns are narrow, so wrapping beats a horizontal scrollbar per
       column — but `pre-wrap`, never `pre-line`, which collapses runs of spaces and would render a
       markdown code block as something the note does not contain. */
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  mark {
    background: color-mix(in srgb, var(--accent) 22%, transparent);
    color: inherit;
  }

  kbd {
    font-family: var(--mono);
    font-size: 0.75rem;
  }
</style>
