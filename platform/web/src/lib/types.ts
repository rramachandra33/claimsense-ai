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
