<!--
  What a visitor with no credential sees, and the one-time PAT paste (KAN-555; copy updated for
  ADR 0012's cutover, KAN-1740 — the token this page asks for is kaya's own `kaya_pat_…` now, not a
  pandan one, and it comes from kaya's own `/tokens` page, not pandan's). Redesigned so "Sign in
  with GitHub" is the page's first, prominent move rather than a link buried in a numbered list
  (the maintainer's own complaint after using it) — it starts the identical `/auth/github/authorize`
  redirect `Tokens.svelte`'s own button does, and lands back on `/tokens` (`RedirectingCookieTransport`,
  `app/identity/backend.py`) to mint the token this page still needs pasted below, because a cookie
  session authenticates `/tokens` but never the note API itself (`lib/auth.ts`'s own separation).

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
  import { githubLoginUrl, IdentityError } from '../lib/identity'
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

  let signingIn = $state(false)
  /** Kept separate from `problem` above: two different failures, in two different sections of the
   * page, and conflating them would show a GitHub-redirect failure under the paste form or a
   * malformed-paste complaint under the hero — neither of which the person just did. */
  let signInProblem: string | null = $state(null)

  // `/auth/github/callback` (`backend/app/identity/router.py`'s `_redirect_declined_oauth`)
  // redirects back here — `POST_LOGIN_REDIRECT`, the same target a *successful* callback uses —
  // with this query param rather than leaving the tab on a raw JSON error body. A successful
  // attempt carries no such param, so this never fires on the path where `App.svelte`'s own silent
  // cookie-to-bearer bootstrap is about to swap this page out for the note list anyway.
  // `replaceState`, not a plain read, so a later reload of this same tab does not re-show a message
  // about an attempt from minutes ago.
  const oauthError = new URLSearchParams(globalThis.location.search).get('oauth_error')
  if (oauthError !== null) {
    signInProblem =
      oauthError === 'access_denied'
        ? 'GitHub sign-in was cancelled.'
        : 'GitHub sign-in failed. Try again.'
    history.replaceState(null, '', globalThis.location.pathname)
  }

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

  async function signIn(): Promise<void> {
    signInProblem = null
    signingIn = true
    try {
      const url = await githubLoginUrl()
      // Not a bare `<a href>` — `GET /auth/github/authorize` answers JSON, not a redirect
      // (`Tokens.svelte`'s own `signIn` has the full reasoning; this is the same call).
      globalThis.location.assign(url)
    } catch (error) {
      signInProblem =
        error instanceof IdentityError || error instanceof Error
          ? error.message
          : 'Could not start GitHub sign-in. Try again.'
      signingIn = false
    }
  }
</script>

<main class="landing">
  <section class="hero">
    <h1>The same note, on every surface.</h1>
    <p class="subhead">
      Cloud-hosted markdown notes, wikilinks and backlinks built in. Every action here is a plain
      <code>/api/v1</code> call — the same one kaya's CLI and its MCP tools use, so what you write in
      the browser is exactly what your agent reads.
    </p>

    <div class="cta-row">
      <button
        type="button"
        class="btn-github"
        onclick={signIn}
        disabled={signingIn}
        data-testid="github-signin"
      >
        <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
          <path
            d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"
          ></path>
        </svg>
        {signingIn ? 'Redirecting…' : 'Sign in with GitHub'}
      </button>
      <a class="text-link" href="#paste">Already have a token?</a>
    </div>

    {#if signInProblem}
      <p class="refused" role="alert" data-testid="sign-in-problem">{signInProblem}</p>
    {/if}
  </section>

  <section class="demo" aria-label="What a kaya note looks like">
    <div class="note-card">
      <p class="note-path">journal/2026/sprint-12-retro.md</p>
      <pre class="note-source"><code
          ># Sprint 12 retro

Blocked on <span class="demo-wikilink">[[Board embed follow-ups]]</span> until that ships.</code
        ></pre>
      <p class="note-backlink">↳ backlinked automatically — no link to maintain by hand</p>
    </div>
  </section>

  <section class="features" aria-label="What kaya does">
    <article class="tile">
      <h3>One API, three surfaces</h3>
      <p>
        The browser, the <code>kaya</code> CLI and its MCP tools all read and write the same
        <code>/api/v1</code> — one source of truth, however you reach it.
      </p>
    </article>
    <article class="tile">
      <h3>Wikilinks &amp; backlinks</h3>
      <p>
        Type <code>[[a note's title]]</code>, kaya resolves it to a real note and the note on the
        other end shows the backlink without you doing anything else.
      </p>
    </article>
    <article class="tile">
      <h3>Built for agents</h3>
      <p>
        Six MCP tools and a hosted endpoint, plus a CLI that never prompts — agent-drivable by
        design, not bolted on after.
      </p>
    </article>
  </section>

  <section class="paste" id="paste" aria-labelledby="identity">
    <h2 id="identity">Get a kaya token</h2>
    <p>
      kaya mints and verifies its own credentials (ADR 0012) — no pandan account is needed to use
      kaya itself. Sign in with GitHub above, or on the
      <a href="/tokens" onclick={(event) => interceptClick(event, '/tokens')}>Tokens</a>
      page directly, create a token, and paste it below.
    </p>

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

    <form class="paste-form" method="post" onsubmit={submit} data-testid="paste-form">
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
  </section>
</main>

<style>
  .landing {
    max-width: 46rem;
    margin: 0 auto;
    padding: clamp(2.5rem, 7vw, 4.5rem) 1.5rem 3rem;
  }

  /* --- hero ---------------------------------------------------------------------------------- */

  .hero {
    text-align: center;
  }

  h1 {
    margin: 0 auto 0.85rem;
    max-width: 18ch;
    font-size: clamp(1.9rem, 5vw, 2.65rem);
    line-height: 1.08;
    letter-spacing: -0.02em;
    font-weight: 700;
    text-wrap: balance;
  }

  .subhead {
    margin: 0 auto;
    max-width: 44ch;
    color: var(--muted);
    font-size: 1.05rem;
    line-height: 1.6;
    text-wrap: pretty;
  }

  .cta-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    margin-top: 1.75rem;
  }

  .btn-github {
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.65rem 1.15rem;
    border: 1px solid var(--text);
    border-radius: var(--radius);
    background: var(--text);
    color: var(--bg);
    font: inherit;
    font-weight: 600;
    font-size: 0.95rem;
    cursor: pointer;
    box-shadow: var(--shadow-sm);
    transition:
      transform 0.12s ease,
      filter 0.12s ease;
  }

  .btn-github:hover {
    filter: brightness(1.12);
  }

  .btn-github:active {
    transform: translateY(1px);
  }

  .btn-github:disabled {
    cursor: progress;
    opacity: 0.75;
  }

  .btn-github:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .btn-github svg {
    fill: currentColor;
    flex-shrink: 0;
  }

  .text-link {
    color: var(--accent);
    font-weight: 600;
    font-size: 0.9rem;
    text-decoration: none;
  }

  .text-link:hover {
    text-decoration: underline;
  }

  .text-link:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: 0.2rem;
  }

  /* --- signature note-card demo ---------------------------------------------------------------- */

  .demo {
    margin-top: clamp(2.25rem, 5vw, 3.25rem);
    display: flex;
    justify-content: center;
  }

  .note-card {
    width: 100%;
    max-width: 30rem;
    padding: 1.1rem 1.25rem 1.25rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card-bg);
    box-shadow: var(--shadow-md);
  }

  .note-path {
    margin: 0 0 0.65rem;
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.75rem;
  }

  .note-source {
    margin: 0;
    color: var(--text);
    font-family: var(--mono);
    font-size: 0.85rem;
    line-height: 1.6;
    white-space: pre-wrap;
  }

  .demo-wikilink {
    padding: 0 0.15rem;
    border-radius: 0.25rem;
    /* The exact values `lib/codemirror.ts`'s `.cm-wikilink-resolved` decorates a real pill with —
       this card is a demonstration of the actual product, not an illustration of it. */
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    color: var(--accent);
  }

  .note-backlink {
    margin: 0.85rem 0 0;
    color: var(--muted);
    font-size: 0.8rem;
  }

  /* --- features -------------------------------------------------------------------------------- */

  .features {
    margin-top: clamp(2rem, 5vw, 3rem);
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
  }

  .tile {
    padding: 1.1rem 1.2rem 1.3rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card-bg);
  }

  .tile h3 {
    margin: 0 0 0.4rem;
    font-size: 0.95rem;
    letter-spacing: -0.01em;
  }

  .tile p {
    margin: 0;
    color: var(--muted);
    font-size: 0.85rem;
    line-height: 1.55;
  }

  @media (max-width: 40rem) {
    .features {
      grid-template-columns: 1fr;
    }
  }

  /* --- the paste form -------------------------------------------------------------------------- */

  .paste {
    margin-top: clamp(2.5rem, 6vw, 3.5rem);
    padding: 1.5rem 1.5rem 1.75rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card-bg);
  }

  .paste h2 {
    margin: 0 0 0.5rem;
    font-size: 1rem;
  }

  .paste > p {
    margin: 0;
    line-height: 1.55;
  }

  .paste > p a {
    color: var(--accent);
    font-weight: 600;
  }

  .paste > p a:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: 0.2rem;
  }

  .paste-form {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin-top: 1.5rem;
  }

  .paste-form label {
    flex-basis: 100%;
    color: var(--muted);
    font-size: 0.85rem;
  }

  .paste-form input {
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

  .paste-form input:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }

  .paste-form button {
    padding: 0.5rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 0.35rem;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
  }

  .paste-form button:hover {
    border-color: var(--accent);
    color: var(--accent);
  }

  .paste-form button:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .refused {
    margin: 1rem 0 0;
    color: var(--danger);
  }

  .footnote {
    margin: 1.5rem 0 0;
    color: var(--muted);
    font-size: 0.85rem;
  }

  /* --- motion ------------------------------------------------------------------------------------
     A one-time reveal on mount, not a scroll-triggered sequence — a single viewport-height hero has
     nothing left to reveal once scrolled to. */
  @media (prefers-reduced-motion: no-preference) {
    .hero > *,
    .demo,
    .tile,
    .paste {
      opacity: 0;
      transform: translateY(8px);
      animation: rise 0.5s ease forwards;
    }
    .hero > *:nth-child(1) {
      animation-delay: 0.02s;
    }
    .hero > *:nth-child(2) {
      animation-delay: 0.08s;
    }
    .hero > *:nth-child(3) {
      animation-delay: 0.14s;
    }
    .demo {
      animation-delay: 0.2s;
    }
    .tile:nth-child(1) {
      animation-delay: 0.24s;
    }
    .tile:nth-child(2) {
      animation-delay: 0.28s;
    }
    .tile:nth-child(3) {
      animation-delay: 0.32s;
    }
    .paste {
      animation-delay: 0.36s;
    }
    @keyframes rise {
      to {
        opacity: 1;
        transform: none;
      }
    }
  }
</style>
