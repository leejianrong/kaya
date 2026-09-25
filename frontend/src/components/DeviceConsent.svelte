<!--
  ADR 0013's RFC 8628 device flow (KAN-1743): the browser half of `kaya auth login`.

  Reachable at `/device?user_code=WDJB-MJHT` — `POST /auth/device/code`'s own
  `verification_uri_complete` points here. Gated on kaya's own cookie session, the identical
  chicken-and-egg reasoning `Tokens.svelte` already documents for minting a first PAT: approving a
  device-flow login mints a PAT on the CLI's next poll, so it must require a freshly
  cookie-authenticated human, never an existing `kaya_pat_…` bearer (`app/identity/device_auth_router.py`'s
  module docstring has the full argument, including the circular-import reason this could not be
  `get_principal` even if the security case were weaker).

  Mirrors `Tokens.svelte`'s own "check the session, sign in via GitHub if not" shape rather than
  reusing it: this page's payload (a `user_code`, a requested scope, approve/deny) has nothing in
  common with the token list, and forcing one component to do both would be the kind of merge
  `lib/auth.ts`'s own module docstring already argues against for two different credential types.
-->
<script lang="ts">
  import {
    approveDeviceAuthorization,
    denyDeviceAuthorization,
    fetchCurrentUser,
    fetchDeviceAuthorization,
    githubLoginUrl,
    IdentityError,
    type DeviceAuthorization,
    type TokenScope,
  } from '../lib/identity'

  type Phase = 'checking' | 'signed-out' | 'loading' | 'ready' | 'done' | 'gone'

  let phase: Phase = $state('checking')
  let userCode: string | null = $state(null)
  let authorization: DeviceAuthorization | null = $state(null)
  let scope: TokenScope = $state('write')
  let outcome: 'approved' | 'denied' | null = $state(null)
  let problem: string | null = $state(null)
  let busy = $state(false)

  $effect(() => {
    userCode = new URLSearchParams(globalThis.location?.search ?? '').get('user_code')

    const abort = new AbortController()
    fetchCurrentUser({ signal: abort.signal })
      .then(async (user) => {
        if (abort.signal.aborted) {
          return
        }
        if (user === null) {
          phase = 'signed-out'
          return
        }
        if (userCode === null) {
          problem = 'This link is missing its code — copy the whole link the CLI printed.'
          phase = 'gone'
          return
        }
        phase = 'loading'
        const found = await fetchDeviceAuthorization(userCode, { signal: abort.signal })
        authorization = found
        scope = found.requested_scope
        phase = found.status === 'pending' ? 'ready' : 'done'
        if (found.status !== 'pending') {
          outcome = found.status === 'approved' ? 'approved' : 'denied'
        }
      })
      .catch((error: unknown) => {
        if (abort.signal.aborted) {
          return
        }
        if (error instanceof IdentityError && error.status === 404) {
          problem = 'This code is unknown or has expired. Run `kaya auth login` again.'
          phase = 'gone'
          return
        }
        problem = describe(error)
        phase = 'gone'
      })
    return () => abort.abort()
  })

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
    if (userCode === null) {
      return
    }
    busy = true
    try {
      authorization = await approveDeviceAuthorization(userCode, scope)
      outcome = 'approved'
      phase = 'done'
    } catch (error) {
      problem = describe(error)
    } finally {
      busy = false
    }
  }

  async function deny(): Promise<void> {
    if (userCode === null) {
      return
    }
    busy = true
    try {
      await denyDeviceAuthorization(userCode)
      outcome = 'denied'
      phase = 'done'
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

<main class="device-consent">
  <h1>Sign in to kaya</h1>

  {#if phase === 'checking' || phase === 'loading'}
    <p>Checking…</p>
  {:else if phase === 'signed-out'}
    <p class="lede">
      Sign in with the GitHub account you want this credential filed under.
    </p>
    <button type="button" onclick={signIn} data-testid="github-signin">Sign in with GitHub</button>
  {:else if phase === 'ready' && authorization !== null}
    <p class="lede">
      A device is asking to sign in as you, with <strong>{scope}</strong> access to your notes.
    </p>
    <p class="code" data-testid="user-code">{authorization.user_code}</p>

    <div class="actions">
      <button type="button" onclick={approve} disabled={busy} data-testid="approve">
        Approve
      </button>
      <button type="button" onclick={deny} disabled={busy} data-testid="deny">Deny</button>
    </div>
  {:else if phase === 'done'}
    {#if outcome === 'approved'}
      <p class="lede" data-testid="approved-state">
        Approved. Go back to your terminal — it will finish signing in on its own.
      </p>
    {:else}
      <p class="lede" data-testid="denied-state">This login was denied. You may close this tab.</p>
    {/if}
  {:else if phase === 'gone'}
    <p class="refused" role="alert" data-testid="gone">{problem}</p>
  {/if}

  {#if problem && phase !== 'gone'}
    <p class="refused" role="alert" data-testid="problem">{problem}</p>
  {/if}
</main>

<style>
  .device-consent {
    max-width: 30rem;
    padding: 3rem 1.5rem;
  }

  h1 {
    margin: 0 0 1rem;
    font-size: 1.4rem;
  }

  .lede {
    line-height: 1.55;
  }

  .code {
    margin: 1rem 0;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--border);
    border-radius: 0.35rem;
    font-family: var(--mono);
    font-size: 1.1rem;
    letter-spacing: 0.05em;
    text-align: center;
  }

  .actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 1.5rem;
  }

  button {
    padding: 0.5rem 1rem;
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
