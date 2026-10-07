<!--
  What a visitor with no credential sees (KAN-555; KAN-1740's identity cutover; KAN-1791; rewritten
  for KAN-1822). One promise, one sign-in action, an interactive phone mock, three short tiles.

  GitHub sign-in is the page's only credential-acquisition path: kaya mints no passwords, and the
  `kayaauth` cookie `/auth/github/callback` sets is what `apiRequest` (`lib/api.ts`) authenticates
  against. A named bearer for the CLI or a script is minted later, on the Tokens page, once signed in.
-->
<script lang="ts">
  import { githubLoginUrl, IdentityError } from '../lib/identity'
  import Logo from './Logo.svelte'
  import PhoneDemo from './PhoneDemo.svelte'

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

  /**
   * The three tiles. The approved copy, in one place. The first tile deliberately names Claude Code
   * and MCP clients in general and no other product: only Claude Code has been checked against
   * kaya's MCP endpoint, so another client's name is added here once it has been.
   */
  const TILES = [
    {
      title: 'Agent ready',
      text: 'Write and edit notes from Claude Code or any MCP client, or script them with the CLI.',
    },
    {
      title: 'Linked notes',
      text: 'Link notes with [[wikilinks]]. Backlinks appear automatically.',
    },
    {
      title: 'Knowledge graph',
      text: 'See how your notes connect, including the ones your agents wrote.',
    },
  ] as const

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
    <div class="hero-mark"><Logo size={72} /></div>
    <h1>Markdown for humans and agents.</h1>
    <p class="subhead">Work on notes alongside your agents.</p>

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

  <div class="phone-slot"><PhoneDemo /></div>

  <section class="features" aria-label="What kaya does">
    {#each TILES as tile (tile.title)}
      <article class="tile">
        <h2>{tile.title}</h2>
        <p>{tile.text}</p>
      </article>
    {/each}
  </section>
</main>

<style>
  .landing {
    /* An explicit width, not just a max: as a grid item with auto margins it would otherwise size to
       its content's min-content and push the page 10px wider than a 320px screen. */
    box-sizing: border-box;
    width: min(100%, 46rem);
    min-width: 0;
    margin: 0 auto;
    padding: clamp(2.5rem, 7vw, 4.5rem) 1.5rem 3rem;
  }

  /* --- hero ---------------------------------------------------------------------------------- */

  .hero {
    text-align: center;
  }

  .hero-mark {
    display: flex;
    justify-content: center;
    margin-bottom: 1.25rem;
  }

  h1 {
    margin: 0 auto 0.85rem;
    max-width: 20ch;
    font-size: clamp(1.9rem, 5vw, 2.65rem);
    line-height: 1.08;
    letter-spacing: -0.02em;
    font-weight: 700;
    text-wrap: balance;
  }

  .subhead {
    margin: 0 auto;
    max-width: 44ch;
    color: var(--on-surface-variant);
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
    border: 0;
    border-radius: var(--shape-full);
    background: var(--primary);
    color: var(--on-primary);
    font: inherit;
    font-weight: 600;
    font-size: 0.95rem;
    cursor: pointer;
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
    outline: 2px solid var(--primary);
    outline-offset: 2px;
  }

  .btn-github svg {
    fill: currentColor;
    flex-shrink: 0;
  }

  .phone-slot {
    margin-top: clamp(1.75rem, 4vw, 2.5rem);
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
    border-radius: var(--shape-md);
    background: var(--surface-container);
  }

  .tile h2 {
    margin: 0 0 0.4rem;
    font-size: 0.95rem;
    letter-spacing: -0.01em;
  }

  .tile p {
    margin: 0;
    color: var(--on-surface-variant);
    font-size: var(--type-body-medium-size);
    line-height: 1.55;
  }

  @media (max-width: 40rem) {
    .features {
      grid-template-columns: 1fr;
    }
  }

  .refused {
    margin: 1rem 0 0;
    color: var(--error);
  }

  /* --- motion ------------------------------------------------------------------------------------
     A one-time reveal on mount, not a scroll-triggered sequence — a single viewport-height hero has
     nothing left to reveal once scrolled to. */
  @media (prefers-reduced-motion: no-preference) {
    .hero > *,
    .phone-slot,
    .tile {
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
    .phone-slot {
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
    @keyframes rise {
      to {
        opacity: 1;
        transform: none;
      }
    }
  }
</style>
