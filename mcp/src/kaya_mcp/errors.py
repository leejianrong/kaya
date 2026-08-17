"""kaya_mcp's own failure: `get_backlinks` has no backend, no `KayaClient` method and no CLI verb.

ADR 0006 froze the six tool names on day one, `get_backlinks` among them, but `/links` /
`/backlinks` (KAN-566, V5) has not landed at any layer — verified before this card started: no
route in `backend/app/api/`, no method on `KayaClient`, no verb in `kaya-cli`, and KAN-566 itself is
blocked on KAN-562. ADR 0006 §2 also says "the CLI is where new capability lands by default, and the
MCP server follows deliberately", so this tool must not be the place backlinks capability is
invented first.

Two shapes were available and both are wrong in their own way: silently returning `{"notes": []}`
is indistinguishable from "this note genuinely has no backlinks" and would be a fabricated answer,
and *not* registering the tool at all would leave ADR 0006's frozen six short by one until KAN-566
happens to land in the right order. The shape this card takes instead — register the tool, so the
name exists and a future parity test (KAN-570) has something to check, but make every call refuse
immediately and say why — is a genuine cross-card sequencing gap made explicit rather than a defect
in this one. See the PR description for the fuller reasoning.

`BacklinksNotAvailable` is a `KayaError` subclass rather than a bare exception so this refusal
reaches `render_error` through the same seam every other MCP failure does, carrying its own code
rather than borrowing `runtime`: unlike `TransportError` or `ApiError`, this failure has no wire
form and no CLI exit row to inherit, because there is genuinely nothing behind the tool yet. It is
declared here, in `kaya_mcp`, rather than in `kaya_client` — ADR 0004 puts *payload shaping* in the
shared client because both adapters need it identically; this failure describes a gap that exists
in the MCP adapter alone (the CLI has no `backlinks` verb to fail from), so a second adapter never
needs to see this class and `kaya_client` never needs to know it exists.
"""

from kaya_client import KayaError

CODE = "not_yet_available"

MESSAGE = (
    "get_backlinks is registered — ADR 0006 froze it as one of kaya's six MCP tools from day one "
    "— but it has no implementation yet: there is no backend route, no KayaClient method and no "
    "CLI verb for backlinks anywhere in kaya today. That capability is KAN-566 (V5), blocked on "
    "KAN-562, and it has not landed. This is a refusal rather than an empty result, so a caller "
    "cannot mistake 'not built yet' for 'this note has no backlinks'."
)

ARG = "get_backlinks"


class BacklinksNotAvailable(KayaError):
    """Raised by every call to the `get_backlinks` tool until KAN-566 lands."""

    code = CODE
