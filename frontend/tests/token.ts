/**
 * The one fake credential the frontend tests use, spelled the way the rest of the repo spells it.
 *
 * Same literal as `kaya-cli/tests/test_config_verbs.py` and `kaya-client/tests/test_config_file.py`,
 * which is the point: one spelling, so `.gitleaks.toml`'s placeholder allowlist recognises it
 * (`FAKE…` after the prefix) and a reader who has seen it in the Python suite knows immediately that
 * it is not a secret. It keeps a real prefix — `kanban_pat_` is still live after the rebrand (pandan
 * ADR 0018) — because a fixture with a made-up prefix would not exercise the shape that actually
 * leaks.
 *
 * It is mixed-case and prefixed rather than a readable word for the reason kaya's redaction fixtures
 * are: a fake containing the word `token` collides with the payload's own key names, and the
 * fragment sweeps start finding themselves.
 */
export const FAKE_TOKEN = 'kanban_pat_FAKE0000aaaaBBBBccccDDDDeeee'

/**
 * Every contiguous run of `size` or more characters in `token`.
 *
 * Four, not eight, and `kaya-cli` explains why: a mutation that leaked exactly pandan's four
 * characters (`set (…c_DE)`) walked straight through a six-character window.
 */
export function fragments(token: string, size = 4): string[] {
  const found: string[] = []
  for (let start = 0; start + size <= token.length; start += 1) {
    for (let end = start + size; end <= token.length; end += 1) {
      found.push(token.slice(start, end))
    }
  }
  return found
}
