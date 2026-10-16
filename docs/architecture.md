# Architecture

## Pipeline

`local JSON → FixtureAdapter → normalized observation → SQLite transaction → decision + optional dry-run outbox event`

- `pokeradar/core.py`: immutable product/source registry, adapter protocol, fail-closed live adapter, fixture normalization, freshness and price eligibility.
- `pokeradar/store.py`: local persistence, append-only audit tables and stock-episode state.
- `pokeradar/__main__.py`: JSON CLI for registry, import, history, decisions, alerts and disabled live access.

The empty repository had no inherited stack or instructions. Python and SQLite keep the first milestone reproducible without dependency downloads or hosted infrastructure. Registry definitions are version-controlled code, not an admin UI. The adapter contract deliberately accepts fixture text; a future live adapter needs an explicit access review and a redesigned retrieval boundary.

## Observation and decision semantics

Store both original raw input and normalized evidence with received/checked timestamps, identity match, price/currency, availability, fetch outcome, freshness, effective status and reason. Status is one of `in_stock`, `sold_out`, `preorder`, `unknown`, `blocked`, `rate_limited`, `stale`, `error`. Fetch failures retain their failure status even when old; availability and freshness remain independent fields. Invalid identity becomes unknown. Malformed JSON becomes error. Positive observations older than 15 minutes become stale; future timestamps become error. The 15-minute policy is a conservative local default, not a promise about source latency.

An alert requires matching identity, fresh in-stock state, positive purchasability, known USD price and the explicitly selected synthetic rule. Current real MSRP remains null. Fixtures cannot assert a verified production rule. Demo and unverified rules have separate state namespaces; there is no production rule or delivery path.

## Deduplication and persistence

SQLite `BEGIN IMMEDIATE` serializes writers. Observation, decision, outbox insertion and state advancement commit together. Failure rolls back all four. Unique outbox keys include product, versioned rule and episode. All audit tables reject update/delete through SQLite triggers (this is not protection against an administrator altering the schema).

The first eligible observation emits one dry-run event. Repeated in-stock observations remain suppressed even after process restart. Only a fresh matching sold-out observation after an alert rearms the episode. Unknown, blocked, errors, preorder, missing prices, stale evidence and wrong variants never rearm it. Older/equal timestamps cannot change state or emit alerts. A watermark advances on fresh matching observations, including access failures, so late-arriving older stock data cannot undo newer evidence. This intentionally may miss a genuine new episode if no trustworthy sold-out observation was seen; avoiding duplicate/unsafe signals takes priority.

Every import is retained, including duplicate raw data and malformed text. Deduplication applies to alert events, not the audit trail. Persist and back up the same SQLite file across runs; deleting it resets history and deduplication. There is no retention, database migration framework, multi-host coordination, or delivery retry system yet. Schema is initial v1 and requires future migration work before changing it.

History reports recorded status at import time. It is an audit view, not a current inventory view; a dashboard must compute aging at read time. `--now` intentionally allows deterministic offline replay and is never evidence of current availability. Files are trusted local inputs; import size limits/redaction are future hardening work.

## Verification boundaries

Tests cover normalization failure modes, price uncertainty, freshness edges, timestamp ordering, episode transitions, append-only enforcement, atomic rollback, actual CLI process restart and concurrent imports. No tests contact retailers. Passing these checks establishes fixture pipeline behavior only. Syntax compilation is not a lint/typecheck substitute; neither tool is configured in this dependency-free repository.


## Local dashboard milestone

`pokeradar/dashboard.py` serves server-rendered HTML using the Python standard library. It binds exclusively to loopback, validates the Host header, serves only GET `/`, and exposes no file browsing, SQL, write, or export routes. A restrictive content security policy disallows scripts, external resources and framing. Dynamic text is HTML-escaped, and the only product link comes from the fixed registry. No third-party browser assets are fetched.

Existing SQLite databases are opened with `mode=ro` and `query_only=ON`; the dashboard never calls the schema-initializing connector for on-disk data. Each request uses a consistent read transaction and closes the connection. Missing databases remain missing. Read failures and invalid JSON payloads degrade to warnings/unknown evidence. Views are bounded to 100 rows per table, newest insertion first (not necessarily newest evidence time); there is no pagination yet. A later arrival can contain older evidence, so the latest-record card is explicitly historical. The registry currently contains one product; multi-product monitoring remains future work.

Demo mode uses the real pipeline in an ephemeral in-memory SQLite database and regenerates relative fixture times per request. Normal mode uses the current clock only for derived freshness; stored statuses and decisions are not recomputed or mutated. The dashboard is a local development server, not a production hosting or authentication solution.
