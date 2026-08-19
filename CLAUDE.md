# Claude Code shared project instructions

@AGENTS.md
@DEV-ROADMAP.md

`AGENTS.md` is the single source of truth for correctness policy, model/evaluation history,
repository boundaries, working protocol, and sub-agent instructions. `DEV-ROADMAP.md` is the single
source of truth for near-term delivery priority and acceptance criteria. Read both before acting;
through the 2026/27 GW1 deadline, complete the remaining roadmap P0 operations — remote parity,
the 2026-08-20 fallback pack, the 2026-08-21 final pack, and manual confirmation in the official
FPL UI — before new model research or non-blocking dashboard polish. The BI/dashboard MVP is
already implemented development-only.

Do not duplicate those instructions here. When status or priority changes, update the owning file in
the same change: invariant/history changes belong in `AGENTS.md`; delivery sequencing belongs in
`DEV-ROADMAP.md`.

Repository skills live only under `.claude/skills/`; these files are the single source of truth
for Claude Code and every other agent.
