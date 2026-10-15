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
