# Descriptive team goal-pattern columns

The Attacking and All metrics tables now include Open-play goals and Set-piece
goals. They use the existing per-match/total selector, filters, match logs and
CSV export. No model, selector, scoring configuration or forecast is changed.

Open-play goals reads the exact retained `goalsOpenplay` field through the existing
nonnegative-integer validator. The display-only catalog leaves independent
semantic reconciliation unverified. Missing, invalid or conflicting evidence is
unavailable; a provider zero is zero. The frozen model/ingestion metric dictionary
is unchanged and this field is not made feature-readable.

The retained 2026/27 source snapshot contains 39 completed fixtures across GW1–GW4
(78 team-match sides), with `goalsOpenplay` explicitly present on all 78 sides.
Their sum is 78 goals. Total provider goals reconcile to the official fixture
scores on all 78 sides (109 goals); this does not independently establish the
origin of every goal. Historical field coverage is lower and missing historical
values are not filled with zero.

Set-piece goals stays NULL: there is no verified total field in the retained
match-stat payloads. Retained events distinguish ordinary goals, penalties and
own goals but do not provide a complete goal-pattern classification. The
description appears in the column/cell tooltip and the CSV provenance column.
The export validator rejects a fabricated numeric set-piece total.

[Opta's event definitions](https://www.statsperform.com/opta-event-definitions/)
distinguish regular play, fast breaks, corners, free kicks, throw-ins and penalties.
The narrow `attSetpiece` category describes attempts, not total set-piece goals.
`attPenGoal` and `attFreekickGoal` exist but do not cover all set-piece origins.
Consequently neither total goals minus open-play goals nor penalty plus free-kick
goals is published as a complete set-piece total. Own-goal attribution also needs
an explicit rule before any exhaustive decomposition.

The new descriptive sidecar is built from the retained read-only source database
at the existing dashboard cutoff, 2026-09-14T03:47:39.528929+00:00. This is a new
presentation export, not a new provider capture. Original source versions,
knowledge timestamps, provider core-valid counts and prediction vintages stay
unchanged. All old fields are reconciled against the prior sidecar before installing
the new export into the existing local preview.

Verification: 78 focused Python source/export tests passed; the separate 85-test
selector/dashboard-validation/scouting regression group passed. The latter first
encountered a Windows temporary-directory ACL error and then completed with a new
explicit workspace test directory; no existing temporary files were removed.
All 64 focused frontend tests passed after correcting the new test's element
selector and quoted-CSV expectations. Global Ruff and strict mypy (230 source
files), changed Python formatting, TypeScript/Vite build and frontend lint passed.
Existing nine Fast Refresh warnings and bundle-size warning remain.

All 404 protected model/config/research/forecast fingerprints matched. Removing
only the two new fields/catalog entries from the export reproduces the previous
logical sidecar exactly, including every source timestamp, display correction,
player row and health count. Both new export runs are byte-identical:
`083fa5251fa041f9a6d296cd461e18b02b519145cc5bf03d2254fbefc3cf68c5`.
Current provider-valid count remains 35/39 fixtures; owner display confirmation
remains separate. New export creation: 2026-09-14T15:56:13.598267+00:00.

The local preview at `http://127.0.0.1:4173/#team-stat-sdp` serves the new sidecar
and built assets byte-for-byte. Browser skill discovery returned
`No browser is available` and an empty browser list, so no visual pass or new
screenshot is claimed. This is a local preview, not a production deployment.
Verification and the preserved prior sidecar live in the ignored
`data/artifacts/sdp-goal-patterns-20260914/` directory on this worktree.
