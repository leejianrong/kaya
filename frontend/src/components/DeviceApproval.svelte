<!--
  ADR 0013's consent screen (KAN-1743): approve or deny a `kaya auth login` device-flow request.

  Reachable at `/device`, and — like `Tokens.svelte`, unlike `PandanConnect.svelte` — a **peer** of
  `App.svelte`'s whole `authed`/`Landing` branch rather than nested inside it. This page is very
  plausibly the *first* thing a brand-new machine's browser ever opens for kaya: the CLI printed the
  link before anything else existed. It needs kaya's own cookie session (`lib/identity.ts`), which
  is a wholly separate credential from `authed`'s `kaya_pat_…` bearer, and there is no reason to make
  approving a device login depend on a credential that login's own job is to hand out.

  `user_code` comes from the query string (`?user_code=...`, RFC 8628's `verification_uri_complete`)
  rather than from the route — `lib/router.ts`'s own docstring explains why the route itself carries
  none of it. A code the query string didn't supply falls back to an editable field, matching
  `gh auth login`'s own dual presentation: the CLI's browser-opened link fills it in automatically,
  and the short code printed beside it is the fallback for a person who typed the bare
  `verification_uri` in by hand instead.
-->
<script lang="ts">
  import {
    approveDeviceAuthorization,
    denyDeviceAuthorization,
    fetchCurrentUser,
    getDeviceAuthorization,
    githubLoginUrl,
    IdentityError,
    type CurrentUser,
    type DeviceAuthorization,
  } from '../lib/identity'

  type Phase = 'checking' | 'signed-out' | 'entering-code' | 'loaded' | 'not-found'

  let phase: Phase = $state('checking')
  let user: CurrentUser | null = $state(null)
  let userCode = $state(readUserCodeFromQuery())
  let authorization: DeviceAuthorization | null = $state(null)
  let problem: string | null = $state(null)
  let busy = $state(false)

  function readUserCodeFromQuery(): string {
    // Not `lib/router.ts`'s business (see this file's own header) — the query string is this
    // component's alone, exactly the layering `Tokens.svelte` already keeps for its session state.
    return new URLSearchParams(globalThis.location?.search ?? '').get('user_code') ?? ''
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
        await loadCode(abort.signal)
      })
      .catch((error: unknown) => {
        if (!abort.signal.aborted) {
          problem = describe(error)
          phase = 'signed-out'
        }
      })
    return () => abort.abort()
  })

  async function loadCode(signal?: AbortSignal): Promise<void> {
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
    await loadCode()
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
  <h1>Sign in to the CLI</h1>

  {#if phase === 'checking'}
    <p>Checking your session…</p>
  {:else if phase === 'signed-out'}
    <p class="lede">
      Sign in with the GitHub account you want <code>kaya auth login</code> connected to.
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
      That code has expired or does not exist. Run <code>kaya auth login</code> again.
    </p>
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

  {#if problem}
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
