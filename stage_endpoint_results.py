"""ADscape endpoint-assessment staging: fetch CT.gov's own posted results data
(resultsSection.outcomeMeasuresModule) for the scoped trial subset and match
each posted measure back to its registered `outcomes` row. Pure data
retrieval against the public CT.gov API - NOT the Anthropic API, no LLM call
here. See endpoint_backfill_no_api.md: the actual met/significance judgment
is made by direct reasoning in the Claude Code session itself, not a script -
this just prepares the source text for that.

Output: staging/endpoint_source/<nct_id>.json, one file per trial, each
containing the compact extracted measure data + best-guess match to an
`outcomes.id` row (by normalized title match) for review.
"""

import json
import re
import sys
import time
from pathlib import Path

import requests

from db import connect

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STAGING_DIR = Path(__file__).parent / "staging" / "endpoint_source"
USER_AGENT = "ADscape-pipeline/0.1 (+https://github.com/dhlee47/ADscape)"


def normalize(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def extract_measure(m):
    """Compact extraction - drop verbose API scaffolding, keep the actual data."""
    groups = {g.get("id"): g.get("title") for g in m.get("groups", [])}

    denoms = []
    for d in m.get("denoms", []):
        for c in d.get("counts", []):
            denoms.append({"group": groups.get(c.get("groupId"), c.get("groupId")), "value": c.get("value")})

    data_rows = []
    for cls in m.get("classes", []):
        for cat in cls.get("categories", []):
            for meas in cat.get("measurements", []):
                data_rows.append({
                    "class": cls.get("title"),
                    "category": cat.get("title"),
                    "group": groups.get(meas.get("groupId"), meas.get("groupId")),
                    "value": meas.get("value"),
                    "spread": meas.get("spread"),
                    "lower": meas.get("lowerLimit"),
                    "upper": meas.get("upperLimit"),
                })

    analyses = []
    for a in m.get("analyses", []):
        analyses.append({
            "groups": [groups.get(gid, gid) for gid in a.get("groupIds", [])],
            "non_inferiority_type": a.get("nonInferiorityType"),
            "param_type": a.get("paramType"),
            "param_value": a.get("paramValue"),
            "p_value": a.get("pValue"),
            "statistical_method": a.get("statisticalMethod"),
            "statistical_comment": a.get("statisticalComment"),
            "ci_pct": a.get("ciPctValue"),
            "ci_lower": a.get("ciLowerLimit"),
            "ci_upper": a.get("ciUpperLimit"),
            "dispersion_type": a.get("dispersionType"),
            "estimate_comment": a.get("estimateComment"),
        })

    return {
        "title": m.get("title"),
        "description": m.get("description"),
        "population_description": m.get("populationDescription"),
        "reporting_status": m.get("reportingStatus"),
        "param_type": m.get("paramType"),
        "unit_of_measure": m.get("unitOfMeasure"),
        "type": m.get("type"),
        "time_frame": m.get("timeFrame"),
        "denoms": denoms,
        "data": data_rows,
        "analyses": analyses,
    }


def match_outcome(measure_title, registered_outcomes):
    """Best-effort match of a posted measure to a registered outcomes.id row
    by normalized title equality/substring. Returns (outcome_id, method) or
    (None, 'unmatched')."""
    norm_title = normalize(measure_title)
    if not norm_title:
        return None, "unmatched"

    for o in registered_outcomes:
        if normalize(o["measure"]) == norm_title:
            return o["id"], "exact"

    for o in registered_outcomes:
        norm_measure = normalize(o["measure"])
        if norm_measure and (norm_measure in norm_title or norm_title in norm_measure):
            return o["id"], "substring"

    return None, "unmatched"


def main():
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()

    trials = conn.execute(
        """
        SELECT nct_id FROM trials
        WHERE results_posted = 1
          AND overall_status IN ('COMPLETED', 'TERMINATED')
          AND bucket_id IS NOT NULL
          AND bucket_id != 'unclassified'
        ORDER BY nct_id
        """
    ).fetchall()
    print(f"{len(trials)} trials to stage.")

    match_stats = {"exact": 0, "substring": 0, "unmatched": 0}
    errors = 0
    for i, t in enumerate(trials, 1):
        nct_id = t["nct_id"]
        out_path = STAGING_DIR / f"{nct_id}.json"
        if out_path.exists():
            continue

        registered = [
            dict(r)
            for r in conn.execute(
                "SELECT id, outcome_type, measure, description, time_frame FROM outcomes WHERE nct_id = ?",
                (nct_id,),
            ).fetchall()
        ]

        try:
            resp = requests.get(
                f"https://clinicaltrials.gov/api/v2/studies/{nct_id}",
                params={"format": "json"},
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            errors += 1
            print(f"  [{i}/{len(trials)}] {nct_id}: ERROR fetching - {exc}")
            continue

        raw_measures = data.get("resultsSection", {}).get("outcomeMeasuresModule", {}).get("outcomeMeasures", [])
        staged_measures = []
        for m in raw_measures:
            extracted = extract_measure(m)
            outcome_id, method = match_outcome(extracted["title"], registered)
            match_stats[method] += 1
            extracted["matched_outcome_id"] = outcome_id
            extracted["match_method"] = method
            staged_measures.append(extracted)

        out_path.write_text(
            json.dumps(
                {
                    "nct_id": nct_id,
                    "registered_outcomes": registered,
                    "posted_measures": staged_measures,
                },
                indent=1,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        if i % 25 == 0:
            print(f"  ... {i}/{len(trials)} staged")
        time.sleep(0.15)

    print(f"\nDone. {len(trials) - errors} trial(s) staged, {errors} fetch error(s).")
    print(f"Measure-to-outcome matching: {match_stats}")


if __name__ == "__main__":
    main()
