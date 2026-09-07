# Chance runner preflight correction (2026-09-07)

The first CLI invocation at preregistration commit
`0beb0f51370cefdd441356b32e78b7f9f22b349d` stopped in the coverage comparison, before
incumbent reproduction, claim reservation, or any chance-model fitting/scoring. Neither
`data/evaluation-claims/retrospective_chance_creation_team_environment_v1.json` nor the
candidate result existed after that invocation. The single candidate identity was not consumed.
The external console record is
`D:\Personal\fpl-operations\verification\football-program-20260907T070000Z\chance-formal.log`.

Two serialization/provenance mismatches caused the guard to fail closed:

- The original coverage publisher used a UTC DuckDB session. The runner inherited
  `Asia/Bangkok`, so the same 1,900 capture instants serialized with `+07:00` instead of
  `+00:00`, changing the version-list hash without changing any instant or observation.
- The coverage publisher added the independently measured `database_sha256` to the pure
  coverage function's return value. The runner had compared that value without its database
  provenance field against the complete published envelope.

The bounded fix sets the read-only connection's session timezone to UTC and adds the
already independently verified database hash before exact canonical comparison. It does not
strip provenance keys, weaken the guard, rewrite timestamps, edit the database, or replace
the frozen coverage report. Full canonical equality then reproduces, including all counts,
values, identities and capture versions.

The candidate/model, features, parameters, population, gate, seed, coverage artifact and
evaluation config remain byte-for-byte unchanged. Config SHA256 remains
`3edb29cd29cbe7b3ab42e11eda9ab53dc061c7902602dd16ce7893f9b8640728`;
coverage SHA256 remains
`7d84bfec69b6e6dac1c95d973a723c7e4dbb218432cf5945d5616cb8664fb163`.
This is a pre-fit runner correction, not a numerical amendment or a second model trial.
The corrected runner/tests are committed cleanly before the candidate may reserve its one run.
