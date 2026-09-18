# Current price refresh recovery

At `2026-09-18T04:20:43.572924Z`, the official FPL bootstrap reported Bogle
(stable code `226182`) at 46 tenths and Haaland (`223094`) at 156 tenths.
The public R2 generation still reported 45 and 155 from its actual capture at
`2026-09-17T13:40:49.988338Z`. The current-price display code was deployed;
the source refresh had stopped.

The existing two-hour task remained enabled. Its latest 11:00 Bangkok attempt
returned exit 1. The preceding 23:00 run stopped during element-summary capture;
its last retained log line is 23:10:50. It left both cycle and database lock files
owned by PID 16524. That process was absent, no refresh process was active, the
task was idle and no database WAL existed. The exact cause of process termination
is not established; the configured execution limit remains two hours.

Before recovery, a read-only database inspection succeeded and its SHA256 exactly
matched that interrupted run's existing pre-run backup:
`b96a3fe70b34205a7c2b91e62aa7cf052e6b3500afca84178b040379ccf7e1bb`.
Both orphan lock records were moved into the diagnostic evidence directory,
preserving their content. No unresolved WAL or active writer was bypassed.

The existing bounded daily-snapshot routine then captured bootstrap, fixtures and
event-live under the existing cycle/writer locks. Capture
`6dff3bec-9306-4cf9-a81a-a093142b1daf` has actual timestamp
`2026-09-18T04:25:01.251169Z`, three payloads and bootstrap SHA256
`bd2066dba2ea125a0dfa34ca5671105093e949b4f1e9ca53216c14c6acdad21c`.
The validated reporting reader returns Bogle 46 and Haaland 156 from that capture.
This was a bounded price/status refresh, not a new full player-history or SDP sweep.
Existing player history and unchanged SDP source versions remain retained.

Publication uses the existing `refresh_dashboard --skip-capture --r2-config ...`
flow with the already registered forecast and its existing optimizer plan.
New price observations do not replace frozen forecast prices or predictions.
The enabled two-hour task and its sign-in trigger are unchanged. Retiring diagnosed
orphan locks restores its ability to start; a future successful scheduled cycle
must still be established from its own receipt.

The evidence directory is
`data/artifacts/price-goal-check-20260918T042042Z/`. It retains the direct API
comparison, database/backup hash check, original lock records and bounded-capture
receipt. Existing failed/incomplete run logs and all frozen forecasts remain intact.
