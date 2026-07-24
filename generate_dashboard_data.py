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
    # accepted curator_agent.py proposals (taxonomy.json v0.1.1-0.1.4) - see
    # review_proposal.py. mechanism_buckets.description is available for these
    # too but is the full candidate_bucket sentence, same length problem as
    # the original seed buckets above.
    "metabolic_insulin_glucose_signaling": "Metabolic/insulin-glucose signaling",
    "ketone_metabolic_substrate": "Ketone/MCT metabolic substrate",
    "senolytic_cellular_senescence": "Senolytics (cellular senescence)",
    "pde9_cgmp_signaling": "PDE9/cGMP signaling",
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
    """Per dashboard_changes_v1.md: landscape.html now needs a client-side
    status filter that cascades to every chart/table on the page, plus
    hover breakdowns by intervention name and by mechanism bucket. None of
    that is achievable from pre-aggregated GROUP BY rows (the v1 shape) once
    filtering has to recompute every chart in-browser - so this exports one
    row per trial instead, and every chart is now computed client-side in
    landscape.html from that array. This is a deliberate data-export change
    despite the spec's "no new SQL queries... unless noted otherwise" line;
    see ASSUMPTIONS.md for why it was unavoidable.
    """
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

    interventions_by_trial = defaultdict(list)
    for r in conn.execute("SELECT nct_id, name, target FROM interventions WHERE name IS NOT NULL"):
        # target is null until classify_target.py has run for this name; the
        # frontend treats null/missing the same as the literal string 'unknown'
        interventions_by_trial[r["nct_id"]].append({"name": r["name"], "target": r["target"]})

    lead_sponsor_by_trial = {}
    for r in conn.execute("SELECT nct_id, name FROM sponsors WHERE role = 'lead'"):
        # a trial can technically have >1 row tagged 'lead' if the registry data is
        # inconsistent - keep the first one encountered rather than erroring
        lead_sponsor_by_trial.setdefault(r["nct_id"], r["name"])

    trials = []
    for t in conn.execute(
        "SELECT nct_id, brief_title, overall_status, bucket_id, phase, start_date, stop_reason_category "
        "FROM trials"
    ).fetchall():
        year = t["start_date"][:4] if t["start_date"] and len(t["start_date"]) >= 4 and t["start_date"][:4].isdigit() else None
        trials.append(
            {
                "nct_id": t["nct_id"],
                "brief_title": t["brief_title"],
                "status": t["overall_status"] or "UNKNOWN",
                "bucket_id": t["bucket_id"] or "__unclassified_pending__",
                "bucket_label": bucket_label(t["bucket_id"]),
                "phase_raw": t["phase"],
                "phase_label": phase_label(t["phase"]),
                "start_year": year,
                "interventions": interventions_by_trial.get(t["nct_id"], []),
                "lead_sponsor": lead_sponsor_by_trial.get(t["nct_id"]),
                # null until the stop-reason classification pass runs (blocked on
                # taxonomy_discovery_prompt.md as of this export - see ASSUMPTIONS.md)
                "stop_reason_category": t["stop_reason_category"],
            }
        )

    # One row per outcome, with its latest endpoint_assessments.met (if any) -
    # "Endpoint outcomes by category" needs this joined against trials.bucket_id
    # client-side. endpoint_category will be null and outcomes_met will have no
    # rows with a non-null `met` until their respective classification/assessment
    # passes run - exported now anyway per outcomes_schema_and_dashboard.md's own
    # instruction to build the chart ahead of the data existing.
    outcomes_export = [
        {"nct_id": r["nct_id"], "endpoint_category": r["endpoint_category"], "met": r["met"]}
        for r in conn.execute(
            """
            SELECT o.nct_id, o.endpoint_category, latest.met
            FROM outcomes o
            LEFT JOIN (
                SELECT outcome_id, met,
                       ROW_NUMBER() OVER (PARTITION BY outcome_id ORDER BY assessed_at DESC) AS rn
                FROM endpoint_assessments
            ) latest ON latest.outcome_id = o.id AND latest.rn = 1
            """
        ).fetchall()
    ]

    return {
        "total_trials": total_trials,
        "last_sync": last_sync,
        "status_breakdown": status_breakdown,
        "outcomes": outcomes_export,
        "trials": trials,
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
