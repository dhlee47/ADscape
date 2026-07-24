"""Condense staging/endpoint_source/*.json (raw CT.gov posted-results extracts)
into staging/endpoint_condensed/*.json - same underlying facts, but with the
verbose scale-description text and full timepoint history trimmed down to
just the decision-relevant row(s) + the reported analysis. Pure data
reduction (string/dict trimming), not classification - no LLM/API call here.
This exists only to make the per-trial reasoning pass (done directly in the
Claude Code session per endpoint_backfill_no_api.md) fit in context at scale;
it does not change any judgment, just what's included in the prompt-facing
JSON.

Also emits staging/endpoint_condensed/_chunks/chunk_NNN.json - the same
records grouped into fixed-size chunks (default 20 trials/chunk) so they can
be read in one shot per batch during the assessment pass.
"""

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC_DIR = Path(__file__).parent / "staging" / "endpoint_source"
OUT_DIR = Path(__file__).parent / "staging" / "endpoint_condensed"
CHUNK_DIR = OUT_DIR / "_chunks"
CHUNK_BYTES_CAP = 45_000

AVERAGE_RE = re.compile(r"\b(average|overall|total|endpoint|final)\b", re.I)


def pick_rows(data_rows):
    """Pick the decision-relevant subset of a measure's data rows."""
    classes = []
    for r in data_rows:
        c = r.get("class")
        if c not in classes:
            classes.append(c)

    if len(classes) <= 1:
        return data_rows

    avg_classes = [c for c in classes if c and AVERAGE_RE.search(c)]
    if avg_classes:
        keep = set(avg_classes)
        return [r for r in data_rows if r.get("class") in keep]

    last_class = classes[-1]
    return [r for r in data_rows if r.get("class") == last_class]


def condense_measure(m):
    rows = pick_rows(m.get("data", []))
    out_rows = []
    for r in rows:
        row = {"group": r.get("group"), "value": r.get("value")}
        if r.get("category"):
            row["category"] = r["category"]
        if r.get("spread"):
            row["spread"] = r["spread"]
        elif r.get("lower") or r.get("upper"):
            row["lower"] = r.get("lower")
            row["upper"] = r.get("upper")
        out_rows.append(row)

    analyses = []
    for a in m.get("analyses", []):
        analyses.append({
            "groups": a.get("groups"),
            "param_type": a.get("param_type"),
            "param_value": a.get("param_value"),
            "p_value": a.get("p_value"),
            "method": a.get("statistical_method"),
        })

    title = m.get("title") or ""

    return {
        "outcome_id": m.get("matched_outcome_id"),
        "title": title[:140],
        "type": m.get("type"),
        "param_type": m.get("param_type"),
        "unit": m.get("unit_of_measure"),
        "denoms": m.get("denoms", []),
        "rows": out_rows,
        "analyses": analyses,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(SRC_DIR.glob("*.json"))
    print(f"{len(files)} staged trial files found.")

    total_matched = 0
    total_unmatched = 0
    chunk = []
    chunk_bytes = 0
    chunk_idx = 1

    def flush():
        nonlocal chunk, chunk_bytes, chunk_idx
        if not chunk:
            return
        chunk_path = CHUNK_DIR / f"chunk_{chunk_idx:03d}.json"
        chunk_path.write_text(json.dumps(chunk, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        chunk = []
        chunk_bytes = 0
        chunk_idx += 1

    for fp in files:
        data = json.loads(fp.read_text(encoding="utf-8"))
        nct_id = data["nct_id"]

        matched = []
        unmatched = 0
        for m in data.get("posted_measures", []):
            if m.get("matched_outcome_id") is None:
                unmatched += 1
                continue
            matched.append(condense_measure(m))

        total_matched += len(matched)
        total_unmatched += unmatched

        record = {"nct_id": nct_id, "measures": matched, "unmatched_count": unmatched}

        out_path = OUT_DIR / f"{nct_id}.json"
        out_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

        record_bytes = len(json.dumps(record, ensure_ascii=False))
        if chunk and chunk_bytes + record_bytes > CHUNK_BYTES_CAP:
            flush()
        chunk.append(record)
        chunk_bytes += record_bytes
        if record_bytes > CHUNK_BYTES_CAP:
            flush()  # oversized trial gets its own chunk

    flush()

    print(f"Condensed {len(files)} trials -> {OUT_DIR}")
    print(f"{chunk_idx - 1} chunk file(s) in {CHUNK_DIR} (~{CHUNK_BYTES_CAP // 1000}KB/chunk cap)")
    print(f"Matched measures: {total_matched}, unmatched (skipped): {total_unmatched}")


if __name__ == "__main__":
    main()
