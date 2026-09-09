# Dashboard latest-vintage selection — 2026-09-09

The published dashboard already contained the registered primary forecast for GW4–GW8. Players,
Fixture Matrix, Player Analytics, and Team Analytics nevertheless opened on GW3–GW7 because their
shared default-vintage selector preferred the retained optimizer plan's older forecast run. The
manifest's final array entry was also unsuitable as a latest-run fallback because manifest runs are
ordered by run identity rather than forecast time.

Exploratory forecast pages now use `summary.latest_run` as their default when that run exists in the
published manifest. A retained optimizer plan remains selectable and remains authoritative on its
own plan/optimizer surface, but it cannot pin weekly fixture views to an old horizon. A central
regression test fixes this ordering rule and retains the optimizer-plan fallback when no valid latest
run is available.

Operational verification used primary run
`b7dcace67b3d185e2e498c4ff67980c99f93f899daded671323056a2de4457d5`: 654 player rows and 20 team
rows, with both fixture collections covering exactly GW4, GW5, GW6, GW7, and GW8. No forecast,
optimizer plan, model configuration, or prediction artifact was regenerated or modified.
