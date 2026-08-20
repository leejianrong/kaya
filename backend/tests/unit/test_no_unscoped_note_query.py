"""SLICES §V1's owner-scoping property, made mechanical — in three rules, because the first one
covered less than its name suggested (KAN-965).

`GET /api/v1/notes` must **omit** another user's note rather than return an empty page for a scoped
query. That is a property of the SQL, and the way it gets lost is not malice — it is a route that
starts life as ``select(Note).order_by(...)`` while the owner filter is still "obviously" going to
be added, or a second list endpoint (search, backlinks, a folder tree) that copies the first and
skips the one clause that mattered. Every one of those reads fine and returns correct-looking JSON
for the only user on the developer's machine.

**Rule 1 — where a note query may be written**, and it is unchanged since KAN-535. ``Note`` reaches
a query builder in ``app/auth/authorization.py`` and nowhere else under ``app/``. Anything wanting a
list of notes composes onto ``notes_owned_by``, which has ``WHERE owner_id = :caller`` already on
it,
and a clause cannot be composed away.

What is deliberately *not* banned is ``session.get(Note, …)``. Fetching one note unscoped is
required, not sloppy: the `403` for someone else's note is only possible if the fetch found it
(``app/auth/authorization.py``). That single note then goes through ``authorize_note``.

**Rule 2 — that every note query inside that one module is actually scoped, which rule 1 never
said.** Rule 1's scope is "every module *except* ``app/auth/authorization.py``" — and that is
precisely the module where every note query is *required* to be written, so "compose onto
``notes_owned_by``" was enforced everywhere it was not needed and nowhere it was. Measured on
KAN-566 and re-confirmed on KAN-965: replacing ``notes_owned_by(principal)`` with a bare
``select(Note)`` inside ``notes_linking_to`` left this file **green**. Rule 1 is a guard against a
query being written in the wrong *place*, not against a query being written without *scoping*, and
the two had been read as the same thing — by this docstring included, which named "a second list
endpoint (search, backlinks, a folder tree) that copies the first and skips the one clause that
mattered" as the failure it was watching for while that failure sat in the one module it could not
see.

So rule 2 is asserted against the **statements themselves** rather than against their source.
``note_selector_factories`` discovers every function in that module that hands back a ``Select``,
``statement_from`` calls each one, and ``owner_predicates`` reads the resulting ``WHERE`` clause for
an equality between ``note.owner_id`` and a bound value. Three reasons that beats a fourth AST
probe. The statement is the artefact that reaches Postgres, so a scoping that merely *looks* present
— a clause built and never applied, a ``where()`` on an expression that is not the one returned —
cannot pass it. It does not care how the clause got there, so ``notes_matching``'s composition onto
``notes_owned_by`` and ``notes_titled``'s own ``Note.owner_id == owner_id`` are one assertion rather
than two spellings that have to be kept in step. And discovery is by **signature**, so a factory
added later is covered the day it is written rather than the day somebody remembers this file: an
annotation the sweep has no sample argument for is a failure naming the parameter, never a silent
skip.

Two strictnesses in it are deliberate. An owner predicate has to be an ``==`` against a bound
parameter, so ``Note.owner_id == Note.owner_id`` is reported unscoped — because it is — and
``Note.owner_id.in_(some_scoped_subquery)`` would be too. Nothing needs the ``IN`` form today; the
day something does, widening this is an edit with an argument in it, which is the transaction this
file exists to force. And a factory whose statement never touches ``note`` at all is skipped rather
than failed, since owner scoping is a claim about that table.

``UNSCOPED_BY_DESIGN`` is the allow-list, and it is two entries because ADR 0008 needs two spellings
of a note's name. Each entry carries its own reason, and each is checked to be **still** unscoped,
so
an entry whose function has since gained an owner clause is a failure telling you to delete it. The
allow-list cannot rot into decoration, and a third entry has to be argued for in a diff of this
file.

**Rule 2b — completeness, because rule 2 can only see functions it can call.** A note query hiding
in a function that returns *rows* rather than a ``Select`` would be invisible to the sweep and
exempt
from rule 1 by living in that module. So the AST half stays: every ``select(… Note …)`` written in
the scoping module has to sit inside a function the sweep covers or the allow-list names.

**Rule 3 — ``note_link``, whose owner is one join away** (and the argument KAN-566 said this would
need). Rule 1 matches the name ``Note`` only, so ``NoteLink`` was unguarded entirely. Widening the
name list is the wrong fix and KAN-566 was right to decline it: ``note_link`` has **no owner
column** (``app/models/note_link.py``), so "scoped" cannot mean for it what it means for ``Note``,
and a blunt ban on ``select(NoteLink)`` outside the scoping module would redden two correct
queries —
``app/note_links.py``'s reconciler read and ``app/api/links.py``'s ``outbound_edges``.

What *can* be said about that table is exact. The only path from a ``note_link`` row to an owner is
``source_note_id → note.owner_id``: ``target_kind`` and ``target_ref`` are strings a body typed,
``resolved_id`` is deliberately not a ``ForeignKey``, and ``id``/``created_at`` say nothing about
anybody. So a query over this table that does not constrain ``source_note_id`` has **nothing** that
could scope it, whatever else it filters on. In practice the constraint is one of exactly two
shapes,
and both are already here: a single ``note.id`` that arrived through ``NoteFromRef`` and therefore
through ``authorize_note`` (``outbound_edges``, ``reconcile_note_links``), or a subquery of the
owner's own note ids (``resolve_pending_note_links``'s ``note_ids_owned_by``, and
``notes_linking_to``'s join onto an owner-scoped ``Note``).

Rule 3 asserts the **necessary** condition and says so out loud: it cannot tell a scoped
``source_note_id`` from an unscoped one. It does not have to, because rules 1 and 2 cover the
sufficient half — any ``Note`` query the constraint leans on is itself under them, so there is
nowhere left under ``app/`` for an unscoped note id to come from. That decomposition is the whole
reason this rule can exist without a `note_link.owner_id` column to point at.

Every scan here is over the AST rather than the raw text, so this docstring does not trip the guards
it is explaining — and this file's own prose is why that matters, the same lesson
``frontend/tests/no-html-injection.test.ts`` learned from four docstrings that merely mentioned the
thing they warned about.
"""

import ast
import inspect
import types
import typing
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Select, Table, select
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, ColumnClause
from sqlalchemy.sql.visitors import iterate

from app.auth import authorization
from app.auth.principal import Principal
from app.models import Note

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


@dataclass(frozen=True)
class QuerySite:
    """One place a module builds a query naming a model, and enough context to judge it.

    ``statement`` is the **outermost expression** the builder call sits inside — the whole
    ``session.scalars(select(NoteLink).where(...)).all()`` chain, not just the ``select(...)`` —
    which
    lets rule 3 ask whether the clause it needs is anywhere in the same statement. Scoping it
    to the expression rather than to the enclosing function is deliberate: a ``source_note_id``
    mentioned three statements away in the same function would otherwise satisfy a query it has
    nothing to do with.
    """

    filename: str
    function: str | None
    lineno: int
    builder: str
    statement: ast.expr | None


def query_sites(
    source: str,
    *,
    model: str,
    builders: frozenset[str] = QUERY_BUILDERS,
    filename: str = "<memory>",
) -> list[QuerySite]:
    """Every place ``source`` hands ``model`` to one of ``builders``, attributed to its function.

    The one scanner behind rules 1, 2b and 3, so the three cannot drift into disagreeing about what
    counts as a query. ``function`` is ``None`` for a query built at module level, which is itself a
    finding rather than a gap: rule 2b requires every note query in the scoping module to sit inside
    a function it can name.
    """
    sites: list[QuerySite] = []

    def visit(node: ast.AST, function: str | None, statement: ast.expr | None) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            function = node.name

        if isinstance(node, ast.Call):
            builder = _called_name(node)
            if builder in builders:
                # `model` anywhere in an argument, so `select(Note.id, Note.title)` — a projection,
                # which is exactly what a list endpoint reaches for — is caught alongside
                # `select(Note)`.
                for argument in node.args:
                    names = (inner for inner in ast.walk(argument) if isinstance(inner, ast.Name))
                    if any(name.id == model for name in names):
                        sites.append(
                            QuerySite(
                                filename=filename,
                                function=function,
                                lineno=node.lineno,
                                builder=builder,
                                statement=statement,
                            )
                        )
                        break

        for child in ast.iter_child_nodes(node):
            # An expression hanging directly off a statement is that statement's expression root;
            # everything below it inherits the root rather than becoming one.
            hangs_off_a_statement = isinstance(node, ast.stmt) and isinstance(child, ast.expr)
            visit(child, function, child if hangs_off_a_statement else statement)

    visit(ast.parse(source), None, None)
    return sites


def note_queries(source: str, *, filename: str = "<memory>") -> list[str]:
    """Every place the source builds a query naming ``Note``, as `filename:lineno: builder`.

    KAN-965 moved the scan itself into ``query_sites`` so rules 1, 2b and 3 share one; the strings
    this returns, and therefore every assertion below that reads them, are byte-identical to what
    KAN-535 pinned.
    """
    return sorted(
        f"{site.filename}:{site.lineno}: {site.builder}(… Note …)"
        for site in query_sites(source, model="Note", filename=filename)
    )


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


# --- Rule 2: every note query in the scoping module is scoped, or argued for ---------------------

ALICE = Principal(id=uuid.UUID("11111111-1111-4111-8111-111111111111"), email="alice@example.com")

SAMPLE_ARGUMENTS: dict[object, object] = {
    Principal: ALICE,
    uuid.UUID: ALICE.id,
    str: "a value nothing here asserts against",
    int: 7,
    Iterable[str]: ("a value nothing here asserts against",),
    Iterable[int]: (7,),
}
"""One sample value per parameter annotation the scoping module's factories use.

Keyed on the annotation rather than on the parameter name, so a new factory taking a familiar
type is callable with nothing written for it, and a factory taking an unfamiliar one is a **failure
naming the parameter** rather than a skip. The values are deliberately uninteresting: this sweep
asks what the statement's ``WHERE`` clause is *shaped* like, never what it would return.
"""

UNSCOPED_BY_DESIGN: dict[str, str] = {
    "note_addressed_as_ref": (
        "ADR 0008 spelling one of a note's name, and unscoped for the reason the module docstring "
        "gives: `authorize_note` cannot answer `403` for somebody else's note if the fetch never "
        "found it, so a `WHERE owner_id` here would turn every 403 into a 404. `note.ref` is "
        "unique, so this is at most one row, and it goes straight to `authorize_note`."
    ),
    "note_addressed_as_id": (
        "ADR 0008 spelling two — the one `session.get(Note, …)` would also serve, and which this "
        "file's rule-1 carve-out already sanctions in that form. Same reason as "
        "`note_addressed_as_ref`; it exists as a statement rather than a `get` so both spellings "
        "of a note's name run down one code path instead of two that have to agree."
    ),
}
"""The whole allow-list, one written reason each. Two entries because ADR 0008 has two spellings.

An entry here is not a suppression, it is a claim — "this statement is unscoped and that is
correct" — and ``test_the_allow_list_is_consulted_rather_than_decorative`` checks the claim both
ways: the function has to exist, and it has to *still* be unscoped. So an entry cannot outlive its
function or its reason. A third entry is a diff of this dict with an argument in it, which is the
only way an allow-list stays short.
"""


def note_selector_factories(module: types.ModuleType = authorization) -> dict[str, object]:
    """Every function ``module`` defines that hands back a ``Select``, keyed on its name.

    Discovery is by **return annotation**, which is what makes the sweep cover a factory written
    after this file. SQLAlchemy's subscript is erased at runtime — a ``Select[tuple[Note]]``
    annotation evaluates to the bare ``Select`` class — so the annotation cannot say *which* table
    the statement is over, which is why the caller asks the built statement instead.
    """
    found: dict[str, object] = {}
    for name, function in inspect.getmembers(module, inspect.isfunction):
        if function.__module__ != module.__name__:
            continue
        returned = typing.get_type_hints(function).get("return")
        if isinstance(returned, type) and issubclass(returned, Select):
            found[name] = function
    return found


def statement_from(name: str, function: object) -> Select:
    """Call ``function`` with a sample value per parameter, and hand back the statement it built."""
    hints = typing.get_type_hints(function)
    arguments = []
    for parameter in inspect.signature(function).parameters:  # type: ignore[arg-type]
        annotation = hints.get(parameter)
        assert annotation in SAMPLE_ARGUMENTS, (
            f"{name}({parameter}: {annotation!r}) — this sweep has no sample value for that "
            "annotation, so it cannot call the factory and therefore cannot check its owner "
            "scoping. Add one to SAMPLE_ARGUMENTS; do not leave the factory unchecked."
        )
        arguments.append(SAMPLE_ARGUMENTS[annotation])
    return function(*arguments)  # type: ignore[operator]


def tables_touched(statement: Select) -> set[str]:
    """Every table named anywhere in ``statement``, so a factory over another table is skipped."""
    return {element.name for element in iterate(statement) if isinstance(element, Table)}


def owner_predicates(statement: Select) -> list[str]:
    """Every ``note.owner_id == <bound value>`` in ``statement``'s ``WHERE`` clause, as SQL.

    Read off the ``whereclause`` rather than off the compiled string, for two reasons that are both
    about a probe proving what it claims. ``select(Note)`` names *every* column of ``note`` in its
    columns clause, ``owner_id`` included, so a substring search over the whole statement is
    satisfied by a projection and cannot tell a filter from one. And the right-hand side has to be a
    ``BindParameter``, so ``Note.owner_id == Note.owner_id`` — a clause that is present, renders,
    and
    scopes nothing — is reported unscoped rather than counted.
    """
    where = statement.whereclause
    if where is None:
        return []

    found: list[str] = []
    for element in iterate(where):
        if not (isinstance(element, BinaryExpression) and element.operator is operators.eq):
            continue
        for column, other in ((element.left, element.right), (element.right, element.left)):
            if (
                isinstance(column, ColumnClause)
                and column.name == "owner_id"
                and column.table is not None
                and getattr(column.table, "name", None) == Note.__tablename__
                and isinstance(other, BindParameter)
            ):
                found.append(str(element))
    return found


def unscoped_note_selectors(module: types.ModuleType = authorization) -> list[str]:
    """The names of ``module``'s ``Select`` factories whose statements touch ``note`` unscoped.

    The allow-list is *not* applied here, so the two tests below can read the same list for opposite
    purposes: one asserts nothing outside the allow-list is in it, the other asserts everything
    inside the allow-list still is.
    """
    offenders: list[str] = []
    for name, function in sorted(note_selector_factories(module).items()):
        statement = statement_from(name, function)
        if Note.__tablename__ not in tables_touched(statement):
            continue
        if owner_predicates(statement):
            continue
        offenders.append(name)
    return offenders


def test_every_note_selector_in_the_scoping_module_is_owner_scoped_or_argued_for() -> None:
    """The blind spot KAN-965 exists for: rule 1 exempts this module, so nothing checked it.

    Drop ``notes_owned_by``'s composition — or its ``where`` — from any factory in
    ``app/auth/authorization.py`` and this fails naming that factory.
    """
    factories = note_selector_factories()
    assert len(factories) >= 6, (
        "the sweep found almost no `Select` factories in the scoping module, so it would pass "
        f"vacuously — found {sorted(factories)}"
    )

    offenders = [name for name in unscoped_note_selectors() if name not in UNSCOPED_BY_DESIGN]

    assert offenders == [], (
        "SLICES §V1: every note query is scoped with `WHERE owner_id = :caller`. These factories "
        "in app/auth/authorization.py build a statement over `note` with no such clause: "
        + ", ".join(offenders)
        + ". Compose onto `notes_owned_by` (or `note_ids_owned_by`), or — if the read is genuinely "
        "meant to be unscoped, the way ADR 0008's two single-row fetches are — add it to "
        "UNSCOPED_BY_DESIGN with the reason written out."
    )


def test_the_allow_list_is_consulted_rather_than_decorative() -> None:
    """Both halves of an allow-list entry's claim, so it cannot outlive what it excuses.

    Delete an entry and the test above goes red naming the function; leave one behind after its
    function is renamed, deleted or *scoped*, and this one does.
    """
    factories = note_selector_factories()
    unscoped = unscoped_note_selectors()

    for name, reason in sorted(UNSCOPED_BY_DESIGN.items()):
        assert name in factories, (
            f"UNSCOPED_BY_DESIGN names `{name}`, which is not a `Select` factory in "
            "app/auth/authorization.py any more. Delete the entry — an allow-list that names "
            "functions that no longer exist is how the next real one gets waved through."
        )
        assert len(reason) > 80, (
            f"`{name}`'s allow-list entry has no argument in it. An unscoped note query is a "
            "decision; write the reason down where the next person will read it."
        )
        assert name in unscoped, (
            f"`{name}` is owner-scoped now, so its UNSCOPED_BY_DESIGN entry is stale and is "
            "silently excusing a rule it no longer needs excusing from. Delete the entry."
        )


def test_the_owner_scoping_probe_catches_every_shape_of_the_bug() -> None:
    """The positive control. An emptiness assertion proves nothing until the probe is shown firing.

    Each of these is a real statement, so what runs is the same code path the sweep runs — and each
    is built **locally**. A control that called ``authorization.notes_owned_by`` would go red for
    the production code being mutated, which is the one thing a control must not do: it is how "the
    probe works" and "the code is correct" become one failure that proves neither. Reading the real
    statements is rule 2's job, above.
    """
    assert owner_predicates(select(Note)) == []
    assert owner_predicates(select(Note).order_by(Note.updated_at.desc())) == []
    assert owner_predicates(select(Note).where(Note.ref == "NOTE-1")) == []
    assert owner_predicates(select(Note.id, Note.title).where(Note.title == "A note")) == []
    assert owner_predicates(select(Note).where(Note.owner_id == Note.owner_id)) == [], (
        "a tautology on the owner column renders as a clause and scopes nothing; the bound-value "
        "requirement is what tells the two apart"
    )

    # And it stays quiet about nothing that is genuinely scoped, however the clause got there.
    scoped = select(Note).where(Note.owner_id == ALICE.id)
    assert owner_predicates(scoped) != []
    assert owner_predicates(scoped.where(Note.path == "proj").limit(50)) != [], (
        "composing onto a scoped statement cannot remove the clause, and the probe has to see that"
    )


def test_the_factory_sweep_reports_an_unscoped_factory_it_has_never_seen() -> None:
    """The other half of the positive control: that *discovery* works, not just the probe.

    A stub module rather than a temporary edit to `app/auth/authorization.py`, so the deliberately
    bad factory is permanent and reviewable instead of a mutation somebody has to re-run to trust.
    `notes_in_folder` is the next list endpoint this repository is plausibly going to grow (V7's
    folder tree), written the way it gets written when the owner filter is still obviously going to
    be added.
    """

    def notes_in_folder(principal: Principal) -> Select[tuple[Note]]:
        return select(Note).where(Note.path == "proj").order_by(Note.updated_at.desc())

    def notes_in_folder_scoped(principal: Principal) -> Select[tuple[Note]]:
        # Its own scoped base rather than `authorization.notes_owned_by`, for the reason the probe's
        # control gives: a control that moves when production moves is not one.
        return select(Note).where(Note.owner_id == principal.id).where(Note.path == "proj")

    def users_seen(principal: Principal) -> Select[tuple[uuid.UUID]]:
        return select(Note.owner_id.distinct()).where(Note.owner_id == principal.id)

    def not_a_query(principal: Principal) -> str:
        return str(principal.id)

    stub = types.ModuleType("a_stub_scoping_module")
    for name, function in [
        ("notes_in_folder", notes_in_folder),
        ("notes_in_folder_scoped", notes_in_folder_scoped),
        ("users_seen", users_seen),
        ("not_a_query", not_a_query),
    ]:
        function.__module__ = stub.__name__
        setattr(stub, name, function)

    assert set(note_selector_factories(stub)) == {
        "notes_in_folder",
        "notes_in_folder_scoped",
        "users_seen",
    }, "discovery is by return annotation, so the non-factory is not a `Select` and is not swept"

    assert unscoped_note_selectors(stub) == ["notes_in_folder"], (
        "the sweep has to name the unscoped factory and nothing else — a composed one and a scoped "
        "projection are both correct"
    )


# --- Rule 2b: and no note query hides in a function the sweep cannot call ------------------------


def test_every_note_query_in_the_scoping_module_sits_in_a_function_the_sweep_covers() -> None:
    """Rule 2 can only check a function it can *call*, which means one returning a ``Select``.

    A helper in that module that ran its own query and returned rows would be invisible to the sweep
    and exempt from rule 1 by living there — the one hole left once rule 2 exists. So every
    ``select(… Note …)`` written in the module has to be inside a function rule 2 covers, or inside
    one the allow-list names.
    """
    sites = query_sites(
        SCOPING_MODULE.read_text(encoding="utf-8"), model="Note", filename=SCOPING_MODULE.name
    )
    assert sites, "no note query found in the scoping module at all; this guard proves nothing"

    covered = set(note_selector_factories()) | set(UNSCOPED_BY_DESIGN)
    stray = sorted(
        f"{site.filename}:{site.lineno}: {site.function or '<module level>'}"
        for site in sites
        if site.function not in covered
    )

    assert stray == [], (
        "a `Note` query in app/auth/authorization.py that is not inside a function returning a "
        "`Select` cannot be checked for owner scoping by the sweep above, and rule 1 exempts this "
        "module. Return the statement instead of the rows: " + ", ".join(stray)
    )


def test_the_query_site_scan_attributes_a_query_to_the_function_it_is_in() -> None:
    """The positive control for the scan the test above reads."""
    inside = "def sneaky(session, principal):\n    return session.scalars(select(Note)).all()\n"
    [site] = query_sites(inside, model="Note")
    assert site.function == "sneaky"
    assert site.builder == "select"

    [top_level] = query_sites("EVERY_NOTE = select(Note)\n", model="Note")
    assert top_level.function is None, "a module-level query belongs to no function and says so"

    nested = (
        "def outer(principal):\n"
        "    def inner():\n"
        "        return select(Note.id)\n"
        "    return inner\n"
    )
    [site] = query_sites(nested, model="Note")
    assert site.function == "inner", "the innermost function is the one that owns the query"


# --- Rule 3: note_link, whose owner is one join away ----------------------------------------------

LINK_QUERY_BUILDERS = frozenset({"select", "select_from", "query", "update", "delete", "join"})
"""Rule 1's three builders plus the three ways this table is reached that ``Note``'s never is.

``update`` and ``delete`` are here because a bulk write over ``note_link`` is exactly as
cross-owner-capable as a read — ``resolve_pending_note_links`` is an ``update`` and is the reason
this set is not rule 1's — and ``join`` because ``notes_linking_to`` brings the table in through one
rather than through a ``select``. The set is wider than ``QUERY_BUILDERS`` on purpose and rule 1's
is deliberately left alone: a `Note` reached by any of the three extra words is already inside a
statement rule 1 and rule 2 both see.
"""

SOURCE_NOTE_COLUMN = "source_note_id"


def mentions_column(node: ast.expr | None, model: str, column: str) -> bool:
    """Whether ``node``'s subtree reads ``model.column`` as a column.

    An attribute access, never a keyword: ``NoteLink(source_note_id=note.id)`` and
    ``.values(source_note_id=…)`` both write that column and neither one filters on it, so a probe
    that accepted the word would call a row-builder a scoping clause.
    """
    if node is None:
        return False
    return any(
        isinstance(inner, ast.Attribute)
        and inner.attr == column
        and isinstance(inner.value, ast.Name)
        and inner.value.id == model
        for inner in ast.walk(node)
    )


def link_query_sites() -> list[QuerySite]:
    """Every ``note_link`` query under ``app/``, wherever it is written."""
    modules = sorted(APP_ROOT.rglob("*.py"))
    assert len(modules) >= 4, "the glob found almost nothing — the guard would pass vacuously"

    sites: list[QuerySite] = []
    for path in modules:
        sites += query_sites(
            path.read_text(encoding="utf-8"),
            model="NoteLink",
            builders=LINK_QUERY_BUILDERS,
            filename=path.name,
        )
    return sites


def test_every_note_link_query_constrains_the_source_note() -> None:
    """Rule 3, and the necessary condition is the whole claim — see the module docstring.

    ``note_link`` has no owner column, so ``source_note_id`` is the only column on it that leads to
    one. A query that does not constrain it has nothing that could scope it, whatever else it
    filters on; a query that does is scoped exactly as well as the note id it was given, which rules
    1 and 2 are what make trustworthy.
    """
    sites = link_query_sites()
    assert sites, "no note_link query found under app/ at all; this guard proves nothing"

    offenders = sorted(
        f"{site.filename}:{site.lineno}: {site.function or '<module level>'} — "
        f"{site.builder}(… NoteLink …)"
        for site in sites
        if not mentions_column(site.statement, "NoteLink", SOURCE_NOTE_COLUMN)
    )

    assert offenders == [], (
        "a `note_link` query with no `NoteLink.source_note_id` constraint has nothing that could "
        "scope it to an owner: that column is the table's only path to `note.owner_id` "
        "(app/models/note_link.py). Filter on a note id that has been through `authorize_note`, or "
        "on `app.auth.note_ids_owned_by(...)` as a subquery, or join to an owner-scoped `Note`. "
        "Found: " + ", ".join(offenders)
    )


def test_the_link_query_scan_and_its_probe_are_not_vacuous() -> None:
    """The positive control for rule 3, in the three ways it could quietly pass.

    A query with no source constraint has to be *reported*; the probe must not accept the same word
    spelled as a keyword, which is how the reconciler's own row-builder would otherwise look like a
    filter; and the scan has to see an ``update`` and a ``join``, since those are two of the four
    real call sites and neither is a ``select``.
    """
    unscoped = "rows = session.scalars(select(NoteLink).where(NoteLink.target_ref == t)).all()\n"
    [site] = query_sites(unscoped, model="NoteLink", builders=LINK_QUERY_BUILDERS)
    assert not mentions_column(site.statement, "NoteLink", SOURCE_NOTE_COLUMN)

    scoped = "rows = session.scalars(select(NoteLink).where(NoteLink.source_note_id == n)).all()\n"
    [site] = query_sites(scoped, model="NoteLink", builders=LINK_QUERY_BUILDERS)
    assert mentions_column(site.statement, "NoteLink", SOURCE_NOTE_COLUMN)

    written = "session.execute(update(NoteLink).values(source_note_id=note.id))\n"
    [site] = query_sites(written, model="NoteLink", builders=LINK_QUERY_BUILDERS)
    assert site.builder == "update"
    assert not mentions_column(site.statement, "NoteLink", SOURCE_NOTE_COLUMN), (
        "a keyword argument writes the column; only an attribute access filters on it"
    )

    built = "session.add(NoteLink(source_note_id=note.id, target_kind=k, target_ref=r))\n"
    assert query_sites(built, model="NoteLink", builders=LINK_QUERY_BUILDERS) == [], (
        "constructing a row is not building a query, and the reconciler does it on every save"
    )

    joined = "statement = notes_owned_by(p).join(NoteLink, NoteLink.source_note_id == Note.id)\n"
    [site] = query_sites(joined, model="NoteLink", builders=LINK_QUERY_BUILDERS)
    assert site.builder == "join"
    assert mentions_column(site.statement, "NoteLink", SOURCE_NOTE_COLUMN)


def test_the_link_query_scan_reaches_every_module_that_queries_the_table() -> None:
    """The scan is a glob, so what it *found* is worth pinning rather than assuming.

    Four call sites in three modules today, and the module list is the assertion: a fourth module
    starting to query this table is a thing to notice, and a call site disappearing from one of
    these
    three means the guard is watching less than it was.
    """
    found = {site.filename for site in link_query_sites()}

    assert found == {"note_links.py", "links.py", "authorization.py"}, (
        "the set of modules querying `note_link` moved. If that is correct, say so here; if a "
        f"module dropped out, this guard just stopped covering it. Found: {sorted(found)}"
    )
