"""``?q=``, everything about it that needs no database — KAN-558, SLICES §V4's unit row.

That row asks for "query parsing handles an empty string, a single term, a quoted phrase, and
characters that would otherwise be ``tsquery`` syntax". Two of those four are *not* Python's to
handle, and saying which is which is most of what this file is for:

- **The blank rule is ours**, so it is asserted here as a pure function: an absent ``q`` is not a
  search, a present one with no non-whitespace character is a `400`, and a usable one arrives
  stripped. See ``app/api/search.py`` for the argument.
- **The grammar is Postgres'**, and what this layer can prove about it is the property that makes it
  safe to hand a stranger's string to: the term is a **bound parameter**. ``&``, ``|``, ``!``,
  ``(``, ``%``, ``_`` and a quote character are inert because they never reach SQL as text, which is
  a claim about the compiled statement and needs no connection to check. What they *mean* to the
  tsquery parser is Postgres' business and is pinned in
  ``tests/integration/test_note_search_api.py``.

The statement assertions compile against the **postgresql** dialect deliberately. A default-dialect
compile would render ``ts_rank`` and ``@@`` happily and hide nothing, but the emitted SQL is what
the card asked to see and it is dialect-specific.

``search_vector`` is checked to be absent from the **columns clause** rather than from the SQL,
since it is named in the ``WHERE`` and inside ``ts_rank`` by construction. That is the whole
subtlety of KAN-557's ``deferred=True`` surviving this card."""

import re
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.search import empty_search_query, search_term
from app.auth.authorization import SEARCH_CONFIG, notes_matching, notes_owned_by
from app.auth.principal import Principal
from app.models.note import SEARCH_VECTOR_EXPRESSION

ALICE = Principal(id=uuid.UUID("11111111-1111-4111-8111-111111111111"), email="alice@example.com")


def compiled(term: str) -> postgresql.dialect:
    return notes_matching(ALICE, term).compile(dialect=postgresql.dialect())


def sql(term: str) -> str:
    return str(compiled(term))


def columns_clause(statement_sql: str) -> str:
    """Everything between ``SELECT`` and the first ``FROM``, which is what gets loaded."""
    matched = re.search(r"\bSELECT\b(.*?)\bFROM\b", statement_sql, re.DOTALL)
    assert matched is not None, f"could not find a columns clause in: {statement_sql}"
    return matched.group(1)


# --- the blank rule -------------------------------------------------------------------------------


def test_an_absent_q_is_not_a_search() -> None:
    assert search_term(None) is None


def test_an_empty_q_is_refused() -> None:
    with pytest.raises(HTTPException) as raised:
        search_term("")

    assert raised.value.status_code == 400
    assert raised.value.detail == {
        "error": {
            "code": "empty_search_query",
            "message": (
                "q was empty: pass a term to search for, or omit q entirely to list every note"
            ),
        }
    }


@pytest.mark.parametrize("blank", ["", " ", "   ", "\t", "\n", " \t\n "])
def test_every_spelling_of_blank_is_refused_the_same_way(blank: str) -> None:
    """``?q=`` and ``?q=%20%20`` are the same non-request, so they get the same answer."""
    with pytest.raises(HTTPException) as raised:
        search_term(blank)

    assert raised.value.status_code == 400
    assert raised.value.detail == empty_search_query().detail


def test_a_usable_term_arrives_stripped() -> None:
    """The value returned is the value queried with — one term, not one validated and one used."""
    assert search_term("runbook") == "runbook"
    assert search_term("  runbook  ") == "runbook"
    assert search_term("\treading list\n") == "reading list"


@pytest.mark.parametrize(
    "term",
    [
        "runbook",
        '"reading list"',
        "reading -list",
        "&|!()",
        "50% of a_b",
        "it's",
        "the",
        "x" * 5000,
    ],
)
def test_anything_with_a_character_in_it_is_a_search(term: str) -> None:
    """Including the hostile ones. What they *match* is Postgres' answer, not this layer's — and
    ``the`` and ``&|!()`` matching nothing is a `200` with no notes, never a refusal, because the
    status code must not depend on the dictionary (``app/api/search.py``)."""
    assert search_term(term) == term


def test_the_refusal_carries_no_extra() -> None:
    """``test_error_extras_stay_addressable`` polices two; this pins that there is not even one, so
    ADR 0005's ``arg`` slot stays empty for this code rather than a whitespace string."""
    assert set(empty_search_query().detail["error"]) == {"code", "message"}


# --- the statement --------------------------------------------------------------------------------


def test_the_search_query_keeps_the_owner_scoping() -> None:
    """The card's first requirement, read off the SQL: a ``WHERE`` clause, not a loop."""
    statement_sql = sql("runbook")

    assert "note.owner_id = " in statement_sql
    assert "WHERE" in statement_sql
    # And it is the *same* clause the unfiltered list uses, rather than a second spelling of it.
    unfiltered = str(notes_owned_by(ALICE).compile(dialect=postgresql.dialect()))
    owner_clause = unfiltered.split("WHERE")[1].strip()
    assert owner_clause in statement_sql


def test_the_predicate_is_websearch_to_tsquery_against_the_stored_vector() -> None:
    statement_sql = sql("runbook")

    assert "note.search_vector @@ websearch_to_tsquery(" in statement_sql
    # `.match()` would render `plainto_tsquery` here; see `notes_matching` for why it is declined.
    assert "plainto_tsquery" not in statement_sql
    assert "to_tsquery(%(to_tsquery" not in statement_sql, "bare to_tsquery raises on user input"


def test_the_order_is_relevance_then_the_id_tie_break() -> None:
    """Both keys, in this order. A rank with no tie-break is a non-deterministic order (SLICES §V4);
    an ``id`` with no rank is a list that does not rank."""
    statement_sql = sql("runbook")
    order_by = statement_sql.split("ORDER BY")[1]

    assert re.search(r"ts_rank\(note\.search_vector, websearch_to_tsquery\(.*?\)\) DESC", order_by)
    assert order_by.strip().endswith("note.id DESC")


def test_the_rank_and_the_predicate_use_one_tsquery() -> None:
    """Ranking by a query other than the one you filtered on is a silent wrongness, so the tsquery
    is built once and both places render the *same* bind parameter."""
    statement = compiled("runbook")
    statement_sql = str(statement)

    names = set(re.findall(r"websearch_to_tsquery\(%\((\w+)\)s, %\((\w+)\)s\)", statement_sql))
    assert len(names) == 1, f"more than one tsquery in the statement: {names}"
    assert statement_sql.count("websearch_to_tsquery(") == 2, "the predicate and the rank, no more"
    assert list(statement.params.values()).count("runbook") == 1


def test_the_search_vector_is_never_in_the_columns_clause() -> None:
    """KAN-557's ``deferred=True``, surviving a card that names the column twice.

    The order-by is the trap: SQLAlchemy adds order-by expressions to the columns clause for a
    ``DISTINCT`` or a union, and a future edit reaching for either would pull a body-sized tsvector
    into every row of every search result.
    """
    clause = columns_clause(sql("runbook"))

    assert "search_vector" not in clause, f"the vector is being loaded: {clause}"
    for expected in ("note.ref", "note.id", "note.title", "note.body", "note.path"):
        assert expected in clause, f"{expected} should still be selected"
    # It is in the statement, just not in the part that gets loaded.
    assert "search_vector" in sql("runbook")


def test_the_unfiltered_list_does_not_load_it_either() -> None:
    """The control for the test above: if `select(Note)` loaded it anyway, that test proves nothing
    about the search path."""
    assert "search_vector" not in columns_clause(
        str(notes_owned_by(ALICE).compile(dialect=postgresql.dialect()))
    )


# --- the term is data, never syntax ---------------------------------------------------------------


@pytest.mark.parametrize(
    "term",
    [
        "&|!()",
        "foo &",
        '"reading list"',
        "reading -list",
        "50% of a_b",
        "'; DROP TABLE note; --",
        "\\",
        "x" * 5000,
    ],
)
def test_the_term_is_a_bound_parameter_and_never_reaches_the_sql(term: str) -> None:
    """Why ``%`` and ``_`` are inert, and why a quote is not an injection: the string is data.

    A ``LIKE``-based implementation of this feature would have made ``%`` and ``_`` wildcards and
    would have had to escape them; this one cannot, because the term is never part of the
    statement's text. That is a property of the compiled statement, so it is checkable here."""
    statement = compiled(term)

    assert term not in str(statement), "the term was rendered into the SQL"
    assert term in statement.params.values(), "the term is not among the bound parameters"


# --- the query's dictionary is the vector's dictionary --------------------------------------------


def test_the_query_is_parsed_with_the_configuration_the_vector_was_built_with() -> None:
    """The quietest way for this card to be wrong (``app/auth/authorization.py``).

    Query as ``simple`` against an ``english`` vector and every exact word still matches, so nothing
    looks broken — but stemming is gone and ``runbooks`` stops finding ``runbook``. The two literals
    live in different packages' worth of concern (a query here, a stored column in the model and in
    migration ``0002``), so they are compared rather than trusted.
    """
    assert SEARCH_CONFIG == "english"
    assert f"'{SEARCH_CONFIG}'" in SEARCH_VECTOR_EXPRESSION
    assert SEARCH_CONFIG in compiled("runbook").params.values()
