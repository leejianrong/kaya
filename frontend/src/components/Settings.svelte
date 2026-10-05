<!--
  KAN-1815: the Settings page, `/settings`. One toggle today, "Format on save".

  Stored server-side per kaya account (`/api/v1/preferences`), so the choice follows the account
  across browsers. An account that never chose reads ON — the server applies that default, so there
  is nothing to backfill and nothing for this component to special-case.

  **The help text is a promise about scope, and it is load-bearing**: the toggle governs saves made
  from this browser app only. The CLI and MCP never format implicitly. Anything that changes that
  must change the text in the same PR.

  Nested inside `App.svelte`'s `authed` branch like `PandanConnect.svelte`: reaching it already
  means holding a working credential, and there is no bootstrap problem to special-case out of it.

  KAN-1818: also the home of what used to sit in the header and the nav column — **Access tokens**
  (`/tokens`), **Pandan connection** (`/pandan`) and, when the operator configured one, the pandan
  board link (resolved by `resolvePandanHref`, hidden entirely rather than dead when unset). Those
  routes still exist; this page is just how a person gets to them now.

  The checkbox is written optimistically and put back if the write fails, with the reason shown —
  a toggle that reads "off" while the server still says "on" would make the next save format a note
  the user believes it won't.
-->
<script lang="ts">
  import { ApiError } from '../lib/api'
  import {
    DEFAULT_FORMAT_ON_SAVE,
    fetchPreferences,
    rememberFormatOnSave,
    updatePreferences,
  } from '../lib/preferences'
  import { resolvePandanHref } from '../lib/meta'
  import { interceptClick } from '../lib/router'

  type Phase = 'loading' | 'ready'

  let phase: Phase = $state('loading')
  let formatOnSave: boolean = $state(DEFAULT_FORMAT_ON_SAVE)
  let problem: string | null = $state(null)
  let busy = $state(false)

  $effect(() => {
    const abort = new AbortController()
    fetchPreferences({ signal: abort.signal })
      .then((read) => {
        if (abort.signal.aborted) {
          return
        }
        formatOnSave = read.format_on_save
        rememberFormatOnSave(read.format_on_save)
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

  async function toggle(event: Event): Promise<void> {
    const next = (event.currentTarget as HTMLInputElement).checked
    const previous = formatOnSave
    formatOnSave = next
    problem = null
    busy = true
    try {
      const stored = await updatePreferences({ format_on_save: next })
      formatOnSave = stored.format_on_save
      rememberFormatOnSave(stored.format_on_save)
    } catch (error) {
      formatOnSave = previous
      problem = describe(error)
    } finally {
      busy = false
    }
  }

  let pandanHref: string | null = $state(null)

  $effect(() => {
    const abort = new AbortController()
    resolvePandanHref({ signal: abort.signal }).then((resolved) => (pandanHref = resolved))
    return () => abort.abort()
  })

  function describe(error: unknown): string {
    if (error instanceof ApiError) {
      return error.message
    }
    return error instanceof Error ? error.message : 'Something went wrong.'
  }
</script>

<section class="settings" data-testid="settings-page">
  <h1>Settings</h1>

  {#if phase === 'loading'}
    <p>Loading your settings…</p>
  {:else}
    <div class="setting">
      <label for="format-on-save">
        <input
          id="format-on-save"
          type="checkbox"
          checked={formatOnSave}
          disabled={busy}
          onchange={toggle}
          data-testid="format-on-save"
        />
        Format on save
      </label>
      <p class="help" data-testid="format-on-save-help">
        Tidies a note's markdown (spacing, list markers, table alignment) when you save it from this
        browser app. It applies to browser saves only: the CLI and MCP never format implicitly. When
        off, your text is stored exactly as typed.
      </p>
    </div>
  {/if}

  <nav class="links" aria-label="Account and connections" data-testid="settings-links">
    <a href="/tokens" onclick={(event) => interceptClick(event, '/tokens')} data-testid="settings-tokens">
      <span class="name">Access tokens</span>
      <span class="hint">Mint and revoke tokens for the CLI and agents</span>
    </a>
    <a href="/pandan" onclick={(event) => interceptClick(event, '/pandan')} data-testid="settings-pandan">
      <span class="name">Pandan connection</span>
      <span class="hint">Link a pandan account for board embeds</span>
    </a>
    {#if pandanHref}
      <a
        href={pandanHref}
        target="_blank"
        rel="noopener noreferrer"
        data-testid="pandan-link"
      >
        <span class="name">pandan</span>
        <span class="hint">Open the pandan board in a new tab</span>
      </a>
    {/if}
  </nav>

  {#if problem}
    <p class="refused" role="alert" data-testid="problem">{problem}</p>
  {/if}
</section>

<style>
  .settings {
    max-width: 34rem;
    padding: 3rem 1.5rem;
  }

  h1 {
    margin: 0 0 1rem;
    font-size: 1.4rem;
  }

  .setting label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 500;
  }

  .help {
    margin: 0.4rem 0 0 1.6rem;
    color: var(--muted);
    font-size: 0.85rem;
    line-height: 1.5;
  }

  .links {
    display: flex;
    flex-direction: column;
    margin-top: 2rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card-bg);
  }

  .links a {
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: 3.5rem;
    padding: 0.5rem 1rem;
    color: inherit;
    text-decoration: none;
  }

  .links a + a {
    border-top: 1px solid var(--border);
  }

  .links a:hover {
    background: var(--hover);
  }

  .links .name {
    font-weight: 500;
  }

  .links .hint {
    color: var(--muted);
    font-size: 0.8rem;
  }

  @media (max-width: 599.98px) {
    .settings {
      padding: 1.5rem 1rem;
    }
  }

  .refused {
    margin-top: 1rem;
  }
</style>
