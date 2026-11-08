/**
 * Protocol definitions for JSON-RPC 2.0 communication between
 * the VS Code TypeScript Extension and the Python QA Engine.
 * Matches Appendix D specification.
 */

export interface RPCRequest {
  jsonrpc: "2.0";
  id: string | number;
  method: string;
  params?: Record<string, unknown>;
}

export interface RPCResponse<T = unknown> {
  jsonrpc: "2.0";
  id: string | number | null;
  result?: T;
  error?: RPCError;
}

export interface RPCNotification {
  jsonrpc: "2.0";
  method: string;
  params?: Record<string, unknown>;
}

export interface RPCError {
  code: number;
  message: string;
  data?: unknown;
}

// Stage Names matching Engine Orchestrator
export type StageName =
  | "STAGE_0_SCOPE"
  | "STAGE_1_INTAKE"
  | "STAGE_2_ANALYSIS"
  | "STAGE_3_EXPLORATION"
  | "STAGE_4_TEST_DESIGN"
  | "STAGE_5_REVIEW_LOOP"
  | "STAGE_6_SCRIPT_GEN"
  | "STAGE_7_DRY_RUN"
  | "STAGE_8_EXECUTION"
  | "STAGE_9_INVESTIGATION"
  | "STAGE_10_SIGN_OFF"
  | "COMPLETED"
  | "CANCELLED"
  | "ERROR";

// Scope and Authorization Payload (Gate 0)
export interface ScopePayload {
  start_url: string;
  allowed_domains: string[];
  environment: "test" | "staging" | "production";
  credentials_ref?: string;
  destructive_actions?: "require_approval" | "allow" | "block";
  max_pages?: number;
  max_steps?: number;
  rate_limit_rps?: number;
  browsers?: string[];
  viewports?: string[];
  retries?: number;
  data_classification?: "synthetic" | "sanitized";
  authorized_attestation: boolean;
}

// Decision Card Types
export type CardType =
  | "scope_card"
  | "clarification_card"
  | "review_card"
  | "script_card"
  | "failure_card"
  | "report_card";

export interface CardShowPayload {
  card_type: CardType;
  run_id: string;
  data: Record<string, unknown>;
}

export interface StageUpdatePayload {
  run_id: string;
  stage: StageName;
  status: "active" | "finished" | "error";
  description: string;
}

export interface MessageStreamPayload {
  chunk: string;
  complete: boolean;
}

