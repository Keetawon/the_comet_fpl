# Owner-directed omitted-count display policy

Recorded at **2026-09-09T02:47:16.006705Z**, this descriptive Dashboard policy
shows selected omitted SDP count fields as an **assumed zero**. It applies only
to presentation and CSV export. Original provider fields remain NULL, retained
payloads remain immutable, SDP core health and production selection are
unchanged, and no assumption enters a forecast, model, optimizer or historical
audit.

Each assumed cell is marked `§` and states:

> Owner-directed display assumption. The provider field was omitted and this
> sparse count is shown as zero. It is not a provider-verified zero.

The sidecar stores the policy time, source-known time, exact provider match ID,
accepted omitted provider field names and raw payload SHA256. Tables, trends,
comparisons and CSV all use the same display reader. Corrections supported by
match-specific evidence remain separately marked `‡` and take precedence.

## Allowed sparse counts

- shots inside and outside the penalty area; blocked attacking attempts;
- big chances created, scored and missed;
- accurate crosses and corners;
- outfield blocks and goalkeeper saves;
- possession won in the attacking third;
- yellow cards, red cards and offsides.

This is a bounded allowlist. Missing xG, xGOT, possession, percentages,
high-volume/core passing counts, touches, tackles, duels and other unlisted
fields remain **Unavailable**. SOT is not generalized through this policy; the
existing five match-specific corrections continue to use their stronger
shot-accounting and FPL goalkeeper corroboration.

`attemptsObox` means shots originating outside the penalty area. It is not the
same as `shotOffTarget`, which describes the outcome of an attempt. A missing
`attemptsObox` is now displayed as assumed zero under this policy; its raw value
is still NULL.

## Verified current export

At cutoff `2026-09-09T03:07:52.565391Z`, sidecar SHA256
`0363b29e86b62422fdd122e7bf829cd74719b152d5853e8233a21463eea9089c`
contains **1,493** assumed cells across all retained seasons. The current 2026/27 GW1–3 population contains
**83** assumed cells across 51 team-match sides. The underlying current source
inventory remains 30 completed fixtures, 26 provider core-valid and four
provider-incomplete fixtures. The five prior owner-confirmed display corrections
remain separate.

The policy is a display convention adopted after these matches. Applying it to
historical Dashboard rows does not establish that a zero was known at a past
prediction deadline and does not change any evidence class or `known_at` value.
