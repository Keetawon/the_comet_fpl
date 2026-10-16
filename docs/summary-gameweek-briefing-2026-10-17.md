# Combined Summary gameweek briefing

Summary now offers **Create GW briefing** for its selected forecast and current
schedule gameweek. It produces one English or Thai text message, with Copy text,
native Share, Copy for Facebook and TXT download. A direct LINE link is offered
only when the complete encoded message fits the existing application URL bound;
longer messages use copy/native sharing without truncation. Facebook requires
the user to paste the copied text. No message is posted automatically.

Every scheduled fixture appears once, in kickoff order:

```text
1) Home club (n) - (m) Away club
Kickoff · original expected-goal estimates
Home team news / press conference
Away team news / press conference
Home player rest days and midweek minutes
Away player rest days and midweek minutes
```

The headline numbers retain Score Prediction's rounded expected-goal display,
explicitly labelled as averages rather than exact-score picks. Missing or moved
forecast fixtures remain in the schedule with unavailable scores. Conflicting
schedule identities prevent a purported complete briefing. No new distribution,
probability, availability adjustment or model quantity is computed.

The full published player roster is included; equal rest descriptions are grouped
to shorten the message. There is no top-15 restriction on this briefing. Each DGW
fixture has its own numbered section and club leg number. Rest joins require the
exact season, stable player/club codes, fixture, venue and kickoff. A report for
the first leg is never reused for the second leg. Later-leg rest remains unavailable
until the preceding appearance is actually witnessed. Blank weeks add no invented
fixture. The existing top-15 xP widget remains a separate quick view.

Rest uses published kickoff gaps and nominal club minutes. An unknown report is
not zero minutes or proof of rest. A confirmed non-participation can show zero;
a club without a midweek fixture has no measured minute value. Legacy reports
without both additive load fields remain valid. National-team minutes are not
captured, and incomplete schedule coverage stays visible in the message.

News is limited to dated @FFScout injury, suspension, squad and press-conference
reports from the selected season and club, within seven days. A different-GW
edition, demo, future-dated record, unresolved identity or failed source remains
unavailable. Reviewed status text and uncertainty are preserved verbatim, with
post timestamps and links. Missing reports do not establish fitness.

The existing news publisher now assigns stable club identity only when the exact
reviewed `CLUB | Team news` heading of `ffscout_press_conferences_v2` matches one
unique club name/code in the same edition's official bootstrap registry. It does
not fuzzy-match player names or rewrite captured observations. Three shorter
headings use explicit mappings to Coventry City/9, Hull City/88 and Ipswich Town/40,
checked against the official registry on 16 October. Both exact canonical name
and code must still match. The existing roundup metadata pins registry season,
capture time and SHA-256. No additional
paid call, autonomous summary approval or news-capture scheduler is introduced.

The live feed inspected during implementation was generated on 14 October from
8–9 October reports. Those reports have expired from this briefing; new news
requires the existing capture, factual review and publication process. The UI
honestly shows no verified update until that process publishes current reports.

Only the small news/rest sidecars load when the user opens the briefing. It uses
the Summary data already loaded and does not request the 15 MB SDP statistics
bundle. The established schema-v9 files and mobile payload budgets are unchanged.

Validation: all 829 dashboard tests pass, including DGW separation, all-player
coverage, missing/moved fixtures, stale or misidentified news, null-versus-zero
rest, language switching, source failure and full-text copying. The 80 Python
news checks pass. Dashboard production build, Ruff and strict mypy pass. The
existing repository formatting failures remain separately documented.

Browser verification on the built local page used the actual sanitized GW7 data:
all ten fixtures appeared in kickoff order, the English message contained 13,286
characters, and Copy text confirmed success. Responsive DOM inspection found the
text area narrower than the viewport. Screenshot capture timed out, so no visual
screenshot or physical iOS verification is claimed.
