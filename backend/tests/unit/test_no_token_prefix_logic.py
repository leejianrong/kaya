"""ADR 0002's first structural trap, made mechanical.

Pandan still accepts pre-rebrand `kanban_pat_…` tokens through an accepted-prefix tuple. A
`startswith` guard on the current prefix alone is precisely the bug pandan ADR 0018 had to
correct — it 401'd every already-issued token. Kaya sidesteps the entire class by having no prefix
knowledge to get wrong, and this is the test that keeps it that way.

It is worth being blunt about why a *test* and not a code review. "Reject obvious rubbish before
paying for a round trip" is a genuinely reasonable-sounding optimisation, it is the first thing an
autocomplete offers when it sees a token and a cache in one file, and the resulting bug is
invisible until an old token shows up. The negative cache is the sanctioned way to shed that load
(``app/auth/cache.py``), and it needs to know nothing about the token.

The scan is over the AST rather than the raw text, so this docstring — which names both prefixes —
does not trip the guard it is explaining.
"""

import ast
from pathlib import Path

AUTH_ROOT = Path(__file__).resolve().parents[2] / "app" / "auth"

FORBIDDEN_CALLS = frozenset(
    {
        # Every affordable way to ask "does this token start with…". Slicing and regex `match`
        # are not name-detectable, which is why the literal scan below exists as well: a prefix
        # check has to name the prefix somewhere, whatever syntax it reaches for.
        "startswith",
        "endswith",
        "removeprefix",
        "removesuffix",
    }
)

FORBIDDEN_LITERALS = ("pat_", "_pat", "pandan_pat", "kanban_pat", "kaya_pat")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Ids of the string constants that are docstrings, so prose can explain the ban freely."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            ids.add(id(body[0].value))
    return ids


def prefix_offences(source: str, *, filename: str = "<memory>") -> list[str]:
    """Every place the source looks like it is inspecting a token's shape."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    offences: list[str] = []

    for node in ast.walk(tree):
        where = f"{filename}:{getattr(node, 'lineno', 0)}"

        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CALLS:
            offences.append(f"{where}: .{node.attr}(")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            lowered = node.value.lower()
            for fragment in FORBIDDEN_LITERALS:
                if fragment in lowered:
                    offences.append(f"{where}: a token-prefix literal")
                    break

    return sorted(offences)


def test_no_module_in_app_auth_inspects_a_token_prefix() -> None:
    modules = sorted(AUTH_ROOT.rglob("*.py"))
    assert len(modules) >= 4, "the glob found almost nothing — the guard would pass vacuously"

    offences: list[str] = []
    for path in modules:
        offences += prefix_offences(path.read_text(encoding="utf-8"), filename=path.name)

    assert offences == [], (
        "ADR 0002: kaya has no token format and no prefix logic. Pandan still accepts pre-rebrand "
        "tokens, and a startswith guard is the exact bug pandan ADR 0018 had to correct. Shed "
        "load with the negative cache instead. Found: " + ", ".join(offences)
    )


def test_the_guard_catches_both_shapes_of_the_bug() -> None:
    """Emptiness assertions pass for the wrong reason; make this one prove it can fail."""
    by_method = "def resolve(t):\n    return t.startswith('legacy-') and None\n"
    by_literal = "ACCEPTED = ('pandan_pat_',)\n"
    by_regex = "import re\nOK = re.compile(r'^kanban_pat_')\n"

    assert prefix_offences(by_method) != []
    assert prefix_offences(by_literal) != []
    assert prefix_offences(by_regex) != []

    # And it stays quiet on the things the resolver legitimately does.
    assert prefix_offences("headers = {'Authorization': f'Bearer {bearer}'}\n") == []
    assert prefix_offences("key = hashlib.sha256(token.encode('utf-8')).hexdigest()\n") == []


def test_the_forwarded_header_is_the_only_thing_built_from_the_token() -> None:
    """A companion assertion the AST scan cannot make: the bearer goes out unchanged.

    ``PandanIdentityUpstream`` interpolates the token into one header and does nothing else with
    it — no trimming, no casefolding, no length check. Pandan owns the format.
    """
    source = (AUTH_ROOT / "upstream.py").read_text(encoding="utf-8")
    assert 'f"Bearer {bearer}"' in source
