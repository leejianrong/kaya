"""The single entry point behind the `kaya` console script.

There is exactly one console script (Q39) and, for now, no verbs. `kaya note list` and
`kaya note get` land in V2a together with the output layer, because ADR 0005 sequences the layer
*before* the behaviour that goes through it — adding verbs here first is precisely the retrofit
that ordering exists to avoid.

So this prints what it is and exits 0. It is not a stub that pretends: it says which slice brings
the verbs, and `scripts/not-yet.sh` shows the same courtesy in the Makefile.
"""

import sys
from collections.abc import Sequence

from kaya_cli import __version__

BANNER = (
    "kaya {version} — markdown notes, API-first.\n"
    "No verbs yet: `note list` and `note get` arrive with the output layer in V2a.\n"
    "See docs/SLICES.md."
)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the banner. Returns the process exit code.

    Takes ``argv`` so tests can call it directly rather than shelling out, and returns an int
    rather than calling ``sys.exit`` so the exit code is a value a test can assert on. V2a's
    named-code table hangs off this return.
    """
    del argv  # nothing is parsed yet, and pretending otherwise would be worse
    print(BANNER.format(version=__version__))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via the console script
    sys.exit(main(sys.argv[1:]))
