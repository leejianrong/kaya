<!--
  What a visitor with no credential sees (KAN-555; copy updated for ADR 0012's cutover, KAN-1740,
  and again for KAN-1791). GitHub sign-in is the page's one and only credential-acquisition path
  now — kaya mints no passwords and never did, GitHub OAuth is the sole login route
  (`backend/app/identity/router.py`'s own comment on `/auth/login`), and there is no paste form to
  fall back to any more: the `kayaauth` cookie `/auth/github/callback` sets is what `apiRequest`
  (`lib/api.ts`, KAN-1791) now authenticates every note-API call against directly, with no
  intermediate `kaya_pat_…` bearer this page has to hand the shell.

  `Tokens.svelte`'s "Use this token now" still exists for minting a *named*, purpose-specific
  bearer (the CLI, a script, another device) without disturbing a browser tab's cookie session —
  that is a deliberate, still-live exception `lib/auth.ts`'s own module docstring explains. This
  page just no longer needs to be a second door to the identical bearer.
-->
<script lang="ts">
  import { githubLoginUrl, IdentityError } from '../lib/identity'
  import { interceptClick } from '../lib/router'

  const {
    rejected = null,
  }: {
    /**
     * Why the last credential was refused, in the API's own words, or `null`.
     *
     * The shell has already discarded the credential by the time this arrives (`App.svelte`'s
     * `discard()`) — a `401` you cannot leave without devtools is a bug — so this is a message to
     * show beside the sign-in button, not a state that gates anything here.
     */
    rejected?: string | null
    /**
     * Kept in the type for parity with `App.svelte`'s call site, which still hands this component
     * the same `accept` callback `Tokens.svelte` and the CLI's device-flow approval get — but
     * nothing in this file destructures or calls it any more now that the paste form (the one
     * thing that used to) is gone. GitHub sign-in is a full-page redirect (`signIn` below): the tab
     * navigates away and back through `/auth/github/callback`, so there is no in-page moment to
     * call `onaccept` from — `authed` flips because `App.svelte`'s own mount-time session check
     * finds the fresh cookie session, not because this component told it to.
     */
    onaccept: () => void
  } = $props()

  let signingIn = $state(false)
  let signInProblem: string | null = $state(null)

  // `/auth/github/callback` (`backend/app/identity/router.py`'s `_redirect_declined_oauth`)
  // redirects back here — `POST_LOGIN_REDIRECT`, the same target a *successful* callback uses —
  // with this query param rather than leaving the tab on a raw JSON error body. A successful
  // attempt carries no such param, so this never fires on the path where `App.svelte`'s own
  // mount-time session check (`fetchCurrentUser`, KAN-1791) is about to swap this page out for the
  // note list anyway.
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
    </div>

    {#if signInProblem}
      <p class="refused" role="alert" data-testid="sign-in-problem">{signInProblem}</p>
    {/if}

    {#if rejected}
      <!-- KAN-1791: relocated from the now-deleted paste section. Still the API's own prose for a
           refusal it produced — the backend never puts a credential in a message, and nothing here
           builds one out of a request — just now surfaced beside the one credential-acquisition
           path this page has left. -->
      <p class="refused" role="alert" data-testid="rejected">
        <!-- An em dash between the two clauses rather than a full stop: kaya's refusal messages carry
             no trailing punctuation (`kaya did not accept this credential`), and appending one here
             would double up the day a message arrives with its own. -->
        {rejected} — sign in again to continue.
      </p>
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

  <!-- KAN-1791: no longer "the paste section" — the form, its input, its own refusal message and
       the sessionStorage footnote are gone along with it. What is left is the one thing that was
       never about pasting: kaya's own identity model, and the link to where a *named* bearer (for
       the CLI, a script, another device) still gets minted by hand. -->
  <section class="identity-note" aria-labelledby="identity">
    <h2 id="identity">Kaya mints its own credentials</h2>
    <p>
      Sign in with GitHub above — kaya mints and verifies its own credentials (ADR 0012), so no
      pandan account is needed to use kaya itself. Need a bearer for the CLI, a script or another
      device instead? Mint a named one on the
      <a href="/tokens" onclick={(event) => interceptClick(event, '/tokens')}>Tokens</a>
      page.
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

  /* --- the identity note (KAN-1791: what the paste form's card became once the form left it) ---- */

  .identity-note {
    margin-top: clamp(2.5rem, 6vw, 3.5rem);
    padding: 1.5rem 1.5rem 1.75rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card-bg);
  }

  .identity-note h2 {
    margin: 0 0 0.5rem;
    font-size: 1rem;
  }

  .identity-note > p {
    margin: 0;
    line-height: 1.55;
  }

  .identity-note > p a {
    color: var(--accent);
    font-weight: 600;
  }

  .identity-note > p a:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: 0.2rem;
  }

  .refused {
    margin: 1rem 0 0;
    color: var(--danger);
  }

  /* --- motion ------------------------------------------------------------------------------------
     A one-time reveal on mount, not a scroll-triggered sequence — a single viewport-height hero has
     nothing left to reveal once scrolled to. */
  @media (prefers-reduced-motion: no-preference) {
    .hero > *,
    .demo,
    .tile,
    .identity-note {
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
    .identity-note {
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
