/**
 * TypeScript types matching Entrix AI backend API schemas.
 */

// ── Auth ──────────────────────────────────────────────────────────────────

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  username: string;
  organization_id: string;
  organization_name: string;
  role: string;
}

export interface UserInfo {
  id: string;
  username: string;
  email: string;
  role: string;
  organization_id: string;
  organization_name: string;
}

// ── Documents ────────────────────────────────────────────────────────────

export interface DocumentSummary {
  id: string;
  title: string;
  source_id?: string | null;
  version: number;
  chunk_count: number;
  created_at: string;
}

export interface IngestRequest {
  title: string;
  content: string;
  source_id?: string | null;
  allowed_roles?: string[];
}

export interface IngestResponse {
  document_id: string;
  title: string;
  chunk_count: number;
  message: string;
}

// ── Evidence & Retrieval ─────────────────────────────────────────────────

export interface EvidenceItem {
  evidence_id: string;
  document_id: string;
  document_title: string;
  chunk_index: number;
  text: string;
  score: number;
  source_id?: string | null;
}

export enum SufficiencyDecision {
  SUFFICIENT = 'sufficient',
  INSUFFICIENT = 'insufficient',
  RETRY = 'retry',
  ABSTAIN = 'abstain',
}

export interface SufficiencyAssessment {
  decision: SufficiencyDecision | string;
  coverage_score: number;
  supporting_evidence_ids: string[];
  missing_information: string[];
  contradictions: string[];
  confidence: number;
  rationale: string;
}

// ── Query / RAG ──────────────────────────────────────────────────────────

export interface Citation {
  document_id: string;
  document_title: string;
  chunk_index: number;
  source_id?: string | null;
  excerpt: string;
}

export interface QueryRequest {
  query: string;
  top_k?: number;
  estimator?: string | null;
}

export interface QueryResponse {
  query_id: string;
  query: string;
  answer?: string | null;
  abstained: boolean;
  abstention_reason?: string | null;
  citations: Citation[];
  evidence: EvidenceItem[];
  sufficiency?: SufficiencyAssessment | null;
  retry_attempted: boolean;
  latency_ms: number;
}

// ── Actions ──────────────────────────────────────────────────────────────

export enum ActionStatus {
  PROPOSED = 'proposed',
  AUTHORIZED = 'authorized',
  EXECUTED = 'executed',
  REJECTED = 'rejected',
  FAILED = 'failed',
}

export interface ActionRequest {
  action_name: string;
  parameters: Record<string, unknown>;
  idempotency_key?: string | null;
}

export interface ActionResponse {
  execution_id: string;
  action_name: string;
  status: ActionStatus | string;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
  correlation_id: string;
  policy_version?: number | null;
}

export interface ActionHistoryItem {
  id: string;
  action_name: string;
  status: string;
  parameters: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at: string;
  executed_at?: string | null;
}

// ── System & Errors ──────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  version: string;
}

export interface ErrorResponse {
  error: string;
  detail?: string | null;
  correlation_id?: string | null;
}
