/**
 * PLAN §Testing approach point 4's "self-cleaning prefixed data" — belt and suspenders with
 * `scripts/test-e2e.sh` tearing down the whole compose stack with `-v`. That teardown is what
 * actually guarantees nothing lingers; this one is what keeps a *long-lived* target safe to point
 * this suite at, should that ever become a thing to do (the doc's own words for why the prefix
 * exists at all).
 *
 * Deletes every note whose title starts with this run's id, through the real API, with the real
 * fake bearer — exactly the credential the suite's own tests used to create them. Runs even when a
 * test failed: Playwright always runs `globalTeardown` after `globalSetup`, pass or fail.
 */
import { baseUrl, fakeToken, runId } from './env'

interface NoteSummary {
  ref: string
  title: string
}

interface NoteList {
  notes: NoteSummary[]
}

export default async function globalTeardown(): Promise<void> {
  const origin = baseUrl()
  const token = fakeToken()
  const prefix = runId()

  const headers = { Authorization: `Bearer ${token}` }

  const response = await fetch(`${origin}/api/v1/notes`, { headers })
  if (!response.ok) {
    // A backend that is already gone (a prior failure tore the stack down oddly) leaves nothing to
    // sweep here either. Warn rather than fail the run over cleanup of a stack about to be deleted
    // wholesale by scripts/test-e2e.sh's own trap.
    console.warn(`[global-teardown] could not list notes to sweep: ${response.status}`)
    return
  }

  const payload = (await response.json()) as NoteList
  const mine = payload.notes.filter((note) => note.title.startsWith(prefix))

  for (const note of mine) {
    const result = await fetch(`${origin}/api/v1/notes/${encodeURIComponent(note.ref)}`, {
      method: 'DELETE',
      headers,
    })
    if (!result.ok && result.status !== 404) {
      console.warn(`[global-teardown] could not delete ${note.ref}: ${result.status}`)
    }
  }

  if (mine.length > 0) {
    console.log(`[global-teardown] swept ${mine.length} note(s) prefixed "${prefix}"`)
  }
}
