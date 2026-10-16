# Backlog and project handoff

Reviewed October 15, 2026. Repository: https://github.com/KryptoShrimp/PokeRadar (remote configured in the Cloud checkout). Initial branch `work` was unborn and empty; no existing project files or local AGENTS/skills were found. Michael authorized publishing a feature branch and draft pull request on October 15, 2026. The initially empty remote requires an empty baseline commit for the PR target; implementation stays on the feature branch. No merge or deployment is authorized.

Planning reference: https://chatgpt.com/space/page_238f42b149808191b59c73ec247df363 (read during implementation). Its setup section predates the confirmed Cloud checkout; the user's explicit setup confirmation governs this build.

## Delivered first milestone

- [x] Exact product/source registry; MSRP unknown and live gate closed.
- [x] Timestamped append-only observations and decisions in SQLite.
- [x] Conservative synthetic eligibility rule and atomic dry-run outbox.
- [x] Restart-safe deduplication, stock transitions and CLI inspection.
- [x] Offline fixture demonstration and regression tests.
- [x] Setup, architecture and access limitations documented.

## Next gates, in order

1. **Review and publish:** publication of a feature branch and draft PR is authorized; review the proposed implementation before any future merge. No merge is authorized.
2. **Access:** establish current terms and an explicitly permitted source route. Do not probe excluded APIs or bypass queues, challenges or access controls. This milestone has no live implementation.
3. **Evidence:** verify exact product identity, current authoritative price/MSRP and dated price-rule provenance. The historical $161.64 chat target is not evidence.
4. **Existing alert reconciliation:** inspect the claimed hourly Delta Reign alert with the owner before proposing any scheduler or replacement. No automation was created here.
5. **Live adapter:** after access approval, capture permitted fixtures, model challenge detection and source-specific parsing, validate real observations separately from synthetic data. Keep production and fixture persistence/rules isolated.
6. **Delivery:** define a destination and obtain authorization before enabling external notifications. Add an idempotent delivery worker with retries separately from decision generation.
7. **Operational hardening:** migrations, backup/recovery, bounded inputs, logging/redaction, CI lint/type tooling, dynamic freshness views and policy versioning.
8. **Later product work:** dashboard; additional permitted retailers; Aurora/Denver vending-location registry with expiring sightings (not live inventory); resale economics from sourced completed sales; outcome tracking before prediction.

No spending, infrastructure deployment, purchases, checkout automation or new recurring tasks are authorized in this build. Fixture readiness does not imply live-source readiness or deployed operation.


## Local dashboard review — October 16, 2026

Implemented on local branch `feat/local-readonly-dashboard`, based on `06729b8ef03d86692f2384afbe6275821fd5d6a4`. Michael authorized publishing this milestone as a second draft PR on October 16, 2026, stacked against `feat/offline-inventory-core` (PR #1). It adds a loopback read-only dashboard, temporary synthetic demo, empty/error states and dynamic freshness. The dashboard remains fixture-only. No live access, schedules, alert changes, Actions or paid services were enabled.

Validation: 28 unit/integration tests pass, including all 17 core regression tests. Syntax compilation and whitespace checks pass. Chromium browser checks cover desktop (1440 px) and mobile (390 px), navigation, provenance disclosure and absence of page-level horizontal overflow. History tables intentionally scroll within their containers on narrow screens.

Pre-publication review: hardened malformed Unicode/deep JSON handling, explicit schema columns and duplicate Host rejection. Added checks for URI-special filenames, bounded reads and fixture URLs never becoming links. Dashboard-only tests: 11 passed; aggregate: 28 passed. Publication as a draft is authorized; no merge or deployment is authorized.
