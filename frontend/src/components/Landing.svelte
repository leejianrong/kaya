<!--
  What a visitor with no credential sees, and the one-time PAT paste (KAN-555).

  This component is small and its discipline is not. It is the only place in the product where a
  live credential exists as a value a person typed, so every choice about the input element is a
  deliberate one and is written down beside it. `lib/auth.ts` holds the rule those choices serve:
  **the token never enters a URL, a log line, an error message, or the DOM.**

  Nothing here validates the token against pandan. It is stored, the shell advances, and the note
  list's own request is what says whether it works — a `401` comes back to this component as
  `rejected`. Verifying here first would mean two code paths that can produce a `401` and two
  places to keep the recovery honest, for one saved round trip on the failure case only.
-->
<script lang="ts">
  import { isUsableToken, setToken } from '../lib/auth'
  import { fetchMeta, pandanHref } from '../lib/meta'

  const {
    rejected = null,
    onaccept,
  }: {
    /**
     * Why the last credential was refused, in the API's own words, or `null`.
     *
     * The shell has already cleared the token by the time this arrives (a `401` state you cannot
     * leave without devtools is a bug), so this is a message and not a state — the form below is
     * always ready.
     */
    rejected?: string | null
    /** The token is stored; the shell may proceed. Called only after `setToken`. */
    onaccept: () => void
  } = $props()

  /** The pandan origin, from `GET /api/v1/meta`. `null` until it arrives, or if it never does. */
  let origin: string | null = $state(null)
  let asking = $state(true)

  /**
   * The field's contents. A credential, while it is being typed.
   *
   * It is a plain `$state` string and it is bound to the input's **value property** — never to a
   * `value` attribute, and never interpolated into text or into any other attribute. That is what
   * keeps it out of `document.body.innerHTML`, which is what a devtools copy, an HTML snapshot and
   * a bug reporter's "copy outer HTML" all read. `tests/landing.test.ts` sweeps that serialization
   * for every four-character fragment of a fake token, mid-paste as well as after submit.
   */
  let pasted = $state('')

  /** Why the last paste was not even storable. Never contains the value it is about. */
  let problem: string | null = $state(null)

  $effect(() => {
    const abort = new AbortController()
    fetchMeta({ signal: abort.signal })
      .then((meta) => (origin = pandanHref(meta.pandan_url)))
      // Deliberately empty, and deliberately not `console.error(error)`: nothing is logged on any
      // path in this component. The failure is already visible — no link — and the fallback text
      // below says what to do instead. Q41/Q42's rule is about the token, and the discipline of
      // "this component logs nothing" is cheaper to keep than a per-call judgement about whether
      // some particular error object was built from a request that carried one.
      .catch(() => (origin = null))
      .finally(() => (asking = false))
    return () => abort.abort()
  })

  function submit(event: SubmitEvent): void {
    // First statement in the handler. A form with no `method` submits as GET, which would put the
    // credential in the address bar, in history and in the backend's request line — the exact
    // failure `lib/api.ts` refuses for every other request. The `method="post"` below and the
    // missing `name=` on the input are the two backstops for the day this line is edited.
    event.preventDefault()

    const candidate = pasted
    // Cleared *before* the branch, not in an `else`, so no path through this function leaves the
    // credential in the field. The clipboard still has it, which is the whole reason this is
    // affordable: a re-paste costs one keystroke and a stale credential in a text field costs a
    // screen share.
    pasted = ''

    if (!isUsableToken(candidate)) {
      // Says nothing about the value — not its length, not its first characters, not what was
      // wrong with it beyond the category. A message that quoted the input would be this card's
      // rule broken by the error path, which is where it usually breaks.
      problem = 'That cannot be used as a credential. Paste the token again.'
      return
    }

    problem = null
    setToken(candidate)
    onaccept()
  }
</script>

<main class="landing">
  <h1>kaya</h1>
  <p class="lede">
    Cloud-hosted markdown notes, API-first. Every action in this app is a plain
    <code>/api/v1</code> call, so the notes you write here are the same notes the
    <code>kaya</code> command-line tool reads and writes.
  </p>

  <section aria-labelledby="identity">
    <h2 id="identity">Identity comes from pandan</h2>
    <p>
      kaya mints no credentials of its own. It authenticates you by asking
      {#if origin}<a href={origin} target="_blank" rel="noopener noreferrer">pandan</a>{:else}pandan{/if},
      the board this app is paired with, so one account and one token span both.
      <!--
        Not "the kanban board", and the reason is the fragment sweep rather than style: the fake
        credential in `tests/token.ts` is prefixed `kanban_pat_` — a real, still-accepted pandan
        prefix — so the word `kanban` in this page contains four-character fragments of it
        (`kanb`, `anba`, `nban`) and every sweep over the rendered DOM would report a leak. The
        collision is the sweep working exactly as designed: it cannot know which occurrence of
        `kanb` came from a credential. Keeping the copy clear of it keeps the guard at full width
        instead of teaching the next person to add an exception to it.
      -->
      Sign-in through a shared browser session is deferred: it needs both apps under one apex
      domain, and
      <code>fly.dev</code> is on the Public Suffix List, so today's two origins cannot share a
      cookie at all.
    </p>

    <ol class="steps">
      <li>
        {#if origin}
          <!-- The origin only, with no path. Pandan's SPA holds its Tokens tab in component state
               and gives it no URL of its own, so there is nothing to deep-link to; a guessed path
               would be a broken link that looks like kaya's fault. -->
          Open <a href={origin} target="_blank" rel="noopener noreferrer">{origin}</a> and sign in.
        {:else if asking}
          Open pandan and sign in.
        {:else}
          <!-- `/api/v1/meta` did not answer, so this SPA does not know which pandan it is paired
               with. Saying so is better than naming one: a self-hosted deployment is supported
               (ADR 0002) and a hard-coded origin would send its users to the wrong place. -->
          Open your pandan deployment and sign in. (kaya could not reach its own API to look up
          which one that is, so there is no link here.)
        {/if}
      </li>
      <li>Open the <strong>Tokens</strong> tab and create a token.</li>
      <li>Paste it below.</li>
    </ol>
  </section>

  {#if rejected}
    <!-- The API's own prose for a refusal it produced. The backend never puts a credential in a
         message, and nothing here builds one out of a request. -->
    <p class="refused" role="alert" data-testid="rejected">
      <!-- An em dash between the two clauses rather than a full stop: kaya's refusal messages carry
           no trailing punctuation (`pandan did not accept this token`), and appending one here would
           double up the day a message arrives with its own. -->
      {rejected} — the credential has been cleared from this tab. Paste another below.
    </p>
  {/if}

  <form class="paste" method="post" onsubmit={submit} data-testid="paste-form">
    <label for="pat">pandan personal access token</label>
    <!--
      Four attributes, each with a reason, and none of them cosmetic:

      - `type="password"` — the field holds a live credential and a screenshot or a screen share is
        one keystroke away. The CLI's equivalent never echoes either.
      - **no `name`** — a form field with no name is not serialized at all, so even a submission
        that somehow escaped `preventDefault()` above carries nothing. This is the strongest of the
        three guards against the credential reaching a URL, because it does not depend on a handler
        running.
      - `autocomplete="off"` — this is not a password to remember, it is a token that gets revoked;
        an offer to save it moves the credential out of `sessionStorage`'s tab lifetime and into the
        browser's own store, which is the `localStorage` decision `lib/auth.ts` already refused.
      - `spellcheck="false"` — a spellchecker is allowed to send text to a remote service.
    -->
    <input
      id="pat"
      type="password"
      autocomplete="off"
      spellcheck="false"
      autocapitalize="off"
      placeholder="paste here"
      bind:value={pasted}
    />
    <button type="submit">Use this token</button>
  </form>

  {#if problem}
    <p class="refused" role="alert" data-testid="problem">{problem}</p>
  {/if}

  <p class="footnote">
    The token stays in this tab and nowhere else: it is held in <code>sessionStorage</code>, so
    closing the tab discards it, and it is sent only as an <code>Authorization</code> header to
    kaya's own API on this origin.
  </p>
</main>

<style>
  .landing {
    max-width: 34rem;
    padding: 3rem 1.5rem;
  }

  h1 {
    margin: 0;
    font-size: 1.6rem;
    letter-spacing: -0.02em;
  }

  h2 {
    margin: 2rem 0 0.5rem;
    font-size: 1rem;
  }

  .lede {
    margin: 0.5rem 0 0;
  }

  p {
    line-height: 1.55;
  }

  .steps {
    margin: 0.75rem 0 0;
    padding-left: 1.25rem;
    line-height: 1.8;
  }

  .paste {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin-top: 2rem;
  }

  .paste label {
    flex-basis: 100%;
    color: var(--muted);
    font-size: 0.85rem;
  }

  .paste input {
    flex: 1 1 18rem;
    min-width: 0;
    padding: 0.5rem 0.65rem;
    border: 1px solid var(--edge);
    border-radius: 0.35rem;
    background: transparent;
    color: inherit;
    font-family: var(--mono);
    font-size: 0.9rem;
  }

  .paste button {
    padding: 0.5rem 0.9rem;
    border: 1px solid var(--edge);
    border-radius: 0.35rem;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
  }

  .refused {
    margin: 0.75rem 0 0;
  }

  .footnote {
    margin: 2rem 0 0;
    color: var(--muted);
    font-size: 0.85rem;
  }
</style>
