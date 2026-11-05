// Shapes returned by the ClaimSense data API (api/src/claimsense_api/main.py).

export type Claim = {
  claim_id: string;
  policy_id: string;
  vehicle_vin: string;
  vehicle_year: number;
  vehicle_make: string;
  vehicle_model: string;
  vehicle_acv_usd: number;
  incident_date: string;
  incident_type: string;
  incident_description: string;
  damage_description: string;
  repair_estimate_usd: number | null;
  injuries_reported: boolean;
  police_report_filed: boolean;
  assigned_adjuster: string;
  prior_claims_12mo: number;
  fraud_risk_score: number;
  claim_status: string;
  created_at: string;
};

export type Policy = {
  policy_id: string;
  coverage_type: string;
  collision_coverage: boolean;
  comprehensive_coverage: boolean;
  collision_deductible_usd: number | null;
  comprehensive_deductible_usd: number | null;
  vehicle_acv_usd: number;
  policy_status: string;
  policy_start: string;
  policy_end: string;
};

export type DocumentRow = {
  document_id: string;
  document_type: string;
  description: string;
  upload_date: string;
  page_count: number;
  ocr_status: string;
};

export type DocumentFull = DocumentRow & { claim_id: string; ocr_text: string | null };

export type Clause = { clause_id: string; title: string; text: string; score: number };

export type Outcome = "APPROVE" | "FLAG" | "ROUTE" | "DENY";

export type Signal = { outcome: Outcome; clause: string; reason: string };
export type Gap = { clause: string; reason: string };

/** One ClaimSense draft note with its assessment (GET /api/v1/claims/{id}/notes). */
export type Note = {
  note_id: number;
  claim_id: string;
  on_behalf_of: string;
  outcome: Outcome;
  summary: string;
  cited_clauses: string[];
  deny_reason: string | null;
  status: string;                       // draft_pending_confirmation | confirmed | rejected
  author: string;
  created_at: string;
  reviewed_by: string | null;
  review_reason: string | null;
  reviewed_at: string | null;
  run_id: string;
  decision_source: "model" | "deterministic_fallback" | "agent_failure";
  claim_status_at_run: string | null;   // the claim's status when the run started (null on older notes)
  code_facts: {
    facts: Record<string, unknown> & {
      in_force_at_loss: boolean;
      net_payable_if_covered_usd: number | null;
      deductible_usd: number | null;
      repair_to_acv_ratio: number | null;
    };
    signals: Signal[];
    documentation_gaps: Gap[];
    precedence?: Outcome[];             // since 2026-11-04
    provisional_precedence?: Outcome[]; // older notes
  };
  agent_outputs: Record<string, unknown> & { draft_problems?: string[]; usage?: Usage };
  models: Record<string, string>;
};

/** Model tokens and cost of one run, per agent and in total (empty for the mock brain). */
export type Usage = {
  agents: Record<string, { model: string; requests: number; input_tokens: number; output_tokens: number; cost_usd: number | null }>;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
};

/** What the runner returns for one run (POST /runs on the runner service). */
export type RunResult = {
  run_id: string;
  claim_id: string;
  status: "written" | "replayed" | "failed";
  outcome: Outcome | null;
  decision_source: string | null;
  cited_clauses: string[];
  problems: string[];
  note_id: number | null;
  brain: string;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
};
