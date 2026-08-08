"""The alarm on a cross-package coupling that otherwise has none.

`kaya-client` fills ADR 0005 §contract 3's ``arg`` slot — the fourth column of
``error<TAB>code<TAB>message<TAB>arg`` — from **the first scalar extra a refusal carries, in
insertion order**. Deriving it from the payload rather than from a list of blessed key names is the
right call: a list here would go stale the first time this package added a code nobody remembered to
update it for.

But the derivation is only unambiguous while a refusal carries **at most one** scalar extra, and
that is a property of *this* package, enforced nowhere in it. Every ``error_body(...)`` call site
below satisfies it today. If one grows a second scalar, the CLI silently starts putting whichever
key was inserted first into the ``arg`` slot, and nothing anywhere goes red — the client cannot see
this file, and the dependency arrow (ADR 0004: adapters depend on the client, the client depends on
neither) means it never will.

So the guard lives here, where the change would actually be made, and it is deliberately blunt:
**a refusal may attach one extra.** Attaching two is not forbidden — ADR 0009's `409` has to, and is
allow-listed by name — it just cannot happen *quietly*. A red test here says: go and check what
``arg`` will now resolve to, and pin it in
`kaya-client/tests/test_arg_slot.py`'s corpus.

The scan is over the AST rather than the raw text, so this docstring does not trip the guard it is
explaining — the same reason `test_no_unscoped_note_query.py` gives.
"""

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

BUILDER = "error_body"

ALLOWED_MULTI_EXTRA: dict[tuple[str, str], tuple[str, ...]] = {
    ("concurrency.py", "note_conflict"): ("attempted", "stored"),
}
"""The refusals allowed more than one extra, keyed on ``(module, code)`` so a line move is not a
failure. One entry, and it earns it: ADR 0009's `409` carries two whole notes precisely so a caller
can diff them and retry, and both are objects — so `kaya-client` resolves ``arg`` to ``""`` and
carries the notes through unflattened, which
`kaya-client/tests/test_arg_slot.py::test_the_conflict_keeps_two_whole_notes_and_still_has_an_empty_arg`
pins from the other side.

**Adding a row here is a decision, not a formality.** Two *scalar* extras would make the ``arg``
slot a coin toss between them."""


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _code_argument(node: ast.Call) -> str:
    """The refusal's ``code``, when it is a literal. ``app/api/errors.py`` derives one from the
    status instead, which is fine and is reported as ``<derived>`` — it attaches no extras."""
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return "<derived>"


Site = tuple[str, str, tuple[str, ...]]


def error_body_calls(source: str, *, filename: str = "<memory>") -> list[Site]:
    """Every ``error_body(...)`` in the source, as ``(filename, code, extra keyword names)``."""
    found: list[Site] = []

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or _called_name(node) != BUILDER:
            continue
        extras = tuple(keyword.arg for keyword in node.keywords if keyword.arg is not None)
        found.append((filename, _code_argument(node), extras))

    return sorted(found)


def _call_sites() -> list[Site]:
    modules = sorted(APP_ROOT.rglob("*.py"))
    assert len(modules) >= 4, "the glob found almost nothing — the guard would pass vacuously"

    sites: list[Site] = []
    for path in modules:
        sites += error_body_calls(path.read_text(encoding="utf-8"), filename=path.name)
    return sites


def test_the_scan_finds_the_refusals_that_are_known_to_exist() -> None:
    """Without this, deleting ``error_body`` or renaming it makes every assertion below vacuous."""
    codes = {code for _, code, _ in _call_sites()}

    assert {"authentication_required", "invalid_token", "note_not_found", "note_conflict"} <= codes


def test_no_refusal_attaches_a_second_extra_without_saying_so() -> None:
    """The guard. One extra per refusal, unless it is allow-listed by name.

    A second extra is where the CLI's ``arg`` slot stops having an obvious answer. It is not banned
    — the `409` needs two — but it has to be a line in ``ALLOWED_MULTI_EXTRA`` that someone wrote
    on purpose, having gone and checked what `kaya-client` will put in the fourth column.
    """
    offenders = [
        f"{filename}: {code}({', '.join(extras)})"
        for filename, code, extras in _call_sites()
        if len(extras) > 1 and ALLOWED_MULTI_EXTRA.get((filename, code)) != extras
    ]

    assert offenders == [], (
        "ADR 0005 §contract 3's `arg` is the first scalar extra in insertion order, so a second "
        "extra changes what the CLI prints in the fourth column. Add a row to ALLOWED_MULTI_EXTRA "
        "here and a row to kaya-client/tests/test_arg_slot.py's corpus, having checked what `arg` "
        "now resolves to. Found: " + ", ".join(offenders)
    )


def test_the_allow_list_has_no_stale_rows() -> None:
    """An allow-list outliving what it excused silently permits the next thing with that name."""
    live = {(filename, code): extras for filename, code, extras in _call_sites()}

    for key, extras in ALLOWED_MULTI_EXTRA.items():
        assert live.get(key) == extras, f"{key} is allow-listed but no longer looks like that"


def test_the_guard_catches_the_shape_of_the_bug() -> None:
    """An emptiness assertion passes for the wrong reason unless it is shown failing."""
    two_scalars = 'error_body("invalid_note_ref", "no", ref=raw, field="title")\n'
    one_scalar = 'error_body("invalid_note_ref", "no", ref=raw)\n'
    none = 'error_body("note_not_found", "no such note")\n'

    assert error_body_calls(two_scalars) == [("<memory>", "invalid_note_ref", ("ref", "field"))]
    assert error_body_calls(one_scalar) == [("<memory>", "invalid_note_ref", ("ref",))]
    assert error_body_calls(none) == [("<memory>", "note_not_found", ())]

    # And stays quiet on a call that is not this builder at all.
    assert error_body_calls('build_something("x", a=1, b=2)\n') == []
