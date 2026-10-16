# PokéRadar

Offline Pokémon TCG MSRP inventory-intelligence MVP. Python 3.12+ and standard-library SQLite; no packages, credentials, or paid services required.

**Fixture ready; live source disabled; nothing deployed.** All imports are synthetic fixtures, never verified retailer observations. Current MSRP and live availability are unknown. The historical chat target of $161.64 is not a verified price and is not used by the code.

## What you can do today

Run a local command-line demo that reads a sample inventory observation, saves its history, and previews one pretend alert. Run it again to see duplicate alerts suppressed. This is the tested foundation for a future monitor; a local read-only dashboard is available, but there is no live inventory feed. Start with the demo below, then inspect `pokeradar/core.py` for safety rules, `pokeradar/store.py` for history and deduplication, and `tests/test_pipeline.py` for the tested scenarios.

## Mac quick start (dashboard review branch)

Requires Git and **Python 3.12 or newer**. Check with `python3 --version`; no Python packages are needed. In Terminal, for a new checkout:

```sh
git clone --branch feat/local-readonly-dashboard https://github.com/KryptoShrimp/PokeRadar.git
cd PokeRadar
python3 -m pokeradar dashboard --demo
```

Then open **http://127.0.0.1:8765** in Safari or Chrome. Keep Terminal running; press Ctrl+C to stop. For an existing clean checkout, run `git fetch origin` and `git switch feat/local-readonly-dashboard` first. The GitHub PR contains reviewable code; it does not host a running dashboard.

## Local read-only dashboard

Launch a labeled synthetic demo with one command, then open **http://127.0.0.1:8765**:

```sh
python -m pokeradar dashboard --demo
```

To inspect an existing local database instead:

```sh
python -m pokeradar --db demo.sqlite3 dashboard
```

The dashboard binds only to `127.0.0.1`. Use `--port 8766` to change the port; Ctrl+C stops it. It reads the newest 100 records per history table in a consistent read-only SQLite snapshot. A missing database shows empty states without creating a file. An unreadable/incompatible database shows a warning. Invalid record payloads show unknown values rather than inferred stock or prices.

The view shows the registered product, observation history, source fetch outcomes, price provenance, suppression reasons and dry-run alert history. Freshness is recalculated at page load; recorded stock status is historical, not current availability. Use **Refresh view** manually. There is no polling or scheduling. A stale observation cannot establish current source health, and the source outcome card explicitly describes fixture evidence.

`--demo` ignores the database path and generates disposable in-memory fixtures through the core pipeline, showing sold-out, in-stock, repeated stock suppression and blocked evidence with one dry-run event. Relative sample times are regenerated on each page load for demonstration; they are not a persistent or live feed. No files or existing alerts are changed. All sample prices are synthetic; verified MSRP stays unknown.

## Setup and checks

From the repository root:

```sh
python --version
python -m unittest discover -s tests -v
python -m compileall -q pokeradar tests
```

An optional virtual environment can be created with `python -m venv .venv`. No installation is required. There is no configured third-party linter or static type checker; compileall checks syntax, not static types.

## Run the offline demonstration

Use a fresh database path to start a new demonstration. Reuse it to verify restart deduplication. `--db` goes before the subcommand.

```sh
python -m pokeradar registry
python -m pokeradar --db demo.sqlite3 import fixtures/in_stock.json --demo-rule --now 2026-10-15T12:01:00Z
python -m pokeradar --db demo.sqlite3 import fixtures/in_stock.json --demo-rule --now 2026-10-15T12:01:00Z
python -m pokeradar --db demo.sqlite3 history
python -m pokeradar --db demo.sqlite3 decisions
python -m pokeradar --db demo.sqlite3 alerts
```

Expected: first import `dry_run_alert`, second `suppressed`, two append-only observations and decisions, **one** outbox event. The outbox is a local preview only; it has no delivery worker. Every event says `SYNTHETIC — NOT A PURCHASE SIGNAL`, includes the timestamp, price, source SKU and product link.

`--demo-rule` explicitly selects a synthetic USD 100.00 ceiling, not actual MSRP. Without it, imports are stored but alerts are suppressed because the target-price rule is unverified. `--now` is an offline replay clock; omitting it uses current UTC time, so the historical sample becomes stale. Preview commands support `--limit 1..1000` (default 20), newest first. History displays status at ingestion, not a dynamically refreshed live status.

```sh
python -m pokeradar --db demo.sqlite3 import fixtures/in_stock.json
python -m pokeradar live
```

The live command exits 2 with the access-policy explanation and makes no network request. There is no switch that enables live access. `python -m pokeradar --help` lists all commands. Malformed readable fixtures are stored with `error`; file/database/CLI failures exit 2.

## Registered target

- Source: Pokémon Center US; SKU `10-10446-120`.
- Variant: Mega Evolution—Delta Reign booster display, **36 packs**.
- [Exact product](https://www.pokemoncenter.com/product/10-10446-120/pokemon-tcg-mega-evolution-delta-reign-booster-display-box-36-packs).
- Exact source ID, URL, SKU and pack count are required; currency must be USD and price a positive integer in cents.

The adapter consumes a normalized fixture contract, **not retailer HTML or an inferred API schema**. See `fixtures/in_stock.json`. Access outcomes must be `ok`, `blocked`, `rate_limited` or `error`; availability must be `in_stock`, `sold_out`, `preorder` or `unknown`. Only literal boolean `true` is accepted for `purchasable`. Timestamps must contain a timezone. Unknown structures, CAPTCHA HTML and parser errors cannot create alerts. A future permitted adapter must explicitly detect queues/challenges; this MVP makes no claim to parse Pokémon Center responses.

## Safety and scope

No live retailer requests, endpoint probing, scheduler, checkout, external notifications, deployments, purchases, or paid dependencies. Per the project brief, robots excludes stock/price/resource API paths and permission has not been established. This is a constraint supplied by the project, not a fresh terms audit. Do not infer permission from a product page being publicly visible.

The claimed existing hourly Delta Reign alert was not inspected, modified or duplicated. The separate TopCut `pokemon-tcg` repository is outside this project and was not modified. Local SQLite files are ignored by Git; preserve them to preserve deduplication history.

See [architecture](docs/architecture.md) and [backlog](docs/backlog.md).
