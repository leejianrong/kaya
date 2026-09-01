<!--
title: "One account, no logins: how kaya borrows its identity from pandan"
description: kaya and pandan are two separately deployable products that share one account and one set of tokens. The mechanism is smaller than you'd expect, and the interesting part is what happened after it shipped, not the design itself.
slug: one-account-no-logins
author: Jian
date: 2026-08-18
status: Draft
tags: [auth, architecture, fastapi, distributed-systems, python, adr]
-->

---

# One account, no logins: how kaya borrows its identity from pandan

kaya and pandan are two separate products. Pandan is the kanban board, kaya is the
notes app, and they're built, tested and deployed independently of each other. But
they're meant to feel like one suite, and the first place that promise gets tested is
the most basic one: does an agent working across both need two accounts and two
tokens, or one?

The product answer was easy. One account, one set of tokens, so an agent can update a
card's spec note with the same credential it uses to move the card. The hard part was
never the "what", it was picking a mechanism that could deliver that without turning
two independently releasable apps into one app wearing two names.

## Cheaper isn't the same question as reversible

Three ways to get one account across two apps got weighed, and it's worth being
honest that the one we picked wasn't the cheapest to build or the fastest at runtime.

The cheapest option was a shared `AUTH_SECRET` and a shared database: kaya computes
the same HMAC pandan does and reads pandan's `personal_access_token` table directly.
One indexed lookup, no network hop, instant revocation. It's also the option that's
hardest to undo, because the moment kaya reads pandan's tables, pandan's auth schema
is part of kaya's contract. Rotating `AUTH_SECRET` becomes a coordinated two-app
outage instead of an internal change, and two independent Alembic histories now have
to coexist on one database without either one's autogenerate trying to drop the
other's tables. Exiting that design means unpicking shared tables first, which is
exactly the kind of thing nobody gets around to.

The other easy option was kaya standing on its own: its own GitHub OAuth app, its own
users, its own PATs. That's the option that gives up the actual point. Two logins and
two tokens is precisely the seam the whole suite exists to hide, and it drags in a
second async engine and a second OAuth app per environment along with it.

What we actually built is the third option: **pandan is the identity provider, and
kaya resolves a caller by asking it.** Slower per request than the shared-secret
version (an HTTP hop on a cache miss instead of one lookup), and more work upfront
than standing kaya up alone. But it's the one where kaya can be pulled out or pandan
can be replaced later without either app dragging the other down with it, which
matters more for two things meant to stay independently deployable.

## The resolver, in five steps

Pandan grew exactly one thing for this: `GET /api/v1/me`, which answers "which pandan
user is this credential?" and nothing else.

```python
# pandan/backend/app/routers/me.py
@router.get("", response_model=PrincipalRead)
def read_me(user: User = Depends(require_user)) -> User:
    """Return the authenticated principal's id + email (401 if there isn't one)."""
    return user
```

That's the whole endpoint. It reuses pandan's existing principal resolver unchanged,
touches no new schema, and adds no secret. Pandan doesn't gain any knowledge that
kaya exists. It just gained an answer to a question nothing had asked it before,
because until this endpoint existed there was no way for a PAT holder to ask who it
was: fastapi-users' own `/users/me` lives on the cookie-only path and won't take a
bearer token at all.

On kaya's side, every request runs through the same five steps, unchanged from the
original design:

```python
# kaya/backend/app/auth/resolver.py
def resolve(self, bearer: str) -> Principal:
    hit, cached = self._cache.lookup(bearer)
    if hit:
        if cached is None:
            raise TokenRejected
        return cached

    principal = self._single_flight.do(digest(bearer), lambda: self._introspect(bearer))

    if principal is None:
        raise TokenRejected
    return principal
```

Take the bearer as it comes and never inspect its prefix. Hash it and check a TTL
cache. On a miss, call pandan's `/me` with the bearer forwarded byte for byte. On
success, make sure a local `user` mirror row exists, keyed on pandan's UUID, created
the first time it's seen. Kaya mints nothing of its own: no token table, no `Tokens`
page, no `kaya_pat_` prefix. One mint point is what "one set of PATs" actually means
in code.

## The prefix trap kaya sidesteps by design

Pandan had already learned something the hard way that shaped this. When pandan
rebranded, its token prefix changed from `kanban_pat_` to `pandan_pat_`, and an
earlier draft of that decision claimed the prefix was "only used at mint time", with
no `startswith` guard anywhere in verification. That claim turned out to be false:
there's a guard at `authz.py`, added as a fast-path load-shedding check so a stray
`Authorization` header never triggers a database round trip. A bare prefix flip would
have 401'd every already-issued token, which is exactly the forced rotation the
rename was trying to avoid. The fix was an accepted-prefix tuple, and the lesson
written down afterwards was blunt: an ADR asserting a property of the code is a claim
to check, not a fact.

Kaya doesn't inherit that trap because it doesn't inherit the mechanism. There's no
prefix logic anywhere in kaya's auth path, so there's no guard to get subtly wrong.
Load-shedding against a stray header is a plain negative cache instead: a rejected
token gets cached too, briefly, so pandan gets asked once for a garbage string and
not once per request.

The cache itself only ever holds a digest, never a raw token:

```python
# kaya/backend/app/auth/cache.py
def digest(token: str) -> str:
    """The cache key for a token, and the only place a raw token is read in this module."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
```

A heap dump or a stray log line shouldn't be able to hand someone a live credential,
so nothing that lives longer than one request ever holds the raw value.

## A wrong answer is worse than no answer

The one rule that shows up everywhere in this design is that an outage must never
look like a bad credential. If pandan can't be reached on a cache miss, kaya answers
`503`, never `401`:

```python
# kaya/backend/app/auth/upstream.py
except httpx.HTTPError as exc:
    raise UpstreamUnavailable(f"{self._url} is unreachable") from exc
```

```python
# kaya/backend/app/auth/resolver.py
except UpstreamUnavailable as exc:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=error_body(
            "upstream_unavailable",
            f"kaya could not reach pandan to resolve this token: {exc}",
            upstream="pandan",
        ),
        headers={"Retry-After": "5"},
    ) from exc
```

The reasoning is that a `401` tells a client its credential is bad when the credential
is fine, and sends an agent into a token-rotation loop over what's actually somebody
else's outage. Pandan, for its part, gives kaya no way to tell a malformed token from
a revoked one; both come back as the identical `401`. Guessing which is which would be
a diagnosis dressed up as a guess, so kaya doesn't try. One code, `invalid_token`, for
both.

## What the design cost, and where it got measured

The consequence we accepted going in was that revocation lags by the cache TTL, and
that kaya has a runtime dependency on pandan, but only for **cold** authentication.
Once a token's cached, pandan can go down and an active agent session keeps working.

That cost got measured rather than left as a comfortable abstraction. A cold pandan
(the kind that's scaled to zero and has to wake up) took eleven to twenty-three
seconds to answer, against a single ten-second deadline kaya had set for the whole
call. Kaya wasn't waiting out the wake-up, it was 503ing on a token that would have
worked fine two seconds later.

The fix split one deadline into two, because "pandan is down" and "pandan is asleep"
are different failures that show up in different phases of the same request:

```python
# kaya/backend/app/auth/upstream.py
def split_timeout(*, connect: float, read: float) -> httpx.Timeout:
    return httpx.Timeout(connect=connect, read=read, write=connect, pool=connect)
```

Down shows up in the connect phase (nothing answers, wants a short deadline so a
`503` comes back promptly). Asleep shows up entirely in the read phase: Fly's edge
proxy finishes the TCP and TLS handshake on its own while the actual app machine
boots behind it, so the connection succeeds in milliseconds and then nothing comes
back for twenty seconds. One number can't be right for both, so now there are two: a
short connect budget and a longer read budget.

That alone introduces a second problem, though. Kaya's routes are synchronous, so a
widened read budget means a thread can sit blocked on pandan for up to thirty
seconds. If forty agents all show up with a fresh token at once (which is kaya's
normal opening move, one agent starting a session), that's forty threads held, and
Starlette only has forty to give out. Every other request behind them, including a
note **save** that needs nothing at all from pandan, waits behind an auth call that
has nothing to do with it.

The fix is to make sure pandan only gets asked once no matter how many callers are
waiting on the same token:

```python
# kaya/backend/app/auth/single_flight.py
def do[T](self, key: str, work: Callable[[], T]) -> T:
    with self._lock:
        existing = self._in_flight.get(key)
        if existing is not None:
            call, leading = existing, False
        else:
            call, leading = _Call(), True
            self._in_flight[key] = call

    if not leading:
        call.done.wait()
        if call.error is not None:
            raise call.error
        return call.result
    ...
```

One caller becomes the leader and actually talks to pandan; everyone else waits on an
event and gets the leader's result, success or failure, when it settles. That last
part matters more than it looks: if a waiter got handed `None` instead of the
leader's real exception, an outage would read as thirty-nine callers getting told
their perfectly good tokens were invalid, which is the exact failure this whole
design exists to prevent, just arriving one layer further in.

## The bug that crossed a package boundary

There's a second, quieter version of the same mistake, and it's the best evidence
that this design held up under pressure rather than just looking tidy on paper.

Widening kaya's own deadline changed what anyone *calling* kaya has to be willing to
wait for. `kaya-client`, the shared client library other tools use to talk to kaya,
had its own thirty-second deadline, set against a measured cold-start time of 21.8
seconds. That was correct when it was written. Then the backend's timeout budget got
split and its worst case rose to thirty-five seconds, and nothing connected those two
numbers, because they live in separate packages that don't import each other on
purpose (the client can't depend on the backend, and the backend importing the client
just to read one float would be worse). The result: a client that gave up on a
request the server was about to answer successfully, and reported a transport error
on a token that was never actually invalid.

Nothing had failed yet when this was caught. The fix isn't a runtime check, it's a
test that reads the client's source as text and compares the number in it against the
backend's configured budget:

```python
# kaya/backend/tests/unit/test_client_deadline_outlasts_auth.py
def test_the_client_outlasts_the_worst_case_authentication() -> None:
    connect, read = _auth_budget()
    client_deadline = _client_read_deadline()
    required = connect + read + HANDLING_MARGIN_SECONDS

    assert client_deadline >= required, (
        f"kaya's worst-case authentication is now {connect:g}s to reach pandan plus "
        f"{read:g}s to wait for it = {connect + read:g}s, and kaya-client's "
        f"{client_deadline:g}s ..."
    )
```

It parses `kaya-client`'s source with Python's own `ast` module rather than importing
it, specifically so the test can't accidentally start depending on the thing it's
checking. Whichever side changes next, raising the backend's timeout budget or
lowering the client's, this is the test that goes red first, with the actual numbers
in the failure message rather than a vague "something's wrong with auth".

## What a third sibling would need

Two things made all of this recoverable rather than merely functional. The dependency
arrow only ever points one way (kaya asks pandan, never the other way round), and
every real cost that showed up got measured instead of argued about. Pandan doesn't
know kaya exists, and if kaya disappeared tomorrow pandan wouldn't notice.

That's also the part worth keeping if a third app joins this suite later. It doesn't
need its own login either, it needs the same one endpoint kaya already leans on, the
same resolver shape, and the same rule that a wrong answer about identity is worse
than no answer at all. The mechanism generalises; what it cost to get right is the
part that's easy to skip and expensive to skip.
