<!--
  kaya's own personal-access-token page (ADR 0012, KAN-1739): sign in with GitHub, mint/list/revoke
  `kaya_pat_…` tokens.

  Reachable at `/tokens` **regardless of `App.svelte`'s `authed` state** — that is the whole reason
  it lives outside the `{#if authed}`/`Landing` branch there. Minting your first kaya-native
  credential cannot itself require one already being pasted into the tab.

  **"Use this token now" is this file's one deliberate bridge to that other credential.** Since
  KAN-1740 a `kaya_pat_…` has worked as the bearer every note-API call sends — this page just never
  offered a way to start using one without leaving the tab, copying it, and pasting it into
  `Landing.svelte`'s own field. The button calls the same `setToken` that field does and the same
  `onaccept` callback `Landing.svelte` already calls, so `App.svelte` needs no separate path for it
  — but this page still owns its own cookie-session identity entirely and this is the only place
  the two credentials touch.

  Session state (`user`) lives here, not in `App.svelte`: unlike the bearer credential, a cookie
  session change here has no effect on the rest of the shell (nothing else in the app reads it yet),
  so there is no reason to lift it.
-->
<script lang="ts">
  import {
    createToken,
    fetchCurrentUser,
    githubLoginUrl,
    IdentityError,
    listTokens,
    logout,
    revokeToken,
    type CreatedToken,
    type CurrentUser,
    type TokenScope,
    type TokenSummary,
  } from '../lib/identity'
  import { setToken } from '../lib/auth'
  import { navigate } from '../lib/router'

  const {
    onaccept,
  }: {
    /** Mirrors `Landing.svelte`'s own prop of the same name: the bearer credential is stored
     * (`useNow` did it); `App.svelte` may flip `authed`. Optional because nothing requires this
     * page's other callers (a bare mount in a test, say) to wire it up. */
    onaccept?: () => void
  } = $props()

  type Phase = 'checking' | 'signed-out' | 'signed-in'

  let phase: Phase = $state('checking')
  let user: CurrentUser | null = $state(null)
  let tokens: TokenSummary[] = $state([])
  let justCreated: CreatedToken | null = $state(null)
  let name = $state('')
  let scope: TokenScope = $state('write')
  let problem: string | null = $state(null)
  let busy = $state(false)

  // `/auth/github/callback` (`backend/app/identity/router.py`'s `_redirect_declined_oauth`)
  // redirects back here with this query param rather than leaving the tab on a raw JSON error
  // body — this page is the only thing that reaches that route, so this is the one place that
  // needs to read it. `replaceState`, not a plain read, so a later reload of this same tab does
  // not re-show a message about an attempt from minutes ago.
  const oauthError = new URLSearchParams(globalThis.location.search).get('oauth_error')
  if (oauthError !== null) {
    problem =
      oauthError === 'access_denied'
        ? 'GitHub sign-in was cancelled.'
        : 'GitHub sign-in failed. Try again.'
    history.replaceState(null, '', globalThis.location.pathname)
  }

  $effect(() => {
    const abort = new AbortController()
    fetchCurrentUser({ signal: abort.signal })
      .then(async (current) => {
        if (abort.signal.aborted) {
          return
        }
        user = current
        if (current === null) {
          phase = 'signed-out'
          return
        }
        phase = 'signed-in'
        tokens = await listTokens()
      })
      .catch((error: unknown) => {
        if (!abort.signal.aborted) {
          problem = describe(error)
          phase = 'signed-out'
        }
      })
    return () => abort.abort()
  })

  async function signIn(): Promise<void> {
    problem = null
    try {
      const url = await githubLoginUrl()
      // Not a bare `<a href>` — `GET /auth/github/authorize` answers JSON, not a redirect (the
      // same build-revealed shape pandan ADR 0011 hit). `lib/identity.ts`'s own docstring on
      // `githubLoginUrl` has the full reasoning.
      globalThis.location.assign(url)
    } catch (error) {
      problem = describe(error)
    }
  }

  async function signOut(): Promise<void> {
    busy = true
    try {
      await logout()
      user = null
      tokens = []
      phase = 'signed-out'
    } catch (error) {
      problem = describe(error)
    } finally {
      busy = false
    }
  }

  async function submitCreate(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    const candidate = name.trim()
    if (candidate === '') {
      problem = 'Give the token a name.'
      return
    }
    problem = null
    busy = true
    try {
      const created = await createToken({ name: candidate, scope })
      justCreated = created
      name = ''
      tokens = await listTokens()
    } catch (error) {
      problem = describe(error)
    } finally {
      busy = false
    }
  }

  /**
   * The bridge this file's docstring describes. `justCreated` is cleared the same way `revoke`
   * clears it — nothing about the raw secret survives past this call — and `navigate('/')` is what
   * actually gets a person off `/tokens` and looking at their notes: `App.svelte`'s `authed` flip
   * alone would not, since `route.name === 'tokens'` is checked before `authed` in its template.
   */
  function useNow(): void {
    if (justCreated === null) {
      return
    }
    setToken(justCreated.token)
    justCreated = null
    onaccept?.()
    navigate('/')
  }

  async function revoke(id: number): Promise<void> {
    busy = true
    try {
      await revokeToken(id)
      if (justCreated?.id === id) {
        justCreated = null
      }
      tokens = await listTokens()
    } catch (error) {
      problem = describe(error)
    } finally {
      busy = false
    }
  }

  function describe(error: unknown): string {
    if (error instanceof IdentityError) {
      return error.message
    }
    return error instanceof Error ? error.message : 'Something went wrong.'
  }
</script>

<main class="tokens">
  <h1>Tokens</h1>

  {#if phase === 'checking'}
    <p>Checking your session…</p>
  {:else if phase === 'signed-out'}
    <p class="lede">
      Sign in with the GitHub account you want kaya tokens minted for. This page is kaya's own —
      separate from the pandan account the rest of this app still authenticates with until a later
      card finishes wiring these tokens into the note API.
    </p>
    <button type="button" onclick={signIn} data-testid="github-signin">Sign in with GitHub</button>
  {:else}
    <p class="lede">
      Signed in as <strong data-testid="current-email">{user?.email}</strong>.
      <button type="button" class="link" onclick={signOut} disabled={busy} data-testid="sign-out">
        Sign out
      </button>
    </p>

    {#if justCreated}
      <!-- The only time the raw secret is ever shown (R7.1). Not stored in any component state
           beyond this render — `justCreated` is cleared on revoke and never repopulated from a
           list read, because a list read never carries the secret at all. -->
      <section class="reveal" role="alert" data-testid="created-secret">
        <p>
          Copy this now — it will not be shown again:
        </p>
        <code>{justCreated.token}</code>
        <button type="button" onclick={useNow} data-testid="use-token-now">
          Use this token now
        </button>
      </section>
    {/if}

    <form onsubmit={submitCreate} data-testid="create-form">
      <label for="token-name">Name</label>
      <input id="token-name" bind:value={name} placeholder="e.g. laptop" />
      <label for="token-scope">Scope</label>
      <select id="token-scope" bind:value={scope}>
        <option value="write">write</option>
        <option value="read">read</option>
      </select>
      <button type="submit" disabled={busy}>Create token</button>
    </form>

    {#if tokens.length === 0}
      <p class="empty">No tokens yet.</p>
    {:else}
      <ul class="list" data-testid="token-list">
        {#each tokens as token (token.id)}
          <li>
            <code>{token.token_prefix}…</code>
            <span class="name">{token.name}</span>
            <span class="scope">{token.scope}</span>
            <button type="button" onclick={() => revoke(token.id)} disabled={busy}>Revoke</button>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}

  {#if problem}
    <p class="refused" role="alert" data-testid="problem">{problem}</p>
  {/if}
</main>

<style>
  .tokens {
    max-width: 34rem;
    padding: 3rem 1.5rem;
  }

  h1 {
    margin: 0 0 1rem;
    font-size: 1.4rem;
  }

  .lede {
    line-height: 1.55;
  }

  .link {
    border: none;
    background: none;
    padding: 0;
    color: inherit;
    text-decoration: underline;
    cursor: pointer;
    font: inherit;
  }

  .reveal {
    margin: 1rem 0;
    padding: 0.75rem 1rem;
    border: 1px solid var(--border);
    border-radius: 0.35rem;
  }

  .reveal [data-testid='use-token-now'] {
    margin-top: 0.75rem;
  }

  .reveal code {
    display: block;
    margin-top: 0.5rem;
    word-break: break-all;
    font-family: var(--mono);
  }

  form {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin: 1.5rem 0;
  }

  form label {
    color: var(--muted);
    font-size: 0.85rem;
  }

  form input,
  form select {
    padding: 0.4rem 0.6rem;
    border: 1px solid var(--border);
    border-radius: 0.35rem;
    background: transparent;
    color: inherit;
    font: inherit;
  }

  button {
    padding: 0.4rem 0.75rem;
    border: 1px solid var(--border);
    border-radius: 0.35rem;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .list li {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--border);
  }

  .list code {
    font-family: var(--mono);
  }

  .name {
    flex: 1;
  }

  .scope {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .empty {
    color: var(--muted);
  }

  .refused {
    margin-top: 1rem;
  }
</style>
