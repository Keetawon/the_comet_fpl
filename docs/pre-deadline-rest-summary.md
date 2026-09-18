# Pre-deadline rest summary

A descriptive, development-only screen answering one question per player:

> **Did this player play midweek football, and how long is the gap to his club's next
> Premier League fixture?**

It changes no forecast, PMF, price, optimizer input, monitoring score or model default. It
is reporting built on captures that already run daily.

## Why it is buildable now

`AGENTS.md` records the measured constant that archive `rest_days` **cannot** see cup or
European congestion: the archive is Premier League only, with no competition field, so a
midweek cup tie is invisible and a congested player reads as fully rested. That constant is
unchanged and still governs every model input.

What changed is the evidence available *beside* the archive. `jobs.capture_sdp_workload`
retains whole lineup/event interpretations for all six supported competitions -- the
Premier League (8), FA Cup (1), League Cup (2), Champions League (5), Europa League (6) and
Conference League (1125) -- into `sdp_competitive_match_version`, and the owner's daily task
already runs it (`daily_pl_sdp --workload`). That makes *observed* congestion reportable
without inferring anything. It does not make rest a model feature: doing that would require
a separately named, pre-registered candidate with its own evaluation.

## Contract

| Piece | Location |
| --- | --- |
| Pure domain, no database, no network | `src/fpl/publish/rest_summary.py` |
| Thin read-only job | `src/fpl/jobs/rest_summary.py` |
| Published international windows | `config/international_breaks.yaml` |
| Tests | `tests/test_rest_summary.py`, `tests/test_rest_summary_job.py` |

```bash
python -m fpl.jobs.rest_summary --db D:/FPL/operational.duckdb --out D:/FPL/rest \
    --code-file my-squad.txt
```

The job connects read-only, writes no table, and emits an immutable
`rest-summary-<as_of>.json` next to a reviewable `.txt` block. Re-running to an existing
path is refused rather than overwritten. Without `--codes` / `--code-file` the population is
every selectable player (element types 1-4; assistant managers are not players and are
excluded); a squad file keeps the text block readable.

## The verdict answers exactly one question

`verdict` is about midweek football and nothing else. It is not an availability badge, not a
fitness estimate and not a recommendation. The existing reported availability overlay
(`status`, `chance_of_playing_next_round`, `news`) remains the separate, unchanged source for
injuries and doubts.

| Verdict | Meaning | What it takes to earn it |
| --- | --- | --- |
| `midweek_played` | At least one witnessed appearance in a Mon-Thu UTC fixture inside the window | One proved appearance |
| `full_rest` | No midweek appearance | A complete, error-free interpretation of that club's side in **every** midweek fixture it played in the window |
| `unknown` | Cannot be decided | Any midweek fixture whose evidence is unusable |

**A red flag is cheap; a green flag must be earned.** This follows the rule already frozen in
`docs/competitive-workload-mart.md`: *a complete valid roster can prove nonselection; an
absent endpoint or an unresolved required identity cannot prove DNP*. A club side whose
interpretation carries an error is unusable **in both directions** -- its absence does not
prove rest, and a row inside a contradictory interpretation does not prove an appearance.
Every downgrade carries its reason and the exact `provider_match_id` that caused it:

* `roster_not_proven:<match_id>` -- that side did not interpret cleanly;
* `participation_unknown:<match_id>` -- the player's own row is unresolved or errored;
* `duration_unknown:<match_id>` -- he appeared, but the duration is unavailable;
* `no_witnessed_appearance_in_window` -- nothing was witnessed at all, so no last match is shown;
* `no_next_fixture_listed` / `next_fixture_kickoff_unavailable` -- the gap has no second endpoint;
* `international_window_overlap_call_ups_not_captured` -- see below.

## Two limitations that must stay visible

1. **National-team call-ups are not captured anywhere in this repository.** When a published
   international window overlaps the gap, the row is flagged and the reason is attached, which
   *qualifies* a rest claim. It never establishes that a particular player travelled, and it
   never silently turns a proved absence of club football into fatigue. The windows are the
   Premier League's own published annotations, mirrored from the browser calendar's copy in
   `dashboard/src/data/internationalBreaks.ts`; `tests/test_rest_summary.py` pins the two
   copies to each other so they cannot drift.
2. **Durations are not FPL minutes.** The provider's figure is
   `nominal_period_clock_intervals_v1_not_fpl_minutes`. For a Premier League leg FPL's own
   recorded `minutes` remains the authority; the two are reported for different purposes and
   are never reconciled into one number here.

## Measures

* `rest_hours` -- exact kickoff-to-kickoff hours. Neither endpoint is a final whistle, so this
  is matchday spacing, not recovery time.
* `rest_days` -- whole UK calendar days between the two kickoff dates, so 13 September to
  20 September reads 7, matching how the all-competition calendar already counts listed gaps.
  The zone is explicit on purpose: DuckDB's `date_diff('day', ...)` counts calendar boundaries
  in the *session* timezone, and the same pair of kickoffs reads 2 under UTC and 1 under
  Asia/Bangkok.
* `midweek_appearances` / `midweek_nominal_minutes` -- witnessed load only; a null total means
  at least one appeared leg had no measurable duration, never zero.

`validate_rest_summary` re-reads a published document and refuses one that contradicts itself:
a verdict that disagrees with its own midweek count, a rest reported without both endpoints, a
negative gap, an unstated international overlap, an appearance postdating the cutoff, or counts
that do not reconcile to the rows.

## What this is not

Not a fatigue model, not a rotation prediction, not permission to feed rest into minutes, xP,
the composer or the optimizer, and not a substitute for the availability overlay. The
all-competition calendar's own wording still holds for schedule spacing: missing cup rounds,
national-team appearances, training and travel are not established by a gap between fixtures.
