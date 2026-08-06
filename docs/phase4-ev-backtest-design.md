# Phase 4 Stage D — Prospective EV Walk-forward Backtest Design

**Status: pre-registration, development-only.** The Prospective Expected Value (EV) Walk-forward
Backtest is pre-registered under `config/phase4_ev_backtest_evaluation.yaml` (contract v1.0).

This backtest evaluates how accurately the **current prospective point-in-time forecasting
architecture** ranks players and models points distributions over the final ten observed gameweeks
(GW29–38) of the 2025–26 season.

## Derived Horizon Anchors

- **Season**: 2025–26
- **Gameweeks**: GW29–38 (10 observed gameweeks)
- **Derived Fixtures**: 99
- **Derived Target Rows**: 8,224 player-fixture rows

## Model Architectures

1. **Primary Architecture** (`prospective_v3_coupled_seasonal_bonus`):
   - Stage A: `trailing_goals_attack_defence` baseline
   - Stage B: `Minutes V3` (`concentration_adaptive_shrinkage_player_minutes_v3`)
   - Stage C Attacking: Goals V3 (`minutes_gated_coupled_team_share_attacking_goals_v3`) + Coupled Assists
   - Appearance: `seasonal` (trailing-5 `minutes IS NOT NULL` with $n \ge 3$ threshold; prior-season blend weight = 0.0)
   - Rules: `scoring_2026_27`
   - Bonus: Joint per-fixture BPS Monte Carlo simulation (2,000 draws, seed 202627)
   - Support: `0..34` per fixture (`DEFAULT_MAX_POINTS_FULL`)
2. **Diagnostic Comparator** (`prospective_v1_independent_seasonal_bonus`):
   - Attacking V1 (`xg_informed_trailing_player_goals_v1`) + Assists V1 (`xa_informed_trailing_player_assists_v1`)
   - Co-scored on 100% identical target fixture population; NOT a promotion gate.

## Target Leakage & BPS ICT Parity

- Trailing ICT (`influence` and `creativity`) is extracted strictly before `as_of` (`kickoff_time < as_of`)
  over rows where `minutes IS NOT NULL AND influence IS NOT NULL AND creativity IS NOT NULL`
  (including 0-minute rows where ICT is measured), matching production `prospective_points_v1.py:trailing_ict`
  exactly.
- No `threat` and no per-minute conversion.
- Target-row outcomes and recorded points are NEVER read by prediction components.

## Forecast Grain & DGW PMF Convolution

- **Fixture Grain**: Proper scores (Log Score, CRPS, Randomized PIT-80) evaluated directly at `(season, code, fixture)` grain over 0..34 support.
- **Weekly DGW Convolution**: For Double Gameweeks, fixture PMFs are convolved without truncation over support `0 .. (34 * fixture_count_for_player_gw)`. Weekly EV is the exact sum of fixture EVs.
- **Cumulative Ranking**: Weekly player-GW rows are aggregated by player `code` across all 10 gameweeks for Spearman correlation evaluation.

## Known Composer Defect Disclaimer

The runner carries the known composer conditionality defect (Stage C V3 rates already include
$P(\text{play})$ and the composer gates events again through sampled minutes). This depresses EV
totals and distorts rank resolution between starters and cameos. The results serve as a development
diagnostic of the current prospective architecture and CANNOT authorize production deployment.
