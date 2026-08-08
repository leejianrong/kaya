"""SLICES §V1's owner-scoping property, made mechanical.

`GET /api/v1/notes` must **omit** another user's note rather than return an empty page for a scoped
query. That is a property of the SQL, and the way it gets lost is not malice — it is a route that
starts life as ``select(Note).order_by(...)`` while the owner filter is still "obviously" going to
be added, or a second list endpoint (search, backlinks, a folder tree) that copies the first and
skips the one clause that mattered. Every one of those reads fine and returns correct-looking JSON
for the only user on the developer's machine.

So the rule is structural: ``Note`` reaches a query builder in ``app/auth/authorization.py`` and
nowhere else under ``app/``. Anything wanting a list of notes composes onto ``notes_owned_by``,
which has ``WHERE owner_id = :caller`` already on it, and a clause cannot be composed away.

What is deliberately *not* banned is ``session.get(Note, …)``. Fetching one note unscoped is
required, not sloppy: the `403` for someone else's note is only possible if the fetch found it
(``app/auth/authorization.py``). That single note then goes through ``authorize_note``.

The scan is over the AST rather than the raw text, so this docstring does not trip the guard it is
explaining.
"""

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
SCOPING_MODULE = APP_ROOT / "auth" / "authorization.py"

# `select` and `select_from` cover Core and 2.0-style ORM queries; `query` covers the legacy
# `Session.query` a code model still offers. A count phrased as
# `select(func.count()).select_from(notes_owned_by(principal).subquery())` names no `Note` and is
# fine — the scoping is inside the subquery.
QUERY_BUILDERS = frozenset({"select", "select_from", "query"})


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def note_queries(source: str, *, filename: str = "<memory>") -> list[str]:
    """Every place the source builds a query naming ``Note``, as `filename:lineno: builder`."""
    found: list[str] = []

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        builder = _called_name(node)
        if builder not in QUERY_BUILDERS:
            continue
        # `Note` anywhere in an argument, so `select(Note.id, Note.title)` — a projection, which is
        # exactly what a list endpoint reaches for — is caught alongside `select(Note)`.
        for argument in node.args:
            names = (inner for inner in ast.walk(argument) if isinstance(inner, ast.Name))
            if any(name.id == "Note" for name in names):
                found.append(f"{filename}:{node.lineno}: {builder}(… Note …)")
                break

    return sorted(found)


def test_no_module_outside_the_scoping_helper_queries_notes() -> None:
    modules = sorted(path for path in APP_ROOT.rglob("*.py") if path != SCOPING_MODULE)
    assert len(modules) >= 4, "the glob found almost nothing — the guard would pass vacuously"

    offenders: list[str] = []
    for path in modules:
        offenders += note_queries(path.read_text(encoding="utf-8"), filename=path.name)

    assert offenders == [], (
        "SLICES §V1: a note list is scoped with `WHERE owner_id = :caller`, not filtered after the "
        "rows arrive. Compose onto `app.auth.authorization.notes_owned_by` instead. Found: "
        + ", ".join(offenders)
    )


def test_the_sanctioned_query_exists_and_is_scoped_on_the_owner() -> None:
    """The other half. Without this, deleting ``notes_owned_by`` makes the guard above pass.

    The literal is brittle on purpose: this is the one line in the package whose exact shape is the
    contract, and an edit to it should stop and be argued for rather than land quietly.
    """
    source = SCOPING_MODULE.read_text(encoding="utf-8")

    assert note_queries(source) != [], "the sanctioned query moved; this guard now proves nothing"
    assert "select(Note).where(Note.owner_id == principal.id)" in source


def test_the_guard_catches_every_shape_of_the_bug() -> None:
    """An emptiness assertion passes for the wrong reason unless it is shown failing."""
    assert note_queries("rows = session.scalars(select(Note)).all()\n") != []
    assert note_queries("statement = select(Note.id, Note.title).order_by(Note.updated_at)\n") != []
    assert note_queries("rows = session.query(Note).all()\n") != []
    assert note_queries("total = select(func.count()).select_from(Note)\n") != []

    # And stays quiet on the reads that are correct by design.
    assert note_queries("found = session.get(Note, note_id)\n") == []
    assert note_queries("page = notes_owned_by(principal).limit(50)\n") == []
    assert note_queries("statement = select(User).where(User.id == principal.id)\n") == []
