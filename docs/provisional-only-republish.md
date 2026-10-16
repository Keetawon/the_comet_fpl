# Provisional-only republish

A cloud path that puts completed-match statistics on the public site without the owner's
desktop, by restating **only** the provisional preview of the generation already being
served.

## The gap it closes, measured

The public site reads one R2 pointer, `current.json`, which names an immutable generation.
That pointer moves only when the full refresh runs on the owner's machine, because every
read model in a generation is rebuilt from the operational database -- forecasts, ledger
vintages and optimizer plans included, none of which exists anywhere else.

On 2026-10-10 that refresh ran 10:46-11:03Z and the next one was on 2026-10-16 at 02:08Z.
GW6's first kickoff was 11:30Z on 2026-10-10, **27 minutes after the refresh finished**, so
for almost six days the published generation carried no GW6 result at all: the matches were
played, the capture workflows retained them, and the site could not show them.

This job closes that window and nothing else.

## What may move, and why that is three files rather than two

| File | Why |
| --- | --- |
| `player_provisional_actuals.json` | the player preview, rebuilt from the capture |
| `team_provisional_actuals.json` | the reciprocal club preview, rebuilt from the capture |
| `fixture_matrix.json` | its `teams[].form` summaries are owned by the published provisional rows |

The third is not a choice. `docs/current-team-form-repair-2026-09-15.md` made team form a
function of the published finalized and provisional ended-match records, and
`check_observed_freshness` refuses a package whose forms disagree with its own rows, so the
forms are recomputed by `refresh_team_forms` -- the same shared function the full export
calls, not a second implementation. `manifest.json` follows, because it hashes the others.

Every other published file is carried forward **byte for byte**, and `restate_generation`
re-reads the staged generation afterwards and refuses it if that is not what happened.

## Why no forecast can move here

Not by promise: by construction. The provisional facts are already forbidden from entering
the prediction ledgers, the prediction-versus-actual read models, calibration, CRPS and
model evaluation, so nothing a forecast depends on is an input to this job. It opens no
database that holds a forecast -- its only database is a disposable DuckDB containing one
capture -- and `RESTATED_FILES` is enforced before anything is written, so a restatement
that names `players.json` is refused rather than published.

## The anti-join, and why substituting it is conservative

Provisional eligibility is one frozen contract, written once in
`src/fpl/publish/provisional_sql.py` and used by both the BI export and this job. Its
`finalized_fixture` anti-join is what makes the preview-to-final handoff fixture-atomic:
one immutable finalized row retires the whole fixture from both previews.

The export supplies that anti-join from the archive marts and the append-only ledgers. This
job has neither, so it supplies the published `player_actuals.json` and `team_actuals.json`
instead. The substitution can only ever *remove* a fixture from the preview -- a fixture the
public already carries as finalized -- and can never add one, so the preview it produces is
a subset of what the full refresh would produce from the same capture.

Identity comes from the same capture, through `capture_identity_queries()`: the club and
fixture dimensions are the live halves of the export's own `dim_team_season` and
`dim_fixture`, column for column, projected through the semantic contract by
`_contract_query` so the frames the shared builders receive carry the declared types.

## What it refuses

* a base URL that is not HTTPS, or a pointer that is not the complete public file set;
* any published object whose bytes disagree with the pointer's sha256 or size;
* a capture that is not a completed-match (`player-history`) capture;
* a restatement naming any file outside `RESTATED_FILES`;
* a preview that would land on only one side. The published envelope pins one capture time
  across both documents and requires it to be null when a document has no rows, so a
  lopsided pair is unpublishable. Reaching that state means the published forecast
  population covers no player in any captured fixture, which an ordinary new registration
  does not cause -- a newcomer is simply absent from the player preview while his team
  mates remain.

When the restatement reproduces the published preview exactly, it publishes nothing and
says so. That is the expected outcome whenever the desktop refresh has already run.

## Operation

```bash
python -m fpl.jobs.republish_provisional --out "$RUNNER_TEMP/provisional-republish" \
    [--capture snapshots/player-history-provisional/<season>/gw-<gw>/<package>] \
    [--r2-config /outside/the/repo/config.json]
```

Without `--r2-config` the restatement is built, validated and discarded -- the safe way to
inspect what a republish would do. With it, the existing `publish_r2_dashboard` uploads the
immutable generation, verifies every object, and only then moves the pointer under a
conditional request, so a concurrent desktop publish loses the race rather than clobbering.

`.github/workflows/provisional-republish.yml` runs it after a successful capture, and on
manual dispatch. It is deliberately **not** on a clock: each republish writes a new
immutable generation (currently about 30 MB compressed, since the all-vintage
`players.json` dominates and grows with every recorded forecast run), so it runs when a
capture actually changed and no-ops otherwise.

The R2 credential lives only in the `production-fpl` environment, is written to a file in
the runner's temporary directory outside the checkout, and never enters the repository, a
log line, a step output or the non-secret config file. The read side needs no credential at
all: the bucket is public and the job proves the bytes by hash.

## Verified

End to end against the live site on 2026-10-16: pointer
`c14ded26…b507d4` fetched and all 17 files verified against its inventory (384 MB), the
committed capture loaded into a disposable database, 440 published finalized fixtures
excluded, zero provisional rows produced, `restated_files` empty and nothing published --
the correct no-op, because that generation already carried GW1-GW6 as finalized.
`tests/test_provisional_republish.py` covers the positive path and every refusal above
against a synthetic published generation served exactly as R2 serves one.

## What this is not

Not a forecast refresh, not a replacement for the desktop cycle, and not permission for
provisional evidence to reach a ledger, a monitoring score or a model input. The full
refresh remains the only path that publishes a new forecast vintage, and the pinned GitHub
Pages release in `public-data-release.json` is untouched by this job.

## What the owner must configure once

The workflow needs a `production-fpl` GitHub environment holding five values. Four are
ordinary configuration and one is the credential; all five are read only by the step that
writes the config file, and none is echoed, logged or written into the repository.

| Name | Value |
| --- | --- |
| `R2_BUCKET` | the public dashboard bucket |
| `R2_ENDPOINT_URL` | `https://<account>.r2.cloudflarestorage.com` |
| `R2_PUBLIC_BASE_URL` | `https://data.thecometfpl.com` |
| `R2_ACCESS_KEY_ID` | R2 API token id |
| `R2_SECRET_ACCESS_KEY` | R2 API token secret |

The token needs only object read and write on that one bucket -- the same capability the
desktop publisher already uses, no account-level or zone-level scope. Nothing here is
needed to *read* the published site, so with the environment unset the workflow still runs
usefully: dispatch it with `stage_only`, or simply leave the secrets absent, and it builds
and verifies the restatement without publishing.

Until that environment exists the workflow is inert rather than broken: with none of the
five set it warns, stages, verifies and publishes nothing, so a daily capture does not turn
red over a setup step. With *some* of them set it fails instead -- a partial configuration
is a mistake, and quietly not publishing would hide it.
