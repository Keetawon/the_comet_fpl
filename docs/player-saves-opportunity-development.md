# OOS shot-opportunity GK saves: retained development result

**SUPPORTED**, retrospective development only. The single
`retrospective_oos_shot_opportunity_gk_saves_v1` run clears every preregistered
aggregate AND per-season gate. It is eligible for the development synthesis, not
production/default promotion. No retuning, second candidate run or Phase A refit.

## Provenance and comparator

Clean preregistration/evaluation HEAD:
`f0c52fe1e5546dd21e8f37b75bb8022c2d9c8bae`. Config SHA256:
`cf777d6b4dce3d5c43891ceefdda0b6f8936c8f177ffbbbc617b2bae20ffd900`.
Original research DB SHA remains
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Started2026-09-07T10:42:44.392636Z; finished10:42:55.586053Z. Result SHA:
`79e61b51951e04795c8acb34a3e17db6e1fa417ed3717f7014b40d71ecf39ed2`.
Before scoring:38focused tests and the broader847-test relevant gate passed.

The exact current GK class and actual component-suite factory reproduce all2,313
conditional keeper PMFs with maximum difference0. The team reference reproduces
all3,800historical PMFs against retained/current prospective evidence, difference0.
The comparator is `gk_saves_poisson_from_team_conceded_v1`, not a research winner.

Both arms preserve current conditional-on-appearance, full-match Poisson0..9plus
10overflow. The candidate uses retained event-time OOS predicted opponent shots,
times league-pooled prior measured SOT/shot, times **unchanged incumbent save fraction**.
No individual keeper ability, new minutes model or actual target exposure enters.

## Result

| Metric | Current comparator | Candidate |
|---|---:|---:|
| Saves NLL |2.019983491|1.975058197|
| CRPS/RPS |1.065743307|1.020953989|
| Randomized PIT80 |.750540|.773022|
| MAE |1.535880170|1.492438356|
| Signed mean error |-.027310|+.102788|
| Predicted-rate SD |.997902|.671231|
| Within-GW Spearman |.233432|.258733|

NLL lift **2.224043%**; CRPS lift **4.202637%**. Paired candidate-minus-current
NLL-.044925294, GW-clustered SE.006905779; normal95% interval
[-.058460621,-.031389967] over114GWs, without serial-dependence adjustment.
Spread falls and ranking improves; this is not learned individual shot-stopping skill.
Mean bias increases despite better proper scores/PIT. No gate is changed.

| Season | Rows | Current NLL | Candidate NLL | Lift |
|---|---:|---:|---:|---:|
|2023-24|776|2.077006677|2.028130978|2.35318%|
|2024-25|770|2.021984666|1.981072574|2.02336%|
|2025-26|767|1.960282191|1.915324757|2.29342%|

Every season also passes non-regressing CRPS and PIT80absolute error<=.05.
EarlyGW1-6lift3.31652%, later2.01466%; home2.20653%, away2.24034%.
The17direct-price-proxy rows improve3.52593%;2,296non-proxy rows improve2.21192%.
Thus the conclusion is not created by proxy rows. The shared821-row missing-registry
limitation remains; minutes/price metadata are diagnostics, not saves-rate inputs.
On2,271measured target-SOT pairs, SOT-faced RMSE2.359046177→2.234315979(+5.28731%).
All2,313keeper rows remain in the nominated saves cohort.

## Missingness and independent verification

Seasonal measured SOT sides:754/760,740/760,744/760. **42NULLs remain NULL**;
no inferred zeros, averages or later revisions. There are no explicit zero SOT values
in these seasons. Selective provider omission may bias pooled precision upward;
a good predictive score does not resolve that limitation. Original later capture
timestamps remain unchanged, so evidence is retrospective only.

Metadata review reproduces189upstream training identities over3,800rows and whole-GW/
6-hour event guards without fitting. Independent arithmetic passes **175,108checks,
zero failures**:114fold hashes,2,313full PMFs, pooled sufficient statistics, original
capture/fixture/opponent identity, all slice scores/rankings/PIT values, gates and
clustered uncertainty. Audit SHA:
`2c18fddb6d49751231a905bbca28a1d489ea5b31f29b75ca0d14e9ffb4813527`.
An initial audit compared timestamps as strings (`T`versus space), creating2,313false
cutoff failures and two propagated gate failures. Its script/report remain preserved;
the additive corrected audit compares aware timestamps. No model or formal result
changed and no formal runner was repeated.

Complete external114fold payloads, shared claim/provenance and both audits:
`D:/Personal/fpl-operations/verification/gk-saves-opportunity-20260907T104500Z/`.
Committed result `results/player_saves_opportunity_development.json` and independent
audit `results/player_saves_opportunity_independent_audit.json` are exact copies.

Actual command from the V2 worktree:

```powershell
& 'D:\Personal\fpl-operations\.venv\Scripts\python.exe' -m fpl.validate.dev_player_saves_opportunity --db D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb --minutes-cache D:\Personal\fpl-operations\verification\current-minutes-proxy-cache-20260907T083100Z --output D:\Personal\fpl-operations\verification\gk-saves-opportunity-20260907T104500Z
```

Synthesis must apply retained per-fold parameters to **every GK roster row**,
never choose H using actual appearance or presence in its scored cohort. That
outcome-independent rule was fixed before scoring in `full-player-pmf-population-audit.md`.
The unchanged composer supplies one drawn-minutes gate. All defaults remain unchanged.
