# Dashboard release — 2026-09-21

Owner authorized merge and deployment before beginning a separate Team-model
experiment. The release starts at current main `ae18411` and applies the frontend
delta from `ec20bbf` to reviewed source branch `68cd2e8` only. The source branch and
all existing worktrees are preserved. Its unrelated retention, recovery and disabled
news backend changes are not included; newer main snapshots remain intact.

Public changes: canonical `#score-prediction` with the old `#gw-analysis` bookmark
alias, a five-column desktop fixture outlook, rounded goals with smaller original
estimates underneath, and demo source-link isolation in the shared News component.
The bilingual conference/roundup simulation remains DEV-only; invented stories are
excluded from the production JavaScript. No automatic news capture is activated,
and no unpublished source is represented as live news.

Validation: 762 frontend tests in 72 files passed in this isolated checkout.
Hosted TypeScript/Vite build passed with the existing public R2 pointer and Manager
ID endpoint; full Oxlint has zero errors and nine inherited Fast Refresh warnings.
Source branch browser verification covers desktop/mobile and bilingual preview
states. Final served-site verification is recorded on the release PR.

There are no changes under `src/`, `config/`, `results/`, `snapshots/`, `.github/`,
`AGENTS.md`, package manifests/locks or the immutable public data release pin.
Model/component content and frozen forecasts are unchanged. No inference,
optimizer, historical audit, paid news capture or R2 publication is run for this
release. The existing main-push GitHub Pages workflow deploys; the R2 pointer and
read-only Manager ID Worker settings remain unchanged.

The last release documented inherited Python-formatting failures on main; this
frontend release does not modify those files or waive gates. Report current CI
separately from the passing frontend/deployment checks.

Rollback: revert this release commit through a normal reviewed PR and allow the
existing Pages workflow to republish. Preserve the R2 pointer and immutable data
and forecast generations. No force push or data regeneration is required.
