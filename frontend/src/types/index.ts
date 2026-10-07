export type Provenance = "detected" | "estimated" | "user_provided" | "unknown";
export type Tier = "budget" | "standard" | "premium" | "fitted";

export interface User { id: string; email: string; full_name: string; role: "admin" | "reviewer" | "sales"; is_active: boolean }
export interface Lead { id: string; name: string; email: string | null; phone: string | null; status: string; notes: string | null; preferences: Record<string, unknown>; is_sample: boolean; created_at: string }
export interface Project {
  id: string; title: string; status: string; category: string | null; location: string | null; area_sqm: number | null;
  property_type: string | null; request_text: string; current_quote_version: number; suspicious_input: boolean; lead: Lead;
  summary: { total?: number; currency?: string; confidence?: number; quote_version?: number; selected_tier?: string; flags?: number; mock_ai?: boolean };
  image_count: number; created_at: string; updated_at: string; pending_approval?: Approval | null;
}
export interface ImageMeta { id: string; filename: string; content_type: string; size_bytes: number; width: number; height: number }
export interface WorkflowEvent { id: string; run_id: string; node: string; status: "completed" | "failed" | "skipped" | "waiting"; summary: string; detail: Record<string, unknown>; latency_ms: number; created_at: string }
export interface WaitingFor { type: "clarification" | "approval"; questions?: string[]; approval_id?: string }
export interface Run { id: string; mode: string; status: "running" | "waiting" | "completed" | "failed"; waiting_for: WaitingFor | null; error: string | null; started_at: string; finished_at: string | null }
export interface WorkflowStatus { project_status: string; run: Run | null; events: WorkflowEvent[]; steps: { node: string; label: string }[]; labels: Record<string, string> }
export interface Attribute { value: string | null; provenance: Provenance; confidence: number }
export interface VisionAnalysis {
  room_type: Attribute; design_style: Attribute; flooring: Attribute; walls: Attribute; ceiling: Attribute; lighting: Attribute;
  dimensions: { width_m: number | null; length_m: number | null; height_m: number | null; area_sqm: number | null; provenance: Provenance; confidence: number; basis: string };
  furniture: string[]; fixtures: string[]; visible_issues: { description: string; severity: string; confidence: number }[];
  renovation_opportunities: string[]; overall_confidence: number; limitations: string[];
}
export interface CV { width: number; height: number; brightness: number; contrast: number; sharpness: number; palette: { hex: string; share: number }[]; color_temperature: string; quality_flags: string[]; detector: string; detections: { label: string; confidence: number }[] }
export interface VisionResponse { items: { image_id: string; model: string; analysis: VisionAnalysis; cv: CV }[]; summary: Record<string, unknown> }
export interface Requirements {
  project_type?: string | null; property_type?: string | null; rooms?: string[]; desired_style?: string | null; budget?: { amount: number; currency: string } | null;
  timeline_weeks?: number | null; area_sqm?: number | null; location?: string | null; priorities?: string[]; must_haves?: string[]; optional_items?: string[];
  constraints?: string[]; missing_information?: string[]; confidence?: number; provenance?: Record<string, Provenance>; vision_area_hint_sqm?: number;
}
export interface PricedLine { group: string; sku: string; name: string; tier: string; unit: string; quantity: number; unit_price: number; material_cost: number; labor_trade: string; labor_hours: number; labor_cost: number; line_total: number; optional: boolean; lead_days: number }
export interface Option {
  tier_label: string; lines: PricedLine[]; materials_subtotal: number; labor_subtotal: number; logistics: number; subtotal: number; contingency: number; tax: number; total: number; currency: string;
  warnings: string[]; timeline: { weeks: number; working_days: number; phases: { phase: string; days: number }[]; critical_material: string | null };
  achievable?: boolean; shortfall?: number; dropped_groups?: string[];
  params: { region: string; region_multiplier: number; complexity: string; contingency_pct: number; logistics_pct: number; tax_pct: number };
}
export interface Flag { code: string; severity: string; blocking: boolean; message: string }
export interface Evidence { doc_id: string; chunk_id: string; title: string; doc_type: string; score: number; snippet: string; metadata: Record<string, unknown>; flagged: string[] }
export interface QuotePayload {
  category: string; category_label: string; options: Partial<Record<Tier, Option>>;
  narrative: { summary: string }; assumptions: string[]; exclusions: string[]; risks: string[]; tradeoffs: string[];
  validation: { flags: Flag[]; confidence: number; approval_reasons: string[] }; evidence: Evidence[];
  negotiation: { budget?: number; achievable?: boolean; steps: { action: string; group: string; from_tier: string | null; to_tier: string | null; saving: number }[] } | null;
  recommendations: { title: string; detail: string; kind: string }[]; disclaimer: string; ai: { provider: string; mock: boolean; models: Record<string, string> };
}
export interface Quote { id: string; project_id: string; version: number; parent_version: number | null; reason: string; status: string; selected_tier: Tier; currency: string; total: number; confidence: number; created_at: string; payload: QuotePayload }
export type QuoteSummary = Omit<Quote, "payload"> & { summary: string | null };
export interface Approval { id: string; project_id: string; status: string; reasons: string[]; requested_at: string; decided_by: string | null; decision_note: string | null; project_title?: string; quote_version?: number; quote_total?: number; currency?: string; selected_tier?: string; confidence?: number }
export interface Message { id: string; role: "user" | "assistant" | "system"; content: string; meta: Record<string, unknown>; created_at: string }
export interface KnowledgeDoc { id: string; title: string; doc_type: string; source: string; metadata: Record<string, unknown>; chunk_count: number; embedder: string; is_sample: boolean }
export interface Material { sku: string; group: string; name: string; tier: string; unit: string; unit_price: number; currency: string; labor_trade: string; lead_days: number; available: boolean; is_sample: boolean }
export interface CrmSync { id: string; project_id: string; provider: string; status: string; external_id: string | null; attempts: number; last_error: string | null; idempotency_key: string; updated_at: string | null }
export interface Task { id: string; project_id: string | null; title: string; kind: string; status: string; due_at: string | null }
export interface Analytics {
  mock_ai: boolean; projects_by_status: Record<string, number>; quotes_by_status: Record<string, number>; approvals_by_status: Record<string, number>;
  crm_syncs_by_status: Record<string, number>; approved_value: number; approved_quotes: number; avg_quote_confidence: number; avg_workflow_seconds: number | null;
  llm: { model: string; tier: string; calls: number; avg_latency_ms: number; input_tokens: number; output_tokens: number; est_cost_usd: number | null; errors: number }[];
  feedback: { net: number; count: number };
}
export interface SystemConfig {
  env: string; version: string; mock_ai: boolean; llm: { provider: string; models: Record<string, string>; task_tiers: Record<string, string>; fallback_enabled: boolean };
  rag: { remote: boolean; collection: string; embedder: string }; crm: { provider: string }; storage: string; visualization: string; checkpointing: string; redis: boolean;
  approval: { always: boolean; total_threshold: number; min_confidence: number }; pricing_defaults: Record<string, number | string>;
  observability: { metrics: boolean; langfuse: boolean; otel: boolean }; configuration_problems: string[];
}
