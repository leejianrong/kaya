<!--
  ADR 0013's consent screen (KAN-1743): approve or deny a `kaya auth login` device-flow request.
  Since ADR 0014 (KAN-1744), the **same** component also serves a second entry path: a
  browser-embedded MCP client's authorization_code+PKCE redirect.

  Reachable at `/device`, and — like `Tokens.svelte`, unlike `PandanConnect.svelte` — a **peer** of
  `App.svelte`'s whole `authed`/`Landing` branch rather than nested inside it. This page is very
  plausibly the *first* thing a brand-new machine's browser ever opens for kaya: the CLI printed the
  link before anything else existed, or a hosted MCP client's own "Connect" button did. It needs
  kaya's own cookie session (`lib/identity.ts`), which is a wholly separate credential from `authed`'s
  `kaya_pat_…` bearer, and there is no reason to make approving either flow depend on a credential
  that flow's own job is to hand out.

  **`mode` is read from the query string once, at mount, never from the route** — `lib/router.ts`'s
  own docstring explains why the route itself carries none of it. `?user_code=...` (RFC 8628's
  `verification_uri_complete`) means device mode; `?client_id=&redirect_uri=...` (the backend's own
  `GET /auth/authorize` redirect, ADR 0014) means authorize mode. A code the query string didn't
  supply for device mode falls back to an editable field, matching `gh auth login`'s own dual
  presentation; authorize mode has no such fallback — every required param arrives together or the
  request is invalid, since nothing about it is ever hand-typed.

  **Authorize mode ends by leaving this page entirely** (`window.location.assign`, a real top-level
  navigation back to the requesting app) rather than rendering a resolved state in place the way
  device mode's approve/deny do — there is nothing on this origin left to show once the browser is
  on its way back to the MCP client.
-->
<script lang="ts">
  import {
    approveAuthorize,
    approveDeviceAuthorization,
    denyAuthorize,
    denyDeviceAuthorization,
    fetchCurrentUser,
    getAuthorizeInfo,
    getDeviceAuthorization,
    githubLoginUrl,
    IdentityError,
    type AuthorizeInfo,
    type AuthorizeParams,
    type CurrentUser,
    type DeviceAuthorization,
    type TokenScope,
  } from '../lib/identity'

  type Phase = 'checking' | 'signed-out' | 'entering-code' | 'loaded' | 'not-found'
  type Mode = 'device' | 'authorize'

  const query = new URLSearchParams(globalThis.location?.search ?? '')
  const isAuthorizeAttempt = query.has('client_id') || query.has('redirect_uri')
  const mode: Mode = isAuthorizeAttempt ? 'authorize' : 'device'
  const authorizeParams: AuthorizeParams | null = isAuthorizeAttempt
    ? parseAuthorizeParams(query)
    : null

  let phase: Phase = $state('checking')
  let user: CurrentUser | null = $state(null)
  let userCode = $state(query.get('user_code') ?? '')
  let authorization: DeviceAuthorization | null = $state(null)
  let authorizeInfo: AuthorizeInfo | null = $state(null)
  let problem: string | null = $state(null)
  let busy = $state(false)

  function parseAuthorizeParams(params: URLSearchParams): AuthorizeParams | null {
    const clientId = params.get('client_id')
    const redirectUri = params.get('redirect_uri')
    const codeChallenge = params.get('code_challenge')
    const codeChallengeMethod = params.get('code_challenge_method')
    const resource = params.get('resource')
    if (!clientId || !redirectUri || !codeChallenge || !codeChallengeMethod || !resource) {
      return null
    }
    const scope: TokenScope = params.get('scope') === 'read' ? 'read' : 'write'
    return {
      client_id: clientId,
      redirect_uri: redirectUri,
      code_challenge: codeChallenge,
      code_challenge_method: codeChallengeMethod,
      resource,
      scope,
      state: params.get('state'),
    }
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
        await load(abort.signal)
      })
      .catch((error: unknown) => {
        if (!abort.signal.aborted) {
          problem = describe(error)
          phase = 'signed-out'
        }
      })
    return () => abort.abort()
  })

  async function load(signal?: AbortSignal): Promise<void> {
    if (mode === 'authorize') {
      if (authorizeParams === null) {
        phase = 'not-found'
        return
      }
      try {
        authorizeInfo = await getAuthorizeInfo(authorizeParams, { signal })
        if (signal?.aborted) {
          return
        }
        phase = 'loaded'
      } catch (error) {
        if (signal?.aborted) {
          return
        }
        problem = describe(error)
        phase = 'not-found'
      }
      return
    }

    if (userCode.trim() === '') {
      phase = 'entering-code'
      return
    }
    try {
      const found = await getDeviceAuthorization(userCode.trim(), { signal })
      if (signal?.aborted) {
        return
      }
      authorization = found
      phase = 'loaded'
    } catch (error) {
      if (signal?.aborted) {
        return
      }
      if (error instanceof IdentityError && error.status === 404) {
        phase = 'not-found'
        return
      }
      problem = describe(error)
      phase = 'entering-code'
    }
  }

  async function submitCode(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    problem = null
    await load()
  }

  async function signIn(): Promise<void> {
    problem = null
    try {
      const url = await githubLoginUrl()
      globalThis.location.assign(url)
    } catch (error) {
      problem = describe(error)
    }
  }

  async function approve(): Promise<void> {
    busy = true
    try {
      if (mode === 'authorize' && authorizeParams) {
        const result = await approveAuthorize(authorizeParams)
        globalThis.location.assign(result.redirect_to)
        return
      }
      authorization = await approveDeviceAuthorization(userCode.trim())
    } catch (error) {
      problem = describe(error)
    } finally {
      busy = false
    }
  }

  async function deny(): Promise<void> {
    busy = true
    try {
      if (mode === 'authorize' && authorizeParams) {
        const result = await denyAuthorize(authorizeParams)
        globalThis.location.assign(result.redirect_to)
        return
      }
      authorization = await denyDeviceAuthorization(userCode.trim())
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

<main class="device-approval">
  <h1>{mode === 'authorize' ? 'Connect an application' : 'Sign in to the CLI'}</h1>

  {#if phase === 'checking'}
    <p>Checking your session…</p>
  {:else if phase === 'signed-out'}
    <p class="lede">
      {#if mode === 'authorize'}
        Sign in with the GitHub account you want this application connected to.
      {:else}
        Sign in with the GitHub account you want <code>kaya auth login</code> connected to.
      {/if}
    </p>
    <button type="button" onclick={signIn} data-testid="github-signin">Sign in with GitHub</button>
  {:else if phase === 'entering-code'}
    <p class="lede">
      Signed in as <strong>{user?.email}</strong>. Enter the code your terminal showed.
    </p>
    <form onsubmit={submitCode} data-testid="code-form">
      <label for="user-code">Code</label>
      <input
        id="user-code"
        bind:value={userCode}
        placeholder="WDJB-MJHT"
        autocomplete="off"
        spellcheck="false"
      />
      <button type="submit">Continue</button>
    </form>
  {:else if phase === 'not-found'}
    <p class="refused" role="alert" data-testid="not-found">
      {#if mode === 'authorize'}
        {problem ?? 'This request is invalid or has expired — go back and try connecting again.'}
      {:else}
        That code has expired or does not exist. Run <code>kaya auth login</code> again.
      {/if}
    </p>
  {:else if phase === 'loaded' && mode === 'authorize' && authorizeInfo}
    <p class="lede">
      Signed in as <strong data-testid="current-email">{user?.email}</strong>.
    </p>
    <section class="consent" data-testid="pending-consent">
      <p>
        <strong>{authorizeInfo.client_name ?? 'An application'}</strong> wants to connect to your
        kaya account, with <strong>{authorizeInfo.requested_scope}</strong> access to your notes.
      </p>
      <div class="actions">
        <button type="button" onclick={approve} disabled={busy} data-testid="approve">
          Approve
        </button>
        <button type="button" onclick={deny} disabled={busy} data-testid="deny">Deny</button>
      </div>
    </section>
  {:else if phase === 'loaded' && authorization}
    <p class="lede">
      Signed in as <strong data-testid="current-email">{user?.email}</strong>.
    </p>

    {#if authorization.status === 'pending'}
      <section class="consent" data-testid="pending-consent">
        <p>
          A terminal is asking to sign in as you, with
          <strong>{authorization.requested_scope}</strong> access to your notes.
        </p>
        <div class="actions">
          <button type="button" onclick={approve} disabled={busy} data-testid="approve">
            Approve
          </button>
          <button type="button" onclick={deny} disabled={busy} data-testid="deny">Deny</button>
        </div>
      </section>
    {:else if authorization.status === 'approved'}
      <p class="lede" data-testid="approved-state">
        Approved. Go back to your terminal — it will finish signing in within a few seconds.
      </p>
    {:else}
      <p class="lede" data-testid="denied-state">
        Denied. Nothing was connected. Run <code>kaya auth login</code> again if this wasn't you.
      </p>
    {/if}
  {/if}

  {#if problem && phase !== 'not-found'}
    <p class="refused" role="alert" data-testid="problem">{problem}</p>
  {/if}
</main>

<style>
  .device-approval {
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

  code {
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
    flex-basis: 100%;
    color: var(--muted);
    font-size: 0.85rem;
  }

  form input {
    flex: 1 1 12rem;
    min-width: 0;
    padding: 0.4rem 0.6rem;
    border: 1px solid var(--border);
    border-radius: 0.35rem;
    background: transparent;
    color: inherit;
    font-family: var(--mono);
    font: inherit;
    text-transform: uppercase;
  }

  .consent {
    margin: 1.5rem 0;
    padding: 0.75rem 1rem;
    border: 1px solid var(--border);
    border-radius: 0.35rem;
  }

  .actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.75rem;
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

  .refused {
    margin-top: 1rem;
  }
</style>
