<!--
  What a visitor with no credential sees, and the one-time PAT paste (KAN-555; copy updated for
  ADR 0012's cutover, KAN-1740 — the token this page asks for is kaya's own `kaya_pat_…` now, not a
  pandan one, and it comes from kaya's own `/tokens` page, not pandan's).

  This component is small and its discipline is not. It is the only place in the product where a
  live credential exists as a value a person typed, so every choice about the input element is a
  deliberate one and is written down beside it. `lib/auth.ts` holds the rule those choices serve:
  **the token never enters a URL, a log line, an error message, or the DOM.**

  Nothing here validates the token against kaya's own API. It is stored, the shell advances, and
  the note list's own request is what says whether it works — a `401` comes back to this component
  as `rejected`. Verifying here first would mean two code paths that can produce a `401` and two
  places to keep the recovery honest, for one saved round trip on the failure case only.
-->
<script lang="ts">
  import { isUsableToken, setToken } from '../lib/auth'
  import { interceptClick } from '../lib/router'

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
    <h2 id="identity">Get a kaya token</h2>
    <p>
      kaya mints and verifies its own credentials (ADR 0012) — no pandan account is needed to use
      kaya itself. Sign in with the GitHub account you want kaya notes filed under, mint a token on
      kaya's own Tokens page, and paste it below.
    </p>

    <ol class="steps">
      <li>
        Open <a href="/tokens" onclick={(event) => interceptClick(event, '/tokens')}>Tokens</a>
        and sign in with GitHub.
      </li>
      <li>Create a token.</li>
      <li>Paste it below.</li>
    </ol>
  </section>

  {#if rejected}
    <!-- The API's own prose for a refusal it produced. The backend never puts a credential in a
         message, and nothing here builds one out of a request. -->
    <p class="refused" role="alert" data-testid="rejected">
      <!-- An em dash between the two clauses rather than a full stop: kaya's refusal messages carry
           no trailing punctuation (`kaya did not accept this credential`), and appending one here
           would double up the day a message arrives with its own. -->
      {rejected} — the credential has been cleared from this tab. Paste another below.
    </p>
  {/if}

  <form class="paste" method="post" onsubmit={submit} data-testid="paste-form">
    <label for="pat">kaya personal access token</label>
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
    border: 1px solid var(--border);
    border-radius: 0.35rem;
    background: transparent;
    color: inherit;
    font-family: var(--mono);
    font-size: 0.9rem;
  }

  .paste button {
    padding: 0.5rem 0.9rem;
    border: 1px solid var(--border);
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
