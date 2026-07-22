"""Generate docs/data/*.json for the static dashboards from adscape.db. See dashboard_spec.md."""

import json
from collections import defaultdict
from pathlib import Path

from db import connect

DOCS_DATA = Path(__file__).parent / "docs" / "data"

PHASE_LABELS = {
    "PHASE1": "Phase 1",
    "PHASE2": "Phase 2",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "EARLY_PHASE1": "Early Phase 1",
    "NA": "N/A",
}

# Short chart-friendly labels - mechanism_buckets.description is the full
# catalog text (a sentence), too long for axis labels/legends/table cells.
BUCKET_SHORT_LABELS = {
    "anti_amyloid_immunotherapy": "Anti-amyloid immunotherapy",
    "amyloid_production": "Amyloid production (secretase)",
    "tau_targeted": "Tau-targeted",
    "neuroinflammation_microglia_complement": "Neuroinflammation/microglia",
    "apoe_lipid_metabolism": "APOE/lipid metabolism",
    "synaptic_neurotransmitter": "Synaptic/neurotransmitter",
    "regenerative_neurotrophic": "Regenerative/neurotrophic",
    "unclassified": "Unclassified",
}


def bucket_label(bucket_id):
    if bucket_id is None:
        return "Not yet classified"
    return BUCKET_SHORT_LABELS.get(bucket_id, bucket_id)


def phase_label(raw):
    if not raw:
        return "Not specified"
    parts = [PHASE_LABELS.get(p, p) for p in raw.split(",")]
    return "/".join(dict.fromkeys(parts))  # dedupe while preserving order, e.g. "PHASE2,PHASE2"


def build_landscape(conn):
    total_trials = conn.execute("SELECT COUNT(*) AS c FROM trials").fetchone()["c"]

    last_sync_row = conn.execute(
        "SELECT MAX(completed_at) AS last FROM pipeline_runs WHERE status = 'success'"
    ).fetchone()
    last_sync = last_sync_row["last"]

    status_breakdown = [
        {"status": r["overall_status"] or "UNKNOWN", "count": r["c"]}
        for r in conn.execute(
            "SELECT overall_status, COUNT(*) AS c FROM trials GROUP BY overall_status ORDER BY c DESC"
        ).fetchall()
    ]

    by_mechanism = [
        {
            "bucket_id": r["bucket_id"] or "__unclassified_pending__",
            "label": bucket_label(r["bucket_id"]),
            "count": r["c"],
        }
        for r in conn.execute(
            """
            SELECT t.bucket_id, COUNT(*) AS c
            FROM trials t
            GROUP BY t.bucket_id
            ORDER BY c DESC
            """
        ).fetchall()
    ]

    phase_counts = defaultdict(int)
    for r in conn.execute("SELECT phase, COUNT(*) AS c FROM trials GROUP BY phase").fetchall():
        phase_counts[phase_label(r["phase"])] += r["c"]
    by_phase = [{"phase": k, "count": v} for k, v in sorted(phase_counts.items(), key=lambda kv: -kv[1])]

    # trials over time: one series per bucket_id, keyed by start_date year
    rows = conn.execute(
        """
        SELECT substr(t.start_date, 1, 4) AS year, t.bucket_id
        FROM trials t
        WHERE t.start_date IS NOT NULL AND length(t.start_date) >= 4
        """
    ).fetchall()
    years = sorted({r["year"] for r in rows if r["year"] and r["year"].isdigit()})
    series_counts = defaultdict(lambda: defaultdict(int))
    series_labels = {}
    for r in rows:
        y = r["year"]
        if not y or not y.isdigit():
            continue
        bucket_key = r["bucket_id"] or "__unclassified_pending__"
        series_labels[bucket_key] = bucket_label(r["bucket_id"])
        series_counts[bucket_key][y] += 1
    trials_over_time = {
        "years": years,
        "series": [
            {
                "bucket_id": bucket_key,
                "label": series_labels[bucket_key],
                "data": [series_counts[bucket_key].get(y, 0) for y in years],
            }
            for bucket_key in sorted(series_labels, key=lambda k: -sum(series_counts[k].values()))
        ],
    }

    sponsor_rows = conn.execute(
        """
        SELECT s.name, COUNT(DISTINCT s.nct_id) AS c
        FROM sponsors s
        WHERE s.role = 'lead'
        GROUP BY s.name
        ORDER BY c DESC
        LIMIT 15
        """
    ).fetchall()
    top_sponsors = []
    for r in sponsor_rows:
        bucket_rows = conn.execute(
            """
            SELECT DISTINCT t.bucket_id
            FROM sponsors s
            JOIN trials t ON t.nct_id = s.nct_id
            WHERE s.role = 'lead' AND s.name = ?
            """,
            (r["name"],),
        ).fetchall()
        top_sponsors.append(
            {
                "name": r["name"],
                "count": r["c"],
                "buckets": sorted(bucket_label(b["bucket_id"]) for b in bucket_rows),
            }
        )

    return {
        "total_trials": total_trials,
        "last_sync": last_sync,
        "status_breakdown": status_breakdown,
        "by_mechanism": by_mechanism,
        "by_phase": by_phase,
        "trials_over_time": trials_over_time,
        "top_sponsors": top_sponsors,
    }


def build_ops(conn):
    recent_runs = [
        dict(r)
        for r in conn.execute(
            "SELECT run_type, started_at, completed_at, status, records_fetched, records_upserted, error_message "
            "FROM pipeline_runs ORDER BY id DESC LIMIT 10"
        ).fetchall()
    ]

    pending_proposals = [
        dict(r)
        for r in conn.execute(
            "SELECT proposed_bucket_json, supporting_items, rationale, proposed_at "
            "FROM taxonomy_proposals WHERE status = 'pending' ORDER BY proposed_at DESC"
        ).fetchall()
    ]

    low_confidence = [
        {**dict(r), "bucket_label": bucket_label(r["bucket_id"])}
        for r in conn.execute(
            """
            SELECT t.nct_id, t.brief_title, t.bucket_id,
                   t.classification_confidence, t.classification_rationale
            FROM trials t
            WHERE t.classification_confidence >= 0.4 AND t.classification_confidence < 0.7
            ORDER BY t.classification_confidence ASC
            """
        ).fetchall()
    ]

    watchlist = [
        dict(r)
        for r in conn.execute(
            "SELECT entity, item_count, first_seen_at, last_seen_at, note "
            "FROM curator_watchlist ORDER BY item_count DESC, last_seen_at DESC"
        ).fetchall()
    ]

    spot_check_log = [
        dict(r)
        for r in conn.execute(
            "SELECT nct_id, bucket_agreement, outcome_agreement, checked_at, notes "
            "FROM spot_check_log ORDER BY checked_at DESC"
        ).fetchall()
    ]
    agreement_counts = defaultdict(int)
    for row in spot_check_log:
        if row["bucket_agreement"]:
            agreement_counts[row["bucket_agreement"]] += 1
    classified_count = conn.execute(
        "SELECT COUNT(*) AS c FROM trials WHERE bucket_id IS NOT NULL"
    ).fetchone()["c"]
    unclassified_count = conn.execute(
        "SELECT COUNT(*) AS c FROM trials WHERE bucket_id IS NULL"
    ).fetchone()["c"]

    return {
        "recent_runs": recent_runs,
        "classified_count": classified_count,
        "unclassified_count": unclassified_count,
        "pending_proposals": pending_proposals,
        "low_confidence": low_confidence,
        "watchlist": watchlist,
        "spot_check": {
            "agreement_counts": dict(agreement_counts),
            "log": spot_check_log,
        },
    }


def main():
    conn = connect()
    DOCS_DATA.mkdir(parents=True, exist_ok=True)

    landscape = build_landscape(conn)
    ops = build_ops(conn)

    (DOCS_DATA / "landscape.json").write_text(json.dumps(landscape, indent=2), encoding="utf-8")
    (DOCS_DATA / "ops.json").write_text(json.dumps(ops, indent=2), encoding="utf-8")
    print(f"Wrote {DOCS_DATA / 'landscape.json'}")
    print(f"Wrote {DOCS_DATA / 'ops.json'}")


if __name__ == "__main__":
    main()
