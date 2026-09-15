# Vendored Premier League SDP payload shapes

**These are hand-authored payload SHAPES, not captured provider responses.** No SDP payload was
observable from the environment that authored them: every Pulselive / premierleague.com /
fantasy.premierleague.com host is refused by its egress policy, so nothing here can be
represented as real provider data.

What they exist for is the property that matters most for an undocumented upstream: the parser
must handle several plausible renderings of the same information, and must FAIL LOUDLY on one
it cannot interpret rather than guessing. Each file pins one of those cases:

| file | pins |
| --- | --- |
| `matches_page.json` | paged envelope: a `content` list with `pageInfo.totalElements` |
| `matches_bare_list.json` | the same records as a bare top-level list |
| `match_stats.json` | the documented `[{side, stats{}}, ...]` stats shape |
| `match_stats_list_form.json` | `stats` as a list of `{name, value}` records |
| `match_stats_one_sided.json` | a partial capture -- must be REFUSED, not stored |
| `match_stats_unknown_fields.json` | fields absent from the metric dictionary -- must be RETAINED |
| `matches_unknown_envelope.json` | an unrecognised envelope -- must raise, not return empty |

These small vendored shapes remain deterministic offline fixtures, not provider evidence. The real
capture is retained content-addressed in the local raw store and summarized in
`docs/pl-sdp-real-provider-validation-2026-09-05.md`. Promote `verified_semantics` only for fields
the independent reconciliation report corroborates.
