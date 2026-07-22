"""ADscape ingestion CLI: verify | backfill | sync. See api_source.md for the spec."""

import json
import sys

from ct_gov_client import fetch_page, iter_studies
from db import connect, init_db

EXPECTED_BACKFILL_MIN = 3000
EXPECTED_BACKFILL_MAX = 4000

# schema.sql column -> dotted path under protocolSection (verified against a
# live response + /studies/metadata on 2026-07-22, see api_source.md)
FIELD_PATHS = {
    "nct_id": "identificationModule.nctId",
    "brief_title": "identificationModule.briefTitle",
    "official_title": "identificationModule.officialTitle",
    "overall_status": "statusModule.overallStatus",
    "study_type": "designModule.studyType",
    "start_date": "statusModule.startDateStruct.date",
    "primary_completion_date": "statusModule.primaryCompletionDateStruct.date",
    "completion_date": "statusModule.completionDateStruct.date",
    "why_stopped": "statusModule.whyStopped",
    "registry_last_updated": "statusModule.lastUpdatePostDateStruct.date",
    "enrollment_count": "designModule.enrollmentInfo.count",
    "enrollment_type": "designModule.enrollmentInfo.type",
    "sex": "eligibilityModule.sex",
    "minimum_age": "eligibilityModule.minimumAge",
    "maximum_age": "eligibilityModule.maximumAge",
}


def _dig(d, dotted_path):
    node = d
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def cmd_verify():
    """Make one live call and confirm api_source.md's field-mapping paths resolve."""
    payload = fetch_page(page_size=1)
    study = payload["studies"][0]
    ps = study["protocolSection"]

    print(f"NCT ID sampled: {_dig(ps, 'identificationModule.nctId')}\n")
    print("Field mapping check (column -> path -> resolved value):")
    missing = []
    for column, path in FIELD_PATHS.items():
        value = _dig(ps, path)
        status = "OK" if value is not None else "MISSING (may be optional on this trial)"
        print(f"  {column:28s} {path:45s} {status}")
        if value is None:
            missing.append(column)

    print(f"\ntop-level hasResults -> results_posted: {study.get('hasResults')}")
    lead = _dig(ps, "sponsorCollaboratorsModule.leadSponsor")
    print(f"leadSponsor: {lead}")
    collaborators = _dig(ps, "sponsorCollaboratorsModule.collaborators") or []
    print(f"collaborators: {len(collaborators)} found")
    interventions = _dig(ps, "armsInterventionsModule.interventions") or []
    print(f"interventions: {len(interventions)} found, types={[i.get('type') for i in interventions]}")
    outcomes = _dig(ps, "outcomesModule.primaryOutcomes") or []
    print(f"primaryOutcomes: {len(outcomes)} found")

    if missing:
        print(f"\n{len(missing)} field(s) not present on this sample trial (likely optional, not a mapping error).")
    else:
        print("\nAll mapped fields resolved on this sample trial.")


def map_study(study):
    ps = study["protocolSection"]

    phases = _dig(ps, "designModule.phases") or []
    conditions = _dig(ps, "conditionsModule.conditions") or []

    trial = {
        "nct_id": _dig(ps, "identificationModule.nctId"),
        "brief_title": _dig(ps, "identificationModule.briefTitle"),
        "official_title": _dig(ps, "identificationModule.officialTitle"),
        "phase": ",".join(phases) if phases else None,
        "overall_status": _dig(ps, "statusModule.overallStatus"),
        "study_type": _dig(ps, "designModule.studyType"),
        "start_date": _dig(ps, "statusModule.startDateStruct.date"),
        "primary_completion_date": _dig(ps, "statusModule.primaryCompletionDateStruct.date"),
        "completion_date": _dig(ps, "statusModule.completionDateStruct.date"),
        "why_stopped": _dig(ps, "statusModule.whyStopped"),
        "enrollment_count": _dig(ps, "designModule.enrollmentInfo.count"),
        "enrollment_type": _dig(ps, "designModule.enrollmentInfo.type"),
        "sex": _dig(ps, "eligibilityModule.sex"),
        "minimum_age": _dig(ps, "eligibilityModule.minimumAge"),
        "maximum_age": _dig(ps, "eligibilityModule.maximumAge"),
        "conditions": json.dumps(conditions),
        "results_posted": 1 if study.get("hasResults") else 0,
        "registry_last_updated": _dig(ps, "statusModule.lastUpdatePostDateStruct.date"),
    }

    sponsors = []
    lead = _dig(ps, "sponsorCollaboratorsModule.leadSponsor")
    if lead and lead.get("name"):
        sponsors.append({"name": lead["name"], "role": "lead", "sponsor_class": lead.get("class")})
    for collab in _dig(ps, "sponsorCollaboratorsModule.collaborators") or []:
        if collab.get("name"):
            sponsors.append({"name": collab["name"], "role": "collaborator", "sponsor_class": collab.get("class")})

    interventions = []
    for iv in _dig(ps, "armsInterventionsModule.interventions") or []:
        if not iv.get("name"):
            continue
        raw_type = iv.get("type")
        interventions.append({"name": iv["name"], "type": raw_type.lower() if raw_type else None})

    outcomes = []
    for outcome_type, key in (("primary", "primaryOutcomes"), ("secondary", "secondaryOutcomes")):
        for oc in _dig(ps, f"outcomesModule.{key}") or []:
            if not oc.get("measure"):
                continue
            outcomes.append(
                {
                    "outcome_type": outcome_type,
                    "measure": oc["measure"],
                    "description": oc.get("description"),
                    "time_frame": oc.get("timeFrame"),
                }
            )

    return {"trial": trial, "sponsors": sponsors, "interventions": interventions, "outcomes": outcomes}


def upsert_trial(conn, mapped):
    t = mapped["trial"]
    columns = list(t.keys())
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "nct_id")
    conn.execute(
        f"""
        INSERT INTO trials ({', '.join(columns)})
        VALUES ({', '.join('?' for _ in columns)})
        ON CONFLICT(nct_id) DO UPDATE SET {update_clause}
        """,
        [t[c] for c in columns],
    )

    nct_id = t["nct_id"]
    for table, rows in (
        ("sponsors", mapped["sponsors"]),
        ("interventions", mapped["interventions"]),
        ("outcomes", mapped["outcomes"]),
    ):
        conn.execute(f"DELETE FROM {table} WHERE nct_id = ?", (nct_id,))
        for row in rows:
            cols = list(row.keys())
            conn.execute(
                f"INSERT INTO {table} (nct_id, {', '.join(cols)}) VALUES (?, {', '.join('?' for _ in cols)})",
                [nct_id] + [row[c] for c in cols],
            )


def _run_ingest(conn, run_type, query_term=None):
    cur = conn.execute(
        "INSERT INTO pipeline_runs (run_type, status) VALUES (?, 'running')", (run_type,)
    )
    run_id = cur.lastrowid
    conn.commit()

    fetched = 0
    upserted = 0
    try:
        for study in iter_studies(query_term=query_term):
            fetched += 1
            mapped = map_study(study)
            upsert_trial(conn, mapped)
            upserted += 1
            if fetched % 500 == 0:
                conn.commit()
                print(f"  ... {fetched} records fetched")
        conn.commit()
        conn.execute(
            """UPDATE pipeline_runs SET status='success', completed_at=datetime('now'),
               records_fetched=?, records_upserted=? WHERE id=?""",
            (fetched, upserted, run_id),
        )
        conn.commit()
    except Exception as exc:
        conn.execute(
            """UPDATE pipeline_runs SET status='failed', completed_at=datetime('now'),
               records_fetched=?, records_upserted=?, error_message=? WHERE id=?""",
            (fetched, upserted, str(exc), run_id),
        )
        conn.commit()
        raise

    return fetched, upserted


def cmd_backfill():
    conn = init_db()
    print("Starting full backfill (query.cond=Alzheimer Disease)...")
    fetched, upserted = _run_ingest(conn, "backfill")
    print(f"Backfill complete: {fetched} fetched, {upserted} upserted.")
    if not (EXPECTED_BACKFILL_MIN <= fetched <= EXPECTED_BACKFILL_MAX):
        print(
            f"WARNING: fetched count {fetched} is outside the expected "
            f"{EXPECTED_BACKFILL_MIN}-{EXPECTED_BACKFILL_MAX} range - double-check the query."
        )


def cmd_sync():
    conn = init_db()
    row = conn.execute(
        """SELECT MAX(completed_at) AS last_date FROM pipeline_runs
           WHERE status='success' AND run_type IN ('backfill','sync')"""
    ).fetchone()
    if not row or not row["last_date"]:
        print("No prior successful backfill/sync found - run `python ingest.py backfill` first.")
        sys.exit(1)

    last_date = row["last_date"].split(" ")[0]  # datetime('now') -> 'YYYY-MM-DD HH:MM:SS'
    query_term = f"AREA[LastUpdatePostDate]RANGE[{last_date},MAX]"
    print(f"Starting incremental sync since {last_date}...")
    fetched, upserted = _run_ingest(conn, "sync", query_term=query_term)
    print(f"Sync complete: {fetched} fetched, {upserted} upserted.")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("verify", "backfill", "sync"):
        print("Usage: python ingest.py [verify|backfill|sync]")
        sys.exit(1)

    {"verify": cmd_verify, "backfill": cmd_backfill, "sync": cmd_sync}[sys.argv[1]]()
