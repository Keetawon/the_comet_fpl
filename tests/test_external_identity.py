"""Season-scoped external -> FPL identity resolution.

Offline and deterministic: rosters are hand-built. The tests pin the matching precedence
(opta anchor, then name+club, then name-in-season), the ambiguity guard (a name shared by two
players in one season is never guessed), and the season isolation that keeps a bare
cross-season id from ever leaking into a match.
"""

from __future__ import annotations

from fpl.transform.external_identity import (
    ExternalRosterEntry,
    FplRosterEntry,
    build_identity_crosswalk,
    normalise_name,
)


def test_normalise_strips_accents_punctuation_and_case() -> None:
    assert normalise_name("Raya Martín") == "raya martin"
    assert normalise_name("O'Riley") == "o riley"
    assert normalise_name("  De  Bruyne ") == "de bruyne"
    assert normalise_name("N'Golo Kanté") == "n golo kante"
    assert normalise_name("--") == ""


def test_opta_code_anchors_the_match() -> None:
    fpl = [
        FplRosterEntry(
            "2025-26", code=118748, team_code=3, full_name="Mohamed Salah", opta_code="p118748"
        )
    ]
    external = [
        ExternalRosterEntry(
            "2025-26", external_id="x1", full_name="Mo Salah", team_code=None, opta_code="p118748"
        )
    ]
    report = build_identity_crosswalk(fpl, external, season="2025-26")
    assert report.match_rate == 1.0
    assert report.matches[0].code == 118748
    assert report.matches[0].method == "opta"
    # Name did not have to agree; the opta id carried it.


def test_name_plus_club_resolves_without_opta() -> None:
    fpl = [
        FplRosterEntry("2023-24", code=1, team_code=3, full_name="David Raya Martín"),
        FplRosterEntry("2023-24", code=2, team_code=7, full_name="David Raya Martín"),
    ]
    external = [
        ExternalRosterEntry("2023-24", external_id="a", full_name="David Raya Martin", team_code=7)
    ]
    report = build_identity_crosswalk(fpl, external, season="2023-24")
    assert len(report.matches) == 1
    assert report.matches[0].code == 2
    assert report.matches[0].method == "name_club"


def test_name_in_season_is_the_fallback_when_club_unknown() -> None:
    fpl = [FplRosterEntry("2023-24", code=9, team_code=11, full_name="Bruno Guimarães")]
    external = [
        ExternalRosterEntry("2023-24", external_id="b", full_name="Bruno Guimaraes", team_code=None)
    ]
    report = build_identity_crosswalk(fpl, external, season="2023-24")
    assert report.matches[0].code == 9
    assert report.matches[0].method == "name_season"


def test_shared_name_without_a_disambiguator_is_ambiguous_not_guessed() -> None:
    """Two players share a normalised name in one season and the external row lacks a club."""
    fpl = [
        FplRosterEntry("2023-24", code=10, team_code=3, full_name="Danny Ward"),
        FplRosterEntry("2023-24", code=11, team_code=7, full_name="Danny Ward"),
    ]
    external = [
        ExternalRosterEntry("2023-24", external_id="c", full_name="Danny Ward", team_code=None)
    ]
    report = build_identity_crosswalk(fpl, external, season="2023-24")
    assert report.matches == ()
    assert report.ambiguous_external == ("c",)
    assert report.match_rate == 0.0


def test_shared_name_is_disambiguated_by_club() -> None:
    fpl = [
        FplRosterEntry("2023-24", code=10, team_code=3, full_name="Danny Ward"),
        FplRosterEntry("2023-24", code=11, team_code=7, full_name="Danny Ward"),
    ]
    external = [
        ExternalRosterEntry("2023-24", external_id="c", full_name="Danny Ward", team_code=7)
    ]
    report = build_identity_crosswalk(fpl, external, season="2023-24")
    assert report.matches[0].code == 11
    assert report.matches[0].method == "name_club"
    assert report.ambiguous_external == ()


def test_unmatched_external_and_fpl_are_reported() -> None:
    fpl = [
        FplRosterEntry("2023-24", code=1, team_code=3, full_name="Matched Player"),
        FplRosterEntry("2023-24", code=2, team_code=3, full_name="Never Seen"),
    ]
    external = [
        ExternalRosterEntry("2023-24", external_id="m", full_name="Matched Player", team_code=3),
        ExternalRosterEntry("2023-24", external_id="u", full_name="Not In Fpl", team_code=3),
    ]
    report = build_identity_crosswalk(fpl, external, season="2023-24")
    assert [m.external_id for m in report.matches] == ["m"]
    assert report.unmatched_external == ("u",)
    assert report.unmatched_fpl == (2,)


def test_other_seasons_are_filtered_out_before_matching() -> None:
    """A same-name, same-opta entry in a different season must never resolve the row."""
    fpl = [
        FplRosterEntry(
            "2024-25", code=308, team_code=3, full_name="Someone Else", opta_code="p999"
        ),
        FplRosterEntry(
            "2025-26", code=118748, team_code=3, full_name="Mohamed Salah", opta_code="p999"
        ),
    ]
    external = [
        ExternalRosterEntry("2025-26", external_id="s", full_name="Mo Salah", opta_code="p999")
    ]
    report = build_identity_crosswalk(fpl, external, season="2025-26")
    # Only the 2025-26 FPL entry is in scope, so opta p999 resolves uniquely to Salah.
    assert report.fpl_count == 1
    assert report.matches[0].code == 118748


def test_matched_by_method_counts_each_rule() -> None:
    fpl = [
        FplRosterEntry("2025-26", code=1, team_code=3, full_name="Opta Guy", opta_code="p1"),
        FplRosterEntry("2025-26", code=2, team_code=7, full_name="Club Guy"),
        FplRosterEntry("2025-26", code=3, team_code=9, full_name="Season Guy"),
    ]
    external = [
        ExternalRosterEntry("2025-26", external_id="a", full_name="whatever", opta_code="p1"),
        ExternalRosterEntry("2025-26", external_id="b", full_name="Club Guy", team_code=7),
        ExternalRosterEntry("2025-26", external_id="c", full_name="Season Guy", team_code=None),
    ]
    report = build_identity_crosswalk(fpl, external, season="2025-26")
    assert report.matched_by_method == {"opta": 1, "name_club": 1, "name_season": 1}
    assert report.match_rate == 1.0
