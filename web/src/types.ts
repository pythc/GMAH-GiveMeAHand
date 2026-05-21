export type JsonObject = Record<string, unknown>;

export interface HealthzResponse {
  status: string;
  version: string;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
}

export interface ChatCompletionResult {
  model: string;
  content: string;
  finish_reason?: string | null;
  usage: JsonObject;
  raw_id?: string | null;
}

export interface ModelSettings {
  provider: string;
  base_url: string;
  model: string;
  api_key_configured: boolean;
}

export interface SessionState {
  thread_id: string;
  user_id?: string | null;
  messages: Array<{ role: string; content: string; created_at: string; metadata: JsonObject }>;
  tool_results: ToolResult[];
  pending_approvals: ApprovalRecord[];
  approval_status: string;
  updated_at: string;
}

export interface ToolResult {
  tool_name: string;
  call_id: string;
  status: string;
  output: JsonObject;
  error?: string | null;
  created_at: string;
}

export interface RunSessionResult {
  thread_id: string;
  trace_id: string;
  state: SessionState;
  tool_result?: ToolResult | null;
  approval_required: boolean;
  pending_approval?: ApprovalRecord | null;
  idempotent_replay: boolean;
}

export interface FunctionToolSpec {
  name: string;
  description: string;
  risk_level: string;
  approval_policy: string;
  idempotency_key_source?: string | null;
}

export interface ApprovalRecord {
  approval_id: string;
  tool_name: string;
  requested_by: string;
  approved_by?: string | null;
  approved?: boolean | null;
  reason?: string | null;
  call_id?: string | null;
  thread_id: string;
  trace_id: string;
  arguments: JsonObject;
  idempotency_key?: string | null;
  created_at: string;
  decided_at?: string | null;
}

export interface RetrievalEvidence {
  source_id: string;
  modality: string;
  score: number;
  content?: string | null;
  artifact_uri?: string | null;
  metadata: JsonObject;
}

export interface RetrievalResult {
  evidence: RetrievalEvidence[];
}

export interface McpCapability {
  server_name: string;
  name: string;
  primitive: string;
  description?: string | null;
  scopes: string[];
  metadata: JsonObject;
}

export interface CriterionAssessment {
  criterion_id: string;
  name: string;
  score: number;
  weight: number;
  evidence: string[];
  issues: string[];
  suggestions: string[];
}

export interface ProjectEvaluationResult {
  topic_title: string;
  overall_score: number;
  summary: string;
  coverage: Record<string, boolean>;
  criterion_assessments: CriterionAssessment[];
  artifact_assessments: JsonObject[];
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
  next_steps: string[];
}

export interface QqAttachment {
  type: string;
  mime: string;
  uri: string;
  name?: string | null;
  size_bytes?: number | null;
}

export interface QqEvent {
  channel: string;
  platform_protocol: string;
  conversation_id: string;
  message_id: string;
  sender: { user_id: string; display_name?: string | null; role?: string | null };
  content: { text?: string | null; attachments: QqAttachment[] };
  timestamp: string;
}

export interface QqBlacklistEntry {
  entry_type: 'user' | 'conversation';
  value: string;
  reason?: string | null;
}

export interface QqAutomationSettings {
  auto_evaluate_enabled: boolean;
  auto_reply_enabled: boolean;
  deep_review_enabled: boolean;
  progress_report_enabled: boolean;
  progress_report_level: 'minimal' | 'normal' | 'verbose';
  onebot_api_base_url: string;
  access_token_configured: boolean;
  topic_title: string;
  topic_goal: string;
  agent_system_prompt: string;
  blacklist: QqBlacklistEntry[];
}

export interface ArchiveInspectionResult {
  path: string;
  kind: string;
  safe: boolean;
  total_files: number;
  total_size_bytes: number;
  detected_artifacts: Record<string, number>;
  errors: string[];
  entries: JsonObject[];
}

export interface ArchiveEvaluateResult {
  extraction: JsonObject;
  evaluation?: ProjectEvaluationResult | null;
}

// ─── Evaluation Workflow Types ──────────────────────────────────────────────

export interface ReviewHistoryRecord {
  repo_url: string;
  topic_name: string;
  score: number | null;
  review: string;
  updated_at: string;
  tool_summary: string;
  review_count: number;
}

export interface ToolLogEntry {
  timestamp: string;
  kind: 'tool_call' | 'model_request' | 'model_response' | 'progress' | 'error' | 'system';
  session_id: string;
  tool: string | null;
  target: string | null;
  status: string | null;
  content: string | null;
  detail: string | null;
  arguments: JsonObject;
  metadata: JsonObject;
}

export interface ReferenceDocument {
  ref_id: string;
  filename: string;
  description: string;
  path: string;
  text_chunks: number;
  uploaded_at: string;
}

export interface ReviewResponse {
  session_id: string;
  evaluation?: ProjectEvaluationResult | null;
  llm_review?: string | null;
  history_record?: ReviewHistoryRecord | null;
  history_comparison?: string | null;
}
