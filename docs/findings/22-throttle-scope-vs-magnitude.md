# Finding 22 — a 20/min throttle producing a 46-second reset

A captured CourtListener 429 in which the scope string and the reset magnitude
contradict each other inside one response body. Tracked here because the
`_reset_seconds` rewrite is not happening in the session that measured this, and
without a file the case for it lives only in a chat transcript.

Every earlier version of this argument was reconstruction: abort geometry inferred
across block-buffered logs, where each line carried the process-exit timestamp and
the 429 body was discarded unread. This one is the artifact itself.

Measured **2026-08-10 01:40Z** against production CourtListener, on the same token
`collectors/litigation.py` loads.

## The artifact

```
HTTP/1.1 429 Too Many Requests
retry-after: 46

{"detail":"Request was throttled. Rate limit exceeded: 20/min. Expected available in 46 seconds."}
```

The body names its scope outright: **`20/min`**. A per-minute throttle. The reset it
reports is **46 seconds**.

`common._get` classifies on magnitude, not scope. `MAX_RETRY_AFTER = 30`, and a reset
above it is read as a spent daily budget — hopeless, abort the run. So this response,
which says *per-minute* in plain text, classifies as a daily cap. Magnitude and scope
disagree inside a single artifact, and the code reads the wrong one.

The 46 is not anomalous, it is the arithmetic of a rolling window. Twenty requests
spanning 14.5s means the oldest ages out at t=60, so 60 − 14.5 ≈ 45.5. **The tighter
the burst, the larger the reset a per-minute throttle reports** — the ceiling is 60s,
which is double `MAX_RETRY_AFTER`. The misclassification is not an edge case of the
window; it is the normal behaviour of a full one.

### Why it does not bite today

`PAGE_THROTTLE = 3.0` plus ~0.7s per-request overhead puts litigation at ~3.7s
spacing. Twenty requests then span ~70s, longer than the window, so the history never
reaches 20 and no 429 is issued at all. This is a **latent** misclassification, not an
active one. It becomes active the moment anything bursts faster than ~3s spacing —
a lowered `PAGE_THROTTLE`, a retry loop, a second client on the same token, or a
future endpoint that costs more than one request per docket.

## The headers, in full

```
Content-Type, Content-Length, Connection, Date, set-cookie, server, retry-after,
vary, allow, content-security-policy, x-frame-options, permissions-policy,
strict-transport-security, x-content-type-options, referrer-policy,
cross-origin-opener-policy, X-Cache, Via, X-Amz-Cf-Pop, X-Amz-Cf-Id
```

Twenty headers, and **no `X-RateLimit-*` header of any kind** — no limit, no
remaining, no reset. `retry-after` carries a delay with no scope attached.

This confirms empirically the invariant already committed to `docs/status.md`, which
was written from inference: the body is the only source of scope. Nothing in the
header set distinguishes a per-minute throttle from a daily one. Any classifier that
does not read the body is guessing, and `retry-after` is precisely the field that
makes the guess look informed.

## Method, in enough detail to repeat

The first-429 index **is** the limit, exactly and without estimation. DRF's
`SimpleRateThrottle` allows a request when its history holds fewer than
`num_requests` entries, so the first rejection is request number `num_requests + 1`.
Index 21 means 20/min. No curve fitting, no averaging.

- Endpoint `GET /api/rest/v4/courts/?page_size=1` — cheap, stable, one row.
- Token loaded through `config.load_env()` → `config.require_env(lit["api"]["key_env"])`,
  sent as `Authorization: Token <token>` with the project `USER_AGENT`. Identical path
  to `collectors/litigation.py`, so the probe measures what the collector would get.
- Burst with no spacing, so every request lands inside one 60s window.
- Ceiling 22, chosen so that a 20/min result is distinguishable from the ceiling
  itself. A ceiling of 12 could not have told 20/min from "no 429 observed".
- Stop at the first 429. No retry, no continue.
- **Timeouts recorded, never skipped.** A request the server received consumes
  allowance whether or not the response was read, so dropping its index would shift
  every later index by one and destroy the measurement.
- Drain the window between attempts. A second burst inside 60s of the first inherits
  its history and reports a falsely low limit.

## The decisive burst

| idx | timestamp (UTC) | status | elapsed |
| --- | --- | --- | --- |
| 1 | 01:40:16.821 | 200 | 0.000s |
| 2 | 01:40:18.561 | 200 | 1.734s |
| 3 | 01:40:19.063 | 200 | 2.234s |
| 4 | 01:40:21.462 | 200 | 4.640s |
| 5 | 01:40:21.987 | 200 | 5.156s |
| 6 | 01:40:23.627 | 200 | 6.796s |
| 7 | 01:40:24.095 | 200 | 7.265s |
| 8 | 01:40:24.592 | 200 | 7.765s |
| 9 | 01:40:25.061 | 200 | 8.234s |
| 10 | 01:40:25.537 | 200 | 8.703s |
| 11 | 01:40:26.052 | 200 | 9.218s |
| 12 | 01:40:26.659 | 200 | 9.828s |
| 13 | 01:40:27.250 | 200 | 10.421s |
| 14 | 01:40:27.746 | 200 | 10.921s |
| 15 | 01:40:28.192 | 200 | 11.359s |
| 16 | 01:40:28.832 | 200 | 12.000s |
| 17 | 01:40:29.294 | 200 | 12.468s |
| 18 | 01:40:29.753 | 200 | 12.921s |
| 19 | 01:40:30.216 | 200 | 13.390s |
| 20 | 01:40:30.773 | 200 | 13.953s |
| **21** | **01:40:31.305** | **429** | **14.484s** |

Twenty 200s in 14.48s, then the rejection. `retry-after: 46` corroborates the reading
independently of the index: 60 − 14.5 ≈ 45.5, which is the age of the oldest request
still in the window. Two derivations, one answer.

Mean spacing across the unthrottled burst is ~0.72s, which is the network round trip
alone. That is the empirical basis for the ~0.7s per-request overhead term in
`PAGE_THROTTLE`'s comment — measured without Turso in the path, so the collector's
real overhead is that or higher.

## The first attempt, and what it settled on its own

An earlier burst reached **18 consecutive 200s** before dying on a 30s read timeout at
index 19. CourtListener was slow mid-burst — a 3.7s stall at index 14 and a 16.4s
stall at index 17 — and the failure was transport, not throttle.

That attempt is not wasted. **It falsified 5/min by itself**: index 6 returned 200. No
result from the second burst was needed to rule out the tier the four aborting runs
had been behaving as.

## The panel leads enforcement

The Access Level panel (Developer Tools → API Usage) read **20/min** while the API was
still enforcing **5/min**. The 00:47:17Z collector run aborted at request ~6 with a
~42s reset — the 5/min signature — and the panel had already been read as 20/min
before that run's abort was inspected. By 01:36:59Z the API answered 20/min.

So the tier boundary brackets to **00:47:17Z – 01:36:59Z on 2026-08-10**, and the
panel led enforcement by up to an hour.

The consequence is a distinction worth keeping:

- **The panel reads entitlement.** What the account is provisioned for.
- **The probe reads enforcement.** What the API will actually do to the next request.

They are not the same instrument and they disagreed for a measurable interval. Anyone
reading the panel and concluding the collector is already fine would have been wrong
for up to an hour. When the six-month EDU expiry comes round, expect the same lag in
the other direction, and trust the probe over the panel for anything the collector's
behaviour depends on.

## The detector is untested, and normal operation will not test it

`common._log_429` is the artifact that makes this finding reproducible next time, and
its correctness currently rests on **the probe reproducing the same body shape
out-of-band, and on nothing else.** It has never fired in the collector.

Nor should it, if the pacing is right. At ~3.7s spacing the 60s window never fills, so
a healthy run issues zero 429s and the detector stays cold. **A clean run is therefore
not a passing test of it** — the two outcomes are indistinguishable from the log.

Its first genuine exercise is whatever run eventually trips a throttle. The most
probable candidate is the EDU membership expiring roughly six months out and dropping
the account back to 5/min: precisely the moment the detector matters most, and
precisely the moment nobody is watching for it. A detector whose first real invocation
is the incident it was built for is a detector nobody has debugged.

The consequence: this wants a test that fires `_log_429` deliberately — a synthetic 429
response through the classification path, asserting the body reaches stderr and the
Authorization header is redacted in both the header map and the body. Left as an open
unit; not written in the pass that measured this.

## What this does not establish

Nothing here proves the GitHub Actions runner holds this token. Secrets are
write-only; no local read can confirm the value. The only available evidence is the
workflow's own behaviour — a run polling the full docket list is what demonstrates the
runner's token carries the same membership.
