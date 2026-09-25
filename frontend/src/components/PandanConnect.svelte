<!--
  ADR 0012's amendment (KAN-1741): connect a kaya account to a pandan PAT.

  The embedded pandan-board preview used to forward the caller's own kaya-side bearer straight to
  pandan and it happened to work, because before `KAN-1740` the same PAT authenticated both apps.
  It no longer does, so this page is the explicit fix: paste a **pandan** PAT here, kaya verifies it
  against pandan's own `GET /api/v1/me` before storing anything, and every `pandan-board` embed then
  forwards it on this account's behalf.

  Reachable at `/pandan`, and — unlike `Tokens.svelte` — nested **inside** `App.svelte`'s `authed`
  branch rather than a peer of it: connecting a pandan account has no chicken-and-egg problem the
  way minting kaya's *first* PAT does (reaching this page at all already means holding a working
  kaya credential, `lib/pandanLink.ts`'s module docstring), so there is no reason to special-case it
  out of the "everything but the shell needs a credential" default `authed` otherwise enforces. An
  unauthenticated visit to `/pandan` lands on `Landing.svelte`, same as any other note route.
-->
<script lang="ts">
  import { ApiError } from '../lib/api'
  import {
    connectPandanLink,
    disconnectPandanLink,
    fetchPandanLinkStatus,
  } from '../lib/pandanLink'

  type Phase = 'checking' | 'ready'

  let phase: Phase = $state('checking')
  let connected: boolean = $state(false)
  let pasted = $state('')
  let problem: string | null = $state(null)
  let busy = $state(false)

  $effect(() => {
    const abort = new AbortController()
    fetchPandanLinkStatus({ signal: abort.signal })
      .then((status) => {
        if (abort.signal.aborted) {
          return
        }
        connected = status.connected
        phase = 'ready'
      })
      .catch((error: unknown) => {
        if (!abort.signal.aborted) {
          problem = describe(error)
          phase = 'ready'
        }
      })
    return () => abort.abort()
  })

  async function submitConnect(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    const candidate = pasted
    // Cleared before the branch, same discipline `Landing.svelte` uses for its own paste field —
    // no path through this function leaves a live credential sitting in the input.
    pasted = ''

    if (candidate.trim() === '') {
      problem = 'Paste a pandan token first.'
      return
    }

    problem = null
    busy = true
    try {
      const status = await connectPandanLink(candidate)
      connected = status.connected
    } catch (error) {
      problem = describe(error)
    } finally {
      busy = false
    }
  }

  async function disconnect(): Promise<void> {
    busy = true
    try {
      const status = await disconnectPandanLink()
      connected = status.connected
    } catch (error) {
      problem = describe(error)
    } finally {
      busy = false
    }
  }

  function describe(error: unknown): string {
    if (error instanceof ApiError) {
      return error.message
    }
    return error instanceof Error ? error.message : 'Something went wrong.'
  }
</script>

<main class="pandan-connect">
  <h1>Pandan</h1>

  {#if phase === 'checking'}
    <p>Checking your connection…</p>
  {:else if connected}
    <p class="lede" data-testid="connected-state">
      Your pandan account is connected. Board embeds in your notes forward this credential.
    </p>
    <button type="button" onclick={disconnect} disabled={busy} data-testid="disconnect">
      Disconnect
    </button>
  {:else}
    <p class="lede">
      Kaya's own credential (the one you pasted on the landing page, or minted on
      <a href="/tokens">Tokens</a>) no longer opens pandan's door — the two apps have separate
      credentials since ADR 0012. Paste a pandan PAT here to let this account's `pandan-board`
      embeds show live cards again.
    </p>

    <form onsubmit={submitConnect} data-testid="connect-form">
      <label for="pandan-token">Pandan personal access token</label>
      <input
        id="pandan-token"
        type="password"
        autocomplete="off"
        spellcheck="false"
        autocapitalize="off"
        placeholder="paste here"
        bind:value={pasted}
      />
      <button type="submit" disabled={busy}>Connect</button>
    </form>
  {/if}

  {#if problem}
    <p class="refused" role="alert" data-testid="problem">{problem}</p>
  {/if}
</main>

<style>
  .pandan-connect {
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
    flex: 1 1 18rem;
    min-width: 0;
    padding: 0.4rem 0.6rem;
    border: 1px solid var(--border);
    border-radius: 0.35rem;
    background: transparent;
    color: inherit;
    font-family: var(--mono);
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

  .refused {
    margin-top: 1rem;
  }
</style>
