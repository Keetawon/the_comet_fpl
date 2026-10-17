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

## Owner follow-up: minute markers and current GW7 news

The English unknown-minute label now reads **midweek minutes unknown or did not
play**, with the equivalent Thai wording. It describes the two possibilities;
it does not reclassify missing evidence as confirmed non-participation. Witnessed
appearances with missing durations still say that the player played but the
minutes are unknown. Confirmed zero and no-fixture descriptions remain distinct.

Each player name in the shared message carries **🟠** for more than 45 published
nominal midweek minutes or **🟡** for a positive total up to and including 45.
Zero, missing minutes and an unavailable fixture-matched report have no marker.
The symbols use the reported total, not xP or a fitness inference. The legend is
included in both languages and remains part of the copied/downloaded text.

The existing bounded, authorized FFScout capture retrieved 47 posts from
15–16 October. Twenty current club reports were selected, using the later Hull
duplicate and excluding promotional posts. Each English/Thai editorial digest
was checked against its complete retained post, with append-only exact-summary
review receipts and `Codex-source-reviewed-editorial` provenance. This is agent
review, not independent human approval. No additional language-provider call or
new unattended capture schedule was used.

All 20 clubs match the current official season registry. Spurs' report explicitly
retains the pending Sunday, 18 October conference and Bentancur's three-gameweek
suspension; it is not labelled a completed conference. Other reports preserve
uncertainty, training-only updates and FFScout's own stated inferences.

The refreshed news edition was published and independently read back with SHA-256
`ffd5e7b46797417ca775b48a5102d264706f90fcf2473677cd81c3ae897070e1`.
Private source/review records and the official registry replay remain under the
existing operations news directory. No forecast generation was republished.

Validation: **838 dashboard tests** and **80 Python news checks** pass. Dashboard
lint and the hosted production build pass with the existing lint warnings. The
new regression checks cover 45 versus 46 minutes, zero/null values, witnessed
appearances with unknown minutes, grouped player names, both languages and no
marker on a later DGW leg without a matching rest report. Python source and the
previously documented unrelated full-suite/format failures are unchanged.

Live text verification found 115 orange and 55 yellow player markers across all
ten GW7 fixtures, with zero/unknown minutes unmarked and all 20 current news links
present in both languages. Copying the entire English message succeeded. The
marker update deployed through Pages run `38985760189` (merge `2047337`).

The screenshot check found that an older Windows emoji font rendered the two
circles as empty boxes. An explicit system emoji fallback alone did not fix it.
The shared message now includes a self-hosted **840-byte** Noto Color Emoji WOFF2
subset restricted to U+1F7E0 and U+1F7E1, with native Apple Color Emoji preferred
on Apple devices. It leaves the Unicode copy/share text unchanged. The font has
no runtime Google request or new npm dependency. Its SIL Open Font License is
included at `dashboard/public/licenses/noto-color-emoji-OFL.txt`.

Source: [Noto Emoji](https://github.com/googlefonts/noto-emoji), obtained via the
Google Fonts CSS API's exact two-character `text` subset using a modern browser
user agent. The retained WOFF2 SHA-256 is
`a15dd66c82288446c8fcaca5275339854715538770c061d1b4d3594e7176e653`.
The subset response was bounded to 20 KB before retention. The legacy TrueType
response was rejected for exceeding the bound and was never saved or shipped.
The built browser preview visually confirms distinct orange/yellow circles on
the affected Windows browser. No forecast or rest data was changed for this fix.
