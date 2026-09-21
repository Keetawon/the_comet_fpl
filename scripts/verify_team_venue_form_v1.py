"""Read-only independent arithmetic and serialized score replay; never refits a model."""

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from fpl.validate.audit_json import canonical
from fpl.validate.dev_team_venue_form import compare, publish


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    name = "team_venue_form_v1_20260921"
    folder = root / "data/artifacts" / name
    report_path = root / "results" / f"{name}.json"
    report = json.loads(report_path.read_bytes())
    inputs = json.loads(gzip.decompress((folder / "inputs.json.gz").read_bytes()))
    checks: Counter[str] = Counter()

    def check(ok: bool, category: str) -> None:
        if not ok:
            raise AssertionError(category)
        checks[category] += 1

    def key(r: dict[str, Any]) -> tuple[str, int, int]:
        return r["season"], r["fixture"], r["team_code"]

    def equal(a: float | None, b: float | None) -> bool:
        return a is b if a is None or b is None else math.isclose(a, b, abs_tol=1e-12, rel_tol=0)

    def average(rows: list[dict[str, Any]], d: int) -> float | None:
        v = [r["values"][d] for r in rows if r["values"][d] is not None]
        return math.fsum(v) / len(v) if v else None

    def weighted(
        rows: list[dict[str, Any]], d: int, weights: list[float], median: bool = False
    ) -> tuple[float | None, int]:
        v = [
            (r["values"][d], w)
            for r, w in zip(rows, weights, strict=False)
            if r["values"][d] is not None
        ]
        if not v:
            return None, 0
        total = math.fsum(w for _, w in v)
        if not median:
            return math.fsum(x * w for x, w in v) / total, len(v)
        v.sort()
        c = 0.0
        for i, (x, w) in enumerate(v):
            c = math.fsum((c, w))
            if abs(c - total / 2) <= 1e-12:
                return (x + v[i + 1][0]) / 2, len(v)
            if c > total / 2:
                return x, len(v)
        raise AssertionError("positive weights must cross midpoint")

    def blend(raw: float | None, prior: float | None, n: int, k: int) -> float | None:
        return (
            n / (n + k) * raw + k / (n + k) * prior
            if raw is not None and prior is not None
            else prior
        )

    target = {key(r): r for r in inputs["targets"]}
    interpreted = {key(r): r for r in inputs["interpreted_sot"]}
    check(len(target) == len(interpreted) == 3800, "population")
    zero_rows = []
    for r in interpreted.values():
        other = interpreted[r["season"], r["fixture"], r["opponent_team_code"]]
        check(
            other["opponent_team_code"] == r["team_code"] and other["was_home"] != r["was_home"],
            "reciprocal_identity",
        )
        if r["shots_on_target"] is None and r["shots_on_target_corroborated"] == 0:
            zero_rows.append(
                {
                    "season": r["season"],
                    "fixture": r["fixture"],
                    "team_code": r["team_code"],
                    "opponent_team_code": r["opponent_team_code"],
                    "raw_sot": None,
                    "interpreted_sot": 0,
                    "opponent_interpreted_sot_against": 0,
                    "reason": r["sot_interpretation"],
                    "payload_sha256": r["payload_sha256"],
                    "source_known_at": r["source_known_at"],
                }
            )

    experiments: dict[str, Any] = {}
    form_coverage: dict[str, Any] = {}
    for arm in ["C0", "C1", "A", "B", "C", "D"]:
        body = (folder / f"{arm}.json.gz").read_bytes()
        check(hashlib.sha256(body).hexdigest() == report["artifacts_sha256"][arm], "artifact_hash")
        saved = json.loads(gzip.decompress(body))
        experiments[arm] = saved["chance"]
        raw = json.loads(canonical(inputs["raw_states"]))
        if arm != "C0":
            for r in raw:
                sot = interpreted[key(r)]["shots_on_target_corroborated"]
                shots = target[key(r)]["shots"]
                r["values"][0] = (
                    sot / shots if sot is not None and shots is not None and shots > 0 else None
                )
        raw_by_key = {key(r): r for r in raw}
        cache: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
        ages = []
        counts = []
        for r in saved["upstream"]["rows"]:
            as_of = r["as_of"]
            batch = (r["season"], r["gw"], as_of)
            if batch not in cache:
                cache[batch] = [
                    x
                    for x in raw
                    if x["kickoff"] < as_of and (x["season"], x["gw"]) != (r["season"], r["gw"])
                ]
            visible = cache[batch]
            own = sorted(
                [
                    x
                    for x in visible
                    if x["team_code"] == r["team_code"] and x["season"] == r["season"]
                ],
                key=lambda x: (x["kickoff"], x["fixture"]),
                reverse=True,
            )
            overall = own[:5]
            venue = [x for x in own if x["was_home"] == r["was_home"]][:5]
            check(r["form"]["venue_keys"] == [list(key(x)) for x in venue], "venue_window")
            check(r["form"]["overall_keys"] == [list(key(x)) for x in overall], "overall_window")
            check(r["form"]["venue_matches"] == len(venue), "venue_matches")
            expected_age = (
                (
                    datetime.fromisoformat(as_of) - datetime.fromisoformat(venue[-1]["kickoff"])
                ).total_seconds()
                / 86400
                if venue
                else None
            )
            check(equal(r["form"]["venue_age_days"], expected_age), "venue_age")
            if r["season"] in report["provenance"]["contract"]["eligible_seasons"]:
                counts.append(len(venue))
                if expected_age is not None:
                    ages.append(expected_age)
            for d in range(5):
                prior = average(visible, d)
                ov, no = weighted(
                    overall,
                    d,
                    [1, 0.707, 0.5, 0.354, 0.25]
                    if arm in ["C0", "C1"]
                    else [0.4, 0.3, 0.2, 0.07, 0.03],
                )
                a = blend(ov, prior, no, 2)
                ve, nv = weighted(venue, d, [0.4, 0.3, 0.2, 0.07, 0.03], median=arm == "D")
                vp = average([x for x in visible if x["was_home"] == r["was_home"]], d)
                if vp is None:
                    vp = prior
                expected = (
                    a if arm in ["C0", "C1", "A"] else blend(ve, vp if arm == "B" else a, nv, 3)
                )
                check(equal(r["current_state"][d], expected), "state_arithmetic")
                check(r["form"]["venue_valid_counts"][d] == nv, "feature_count")
            check(
                r["source_known_at"] == raw_by_key[key(r)]["source_known_at"],
                "truthful_knowledge_time",
            )
            for field in ["maximum_state_source_event", "maximum_style_training_event"]:
                check(r[field] is None or r[field] < as_of, "causal_trace")
        scored = saved["chance"]["rows"]
        paired = {key(r): r for r in scored}
        check(
            len(scored) == 2280 and len({(r["season"], r["gw"]) for r in scored}) == 114,
            "scored_population",
        )
        for r in scored:
            t = target[key(r)]
            other = paired[r["season"], r["fixture"], r["opponent_team_code"]]
            check(
                (r["observed_goals"], r["observed_shots"], r["observed_archive_xg"])
                == (t["goals"], t["shots"], t["expected_goals"]),
                "unchanged_targets",
            )
            check(
                r["clean_sheet_probabilities"]["candidate"]
                == other["distributions"]["candidate"][0],
                "reciprocal_cs",
            )
            check(
                r["predicted_opponent_state"] == other["predicted_state"],
                "reciprocal_predicted_state",
            )
        for f in saved["chance"]["historical_folds"]:
            for fit in [*f["stage_fits"].values(), f["conversion_fit"]]:
                for field in ["maximum_training_event", "maximum_training_prediction_cutoff"]:
                    check(fit[field] is None or fit[field] < f["as_of"], "downstream_causal_fit")
        ages.sort()
        form_coverage[arm] = {
            "venue_match_counts": dict(Counter(counts)),
            "venue_age_days_median": ages[len(ages) // 2],
            "venue_age_days_max": max(ages),
        }

    for label, original in report["comparisons"].items():
        arm, control = label.split("_vs_")
        replay = compare(experiments, arm, control, report["provenance"]["contract"])
        check(canonical(replay) == canonical(original), "byte_identical_score_replay")
    for p, sha in report["provenance"]["source_sha256"].items():
        check(hashlib.sha256((root / p).read_bytes()).hexdigest() == sha, "frozen_source_file")
    verification = {
        "experiment": name,
        "result_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "checks": dict(checks),
        "total_checks": sum(checks.values()),
        "failures": 0,
        "model_refits": 0,
        "form_coverage": form_coverage,
        "interpreted_zero_rows": zero_rows,
    }
    verification_path = root / "results/team_venue_form_v1_verification_20260921.json"
    if args.verify_existing:
        if verification_path.read_bytes() != canonical(verification):
            raise AssertionError("verification receipt differs")
    else:
        publish(verification_path, verification)
    print(
        json.dumps(
            {"checks": sum(checks.values()), "failures": 0, "form_coverage": form_coverage},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
