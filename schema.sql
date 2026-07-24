-- AD landscape tracker: trials schema (v0.1)
-- SQLite. Run with `PRAGMA foreign_keys = ON;` enabled at connection time -
-- SQLite does not enforce FKs by default.

PRAGMA foreign_keys = ON;

-- ============================================================
-- mechanism_buckets: mirrors taxonomy.json. Single source of truth
-- for valid bucket_id values everywhere else in the schema.
-- ============================================================
CREATE TABLE mechanism_buckets (
    bucket_id           TEXT PRIMARY KEY,      -- e.g. 'anti_amyloid_immunotherapy', 'unclassified'
    description          TEXT NOT NULL,
    pubmed_query          TEXT,
    trial_keywords        TEXT,                 -- JSON array, stored as text
    preclinical_terms     TEXT,                 -- JSON array, stored as text
    representative_agents TEXT,                 -- JSON array, stored as text
    added_at              TEXT NOT NULL DEFAULT (datetime('now')),
    source                TEXT NOT NULL DEFAULT 'seed' -- 'seed' or 'curator_proposal'
);

-- ============================================================
-- trials: one row per NCT ID. Registry fields + our own
-- classification metadata.
-- ============================================================
CREATE TABLE trials (
    nct_id                  TEXT PRIMARY KEY,
    brief_title              TEXT NOT NULL,
    official_title            TEXT,
    bucket_id                TEXT REFERENCES mechanism_buckets(bucket_id),
    classification_confidence REAL,             -- 0.0-1.0, from classify_prompt.md
    classification_rationale  TEXT,
    phase                     TEXT,              -- raw from API's `phases` array, comma-joined
                                                    -- e.g. 'PHASE2,PHASE3', 'PHASE1', 'NA'. No CHECK:
                                                    -- combinations vary and we store the registry's
                                                    -- own values as-is rather than inventing our own enum.
    overall_status            TEXT,              -- raw from API, e.g. 'RECRUITING', 'COMPLETED', 'TERMINATED'
    study_type                TEXT,               -- 'INTERVENTIONAL' / 'OBSERVATIONAL'
    start_date                TEXT,
    primary_completion_date   TEXT,
    completion_date           TEXT,
    why_stopped                TEXT,
    stop_reason_category         TEXT CHECK (stop_reason_category IN
                                    ('safety_toxicity','lack_of_efficacy','business_funding',
                                     'enrollment_futility','investigator_departure','operational_logistical',
                                     'other','not_applicable')),
                                  -- INFERRED from why_stopped via LLM (see classify_prompt.md).
                                  -- 'not_applicable' when why_stopped is null (trial never stopped
                                  -- early). This is what makes "targeting X failed because of
                                  -- toxicity" queries possible.
                                  -- investigator_departure/operational_logistical added after the
                                  -- taxonomy_discovery_prompt.md pass against the real why_stopped
                                  -- text found both as genuine recurring clusters not covered by the
                                  -- original 4 (see taxonomy_discovery_response.json for the full review).
    stop_reason_confidence         REAL,
    regulatory_status                 TEXT CHECK (regulatory_status IN
                                        ('approved','not_approved','pending_review','discontinued')),
                                      -- Deliberately NOT llm-inferred by default - the actual set of
                                      -- FDA-approved AD drugs is small and well-known (lecanemab,
                                      -- donanemab, and a handful of older symptomatic drugs). Hand-curate
                                      -- this one, same reasoning as the modality/target lookup tables:
                                      -- high-value, low-volume facts are worth getting exactly right
                                      -- rather than delegating to an LLM call.
    regulatory_status_source            TEXT NOT NULL DEFAULT 'human' CHECK (regulatory_status_source IN ('human','llm')),
    regulatory_status_updated_at          TEXT,
    enrollment_count           INTEGER,
    enrollment_type             TEXT,
                                 -- raw from API. Claude Code verified live that the actual value is
                                 -- 'ESTIMATED', not 'ANTICIPATED' as guessed here originally - defer
                                 -- to that finding, not this file's CHECK list.
    sex                          TEXT CHECK (sex IN ('ALL','MALE','FEMALE')),
    minimum_age                  TEXT,           -- kept as text: registry values like '55 Years'
    maximum_age                  TEXT,
    conditions                    TEXT,           -- free text / JSON array; see schema notes on eligibility criteria
    results_posted                 INTEGER NOT NULL DEFAULT 0 CHECK (results_posted IN (0,1)),
    registry_last_updated            TEXT,        -- last_update_post_date from CT.gov, NOT our ingestion time
    ingested_at                       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_trials_bucket ON trials(bucket_id);
CREATE INDEX idx_trials_status ON trials(overall_status);
CREATE INDEX idx_trials_phase ON trials(phase);

-- ============================================================
-- sponsors: one-to-many. Lead sponsor + any collaborators.
-- ============================================================
CREATE TABLE sponsors (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nct_id          TEXT NOT NULL REFERENCES trials(nct_id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    role              TEXT NOT NULL CHECK (role IN ('lead','collaborator')),
    sponsor_class      TEXT               -- raw from API's AgencyClass field (e.g. 'INDUSTRY', 'NIH', 'OTHER')
                                            -- no CHECK: verify exact enum values against a live response
                                            -- before hardcoding, they weren't independently confirmed here
);

CREATE INDEX idx_sponsors_nct ON sponsors(nct_id);
CREATE INDEX idx_sponsors_name ON sponsors(name);

-- ============================================================
-- interventions: one-to-many. Drug/device/biological tested.
-- This is what classify_prompt.md matches against
-- mechanism_buckets.representative_agents.
-- ============================================================
CREATE TABLE interventions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nct_id      TEXT NOT NULL REFERENCES trials(nct_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    type          TEXT,
                    -- raw from API's InterventionType. Do NOT constrain this to a guessed list -
                    -- Claude Code verified against the live API that this has more values than
                    -- assumed here (at least 11, including genetic/combination_product/
                    -- diagnostic_test). Defer to Claude Code's live-verified enum, not this file.
    modality       TEXT,
                    -- INFERRED, not from the raw API (same caveat as bucket_id/outcome_assessments -
                    -- keep provenance in mind). Suggested controlled vocabulary:
                    -- 'small_molecule', 'monoclonal_antibody', 'antisense_oligonucleotide',
                    -- 'gene_therapy', 'cell_therapy', 'vaccine_active_immunization', 'peptide',
                    -- 'other_biologic', 'device', 'behavioral', 'unknown'
                    -- No CHECK constraint yet - confirm this list covers what's actually in the
                    -- AD pipeline before locking it down; add more values as needed.
    modality_confidence REAL,
    modality_source      TEXT NOT NULL DEFAULT 'llm' CHECK (modality_source IN ('llm','lookup_table','human')),
    target                TEXT,
                            -- INFERRED. The specific druggable target (gene/protein symbol),
                            -- e.g. 'TREM2', 'BACE1', 'APOE', 'amyloid-beta', 'tau', 'NLRP3',
                            -- 'complement C1q/C3', 'GLP-1R', 'NMDA receptor', 'AChE'.
                            -- One level more specific than bucket_id (a bucket like
                            -- neuroinflammation_microglia_complement can span several distinct
                            -- targets - TREM2, NLRP3, complement - this field distinguishes them).
                            -- Free text, not a fixed enum: the set of real AD drug targets is
                            -- too open-ended to enumerate up front.
    target_confidence       REAL,
    target_source             TEXT NOT NULL DEFAULT 'llm' CHECK (target_source IN ('llm','lookup_table','human'))
);

CREATE INDEX idx_interventions_nct ON interventions(nct_id);
CREATE INDEX idx_interventions_name ON interventions(name);

-- ============================================================
-- outcomes: one-to-many. What the trial set out to measure -
-- from the registry, always available, never inferred.
-- ============================================================
CREATE TABLE outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nct_id         TEXT NOT NULL REFERENCES trials(nct_id) ON DELETE CASCADE,
    outcome_type    TEXT NOT NULL CHECK (outcome_type IN ('primary','secondary')),
    measure          TEXT NOT NULL,
    description       TEXT,
    time_frame         TEXT,
    endpoint_category    TEXT CHECK (endpoint_category IN
                            ('biomarker','cognitive_clinical','functional_adl','safety_tolerability',
                             'pharmacokinetics','neuropsychiatric_behavioral','quality_of_life_wellbeing',
                             'physical_function_motor','other')),
                          -- INFERRED from measure/description text. This is what makes
                          -- "met biomarker but not cognitive" queries possible - without this,
                          -- outcomes are just an undifferentiated list.
                          -- pharmacokinetics/neuropsychiatric_behavioral/quality_of_life_wellbeing/
                          -- physical_function_motor added after the taxonomy_discovery_prompt.md pass
                          -- against real outcomes.measure/description text (see
                          -- taxonomy_discovery_response.json). 'feasibility_engagement' (recruitment/
                          -- adherence/usability measures) was also proposed but deliberately rejected -
                          -- those aren't therapeutic-outcome endpoints in the sense this taxonomy exists
                          -- for (met-biomarker-vs-met-cognitive analysis), so they stay 'other'.
    endpoint_category_confidence REAL
);

CREATE INDEX idx_outcomes_nct ON outcomes(nct_id);

-- ============================================================
-- endpoint_assessments: per-OUTCOME assessment (not per-trial).
-- This is the finer-grained sibling of outcome_assessments -
-- keep both: outcome_assessments answers "did the trial succeed
-- overall," this answers "did THIS SPECIFIC endpoint succeed."
-- Same provenance/append-only discipline as outcome_assessments.
-- ============================================================
CREATE TABLE endpoint_assessments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id      INTEGER NOT NULL REFERENCES outcomes(id) ON DELETE CASCADE,
    met               TEXT NOT NULL CHECK (met IN ('met','not_met','mixed','unknown')),
    statistically_significant TEXT CHECK (statistically_significant IN
                                ('yes','no','not_reported','not_applicable')),
                              -- kept separate from `met` deliberately - a result can point the
                              -- right direction without reaching significance, or vice versa
                              -- be significant but clinically marginal. Don't collapse these.
    source_url          TEXT,
    confidence             REAL,
    rationale                 TEXT,
    assessed_by                TEXT NOT NULL DEFAULT 'llm' CHECK (assessed_by IN ('llm','human')),
    assessed_at                  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_endpoint_assessments_outcome ON endpoint_assessments(outcome_id);

-- ============================================================
-- outcome_assessments: what actually happened - inferred, with
-- provenance and confidence. Append-only: keep history rather
-- than overwriting when reassessed later.
-- ============================================================
CREATE TABLE outcome_assessments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nct_id         TEXT NOT NULL REFERENCES trials(nct_id) ON DELETE CASCADE,
    assessment       TEXT NOT NULL CHECK (assessment IN ('met_primary','failed_primary','mixed','unknown')),
    source_url        TEXT,                       -- linked publication, press release, etc.
    confidence          REAL,                      -- 0.0-1.0
    rationale             TEXT,
    assessed_by            TEXT NOT NULL DEFAULT 'llm' CHECK (assessed_by IN ('llm','human')),
    assessed_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_assessments_nct ON outcome_assessments(nct_id);

-- Convenience view: latest assessment per trial (since the table is append-only)
CREATE VIEW current_outcome_assessment AS
SELECT oa.*
FROM outcome_assessments oa
INNER JOIN (
    SELECT nct_id, MAX(assessed_at) AS max_assessed_at
    FROM outcome_assessments
    GROUP BY nct_id
) latest ON oa.nct_id = latest.nct_id AND oa.assessed_at = latest.max_assessed_at;

-- ============================================================
-- curator_watchlist: persists entities that appeared in
-- unclassified items but haven't yet cleared the curator
-- agent's recurrence threshold (see curator_agent_prompt.md).
-- Accumulates across weekly runs instead of resetting each time.
-- ============================================================
CREATE TABLE curator_watchlist (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entity          TEXT NOT NULL,                -- candidate drug/target/mechanism name
    item_count       INTEGER NOT NULL DEFAULT 1,
    first_seen_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at         TEXT NOT NULL DEFAULT (datetime('now')),
    note                    TEXT,
    UNIQUE(entity)
);

-- ============================================================
-- taxonomy_proposals: curator agent's weekly output when an
-- entity DOES clear the recurrence threshold. Human reviews
-- and either promotes into mechanism_buckets or rejects.
-- ============================================================
CREATE TABLE taxonomy_proposals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proposed_bucket_json  TEXT NOT NULL,          -- full candidate_bucket JSON from curator agent output
    supporting_items        TEXT,                  -- JSON array of nct_ids / item ids
    rationale                 TEXT,
    status                       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected')),
    proposed_at                    TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at                       TEXT
);

-- ============================================================
-- spot_check_log: manual, infrequent QA against Alzforum.
-- See spot_check_eval.md for process. Populated by hand, not
-- by any automated agent - do not scrape Alzforum content in.
-- ============================================================
CREATE TABLE spot_check_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nct_id          TEXT NOT NULL REFERENCES trials(nct_id) ON DELETE CASCADE,
    our_bucket_id     TEXT,
    alzforum_mechanism_note TEXT,                 -- brief paraphrase, not copied text
    bucket_agreement          TEXT CHECK (bucket_agreement IN ('match','partial','mismatch')),
    our_outcome_assessment      TEXT,
    alzforum_outcome_note         TEXT,            -- brief paraphrase, not copied text
    outcome_agreement               TEXT CHECK (outcome_agreement IN ('match','partial','mismatch')),
    notes                              TEXT,
    checked_at                           TEXT NOT NULL DEFAULT (datetime('now'))
);
