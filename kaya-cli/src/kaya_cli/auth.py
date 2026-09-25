"""Device-flow login orchestration (RFC 8628, ADR 0013, KAN-1743) — `kaya auth login`.

`kaya config set --token` (unchanged) pastes an already-minted secret and stays exactly as it is —
CI/headless environments have no browser to send a human to. `auth login` is the browser-click
alternative: obtain a `kaya_pat_…` with zero copy-pasting, by walking the CLI through RFC 8628's
device-code dance against kaya's own authorization server (ADR 0012).

**This is the one function in `kaya-cli`, besides `context.run_hook`, that does not go through
`verbs.run`/`render()` — but unlike `run_hook`, it does not swallow its own failures.** A login
that was denied or that expired is exactly the kind of outcome ADR 0005's exit table exists to
report, so `run_login` raises `KayaError` subclasses normally and lets `__main__.main`'s existing
`except KayaError` funnel turn them into a structured row and an exit code, the same as every other
verb's failure. What it shares with `run_hook` is *why* neither can be a normal verb: both are
built around something a single `Payload` cannot represent — a hook's answer must never carry a
structured refusal on stdout, and this one is a multi-step, human-in-the-loop flow (print a code,
open a browser, poll on a timer) with no one response to hand `render()` at the end. `verbs.py`'s
own `VERBS`/`LOCAL_VERBS` tables therefore carry **no row at all** for `(AUTH, LOGIN)` — the mirror
image of `verbs.BARE` (a row with no parser word) — and `tests/test_verbs.py`'s exhaustiveness
guard names it explicitly for the same reason it names `BARE`.

**No session opened via `kaya_client.open_client()`.** Both device-flow calls are unauthenticated
by RFC 8628's own design — a CLI with no credential yet is the whole point — so this module calls
`kaya_client.create_device_code`/`poll_device_token` directly against `kaya_client.api_url()`
rather than through a `KayaClient` built around a bearer that does not exist yet.
"""

import time
import webbrowser
from argparse import Namespace

from kaya_client import KayaError, api_url, config_path, create_device_code, poll_device_token
from kaya_client.config import TOKEN_ENV
from kaya_client.config import write_settings as _write_settings

from kaya_cli.failures import EXIT_OK

DEFAULT_LOGIN_SCOPE = "write"


class AccessDenied(KayaError):
    """The human denied the login on the consent screen (`POST /auth/device/{user_code}/deny`)."""

    code = "access_denied"


class ExpiredLogin(KayaError):
    """The code expired — either the server said so on a poll, or the CLI's own wait outran
    ``expires_in`` without a poll ever seeing anything but `authorization_pending`."""

    code = "expired_token"


def _try_open_browser(url: str) -> bool:
    """Best-effort. A headless box, a missing `$DISPLAY`, or `webbrowser` simply having no
    registered opener are all the same outcome from this CLI's point of view: print the link
    instead and keep polling — never a reason to fail the login."""
    try:
        return webbrowser.open(url)
    except Exception:  # noqa: BLE001 - see the comment above; any failure here just means "no browser"
        return False


def run_login(args: Namespace) -> int:
    """`kaya auth login [--scope read|write]`. See the module docstring for why this bypasses
    `verbs.run`/`render()` while still raising through `main`'s ordinary failure path.
    """
    scope = getattr(args, "scope", None) or DEFAULT_LOGIN_SCOPE
    base_url = api_url()

    code = create_device_code(base_url, scope=scope)
    print(f"First copy your code: {code['user_code']}")
    print(f"Then visit: {code['verification_uri']}")
    if _try_open_browser(code["verification_uri_complete"]):
        print("(opened in your browser)")
    else:
        print(f"Or open this link directly: {code['verification_uri_complete']}")
    print("Waiting for approval…")

    interval = code["interval"]
    deadline = time.monotonic() + code["expires_in"]
    try:
        while time.monotonic() < deadline:
            time.sleep(interval)
            result = poll_device_token(base_url, code["device_code"])
            error = result.get("error")
            if error is None:
                _write_settings({TOKEN_ENV: result["token"]})
                print(f"logged in — token saved to {config_path()} (mode 0600)")
                return EXIT_OK
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                # RFC 8628 §3.5: back off rather than keep polling at the same cadence — the
                # server is telling us it's too fast.
                interval += 5
                continue
            if error == "access_denied":
                raise AccessDenied("login was denied")
            if error == "expired_token":
                raise ExpiredLogin(
                    "the login code expired before it was approved; run `kaya auth login` again"
                )
            raise KayaError(f"unexpected device-flow response: {error!r}")
    except KeyboardInterrupt:
        raise KayaError("login cancelled") from None

    raise ExpiredLogin("login timed out waiting for approval; run `kaya auth login` again")
