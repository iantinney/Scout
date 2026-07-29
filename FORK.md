# Fork notes — riversnap

Fork of [kiryano/Scout](https://github.com/kiryano/Scout) (MIT). Upstream is a
lead-gen CLI for appointment setters; we use it as a **creator discovery and
contact-capture** tool feeding Pharos.

## Why we forked rather than depending on it

Two upstream behaviours are unacceptable in an unattended data pipeline. Both are
fixed here; everything else is upstream's and we want upstream's fixes.

### 1. Removed the update checker (`scout.py`)

Upstream polled `api.github.com/repos/kiryano/Scout/releases/latest` on every
start and called `sys.exit(1)` if the local version was behind. That is a remote
kill switch over our pipeline held by a third party. Removed entirely.

Pull upstream changes deliberately instead:

```bash
git fetch upstream && git merge upstream/main
python -m pytest tests/ -v     # MUST stay green — see below
```

### 2. Address guessing is off by default (`app/scrapers/enrichment.py`)

Upstream synthesises addresses that were never observed: it takes a name plus a
domain, emits `first.last@`, `first@`, `f.last@` …, and keeps any the mail server
doesn't reject on an SMTP `RCPT` probe. Those are inventions, not contacts.

This matters because we send real mail. Mailing invented addresses spikes hard
bounces and burns sender reputation — and for riversnap that reputation is shared
with the transactional mail live controllers depend on. The SMTP probe also
proves less than it appears: catch-all domains accept everything, and upstream's
own code detects that case and proceeds anyway.

Only **observed** addresses — published in a bio, on a site, or behind a bio link
(`OBSERVED_SOURCES`) — are treated as contactable. Three upstream paths are gated
behind `SCOUT_ALLOW_GUESSED_EMAILS` (default off):

| Upstream path | `email_source` | Status |
|---|---|---|
| `_predict_email_from_pattern` | `pattern` | gated off |
| `_generate_email_candidates` + SMTP probe | `smtp_guess` | gated off |
| `possible_emails` export column | — | gated off |

Plus a backstop in `enrich_lead` that strips any address whose source is not in
`OBSERVED_SOURCES`, so a future upstream merge that adds a fourth guessing path
still cannot leak one.

Set `SCOUT_ALLOW_GUESSED_EMAILS=true` only for research/enumeration where nothing
will be mailed.

> Note: SMTP verification of *observed* addresses is still present upstream and
> still runs. It is a **signal, not a gate** — Pharos's binding rule is that the
> send gate uses a commercial verifier, never a homemade SMTP check.

## Tests

Upstream ships none. `tests/test_no_guessed_emails.py` pins the two properties
above. Run it after every upstream merge — if it fails, upstream reintroduced a
guessing path or the kill switch.

## What we actually use it for

- `app/scrapers/tiktok.py` — unauthenticated TikTok profile parse off
  `__UNIVERSAL_DATA_FOR_REHYDRATION__`. Returns bio, follower/like counts, and any
  bio email. Verified working from the VM with no key and no proxy.
  Pharos's own `branches/scrapecreators/src/client.ts` is still a stub that
  throws, so this is currently our only working live TikTok enrichment path.
- `app/scrapers/linktree.py` — Linktree / Stan / Bio.link / Linkr expansion.
  Pharos has no equivalent; creator contact details often live one hop behind the
  bio link.
- `app/scrapers/instagram.py`, `youtube.py` — secondary.

## Upstream limitations that still apply

TikTok may serve CAPTCHAs by region/IP; Instagram may need retries; free proxies
are unreliable. Nothing here changes that — budget for retry and partial yield.
