import type {
  ApprovalRecord,
  ArchiveEvaluateResult,
  ArchiveInspectionResult,
  ChatCompletionResult,
  FunctionToolSpec,
  HealthzResponse,
  JsonObject,
  McpCapability,
  ModelSettings,
  ProjectEvaluationResult,
  QqAutomationSettings,
  QqEvent,
  ReferenceDocument,
  RetrievalResult,
  ReviewHistoryRecord,
  ReviewResponse,
  RunSessionResult,
  SessionState,
  ToolLogEntry
} from './types';

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('auth_token');
  if (token) return { authorization: `Bearer ${token}` };
  return {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...getAuthHeaders(),
    ...(init?.headers as Record<string, string> ?? {})
  };
  // Only set content-type for non-FormData bodies
  if (!(init?.body instanceof FormData)) {
    headers['content-type'] = 'application/json';
  }
  const response = await fetch(path, {
    ...init,
    headers
  });

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : response.statusText;
    throw new Error(`${response.status} ${detail}`);
  }
  return data as T;
}

export const api = {
  healthz: () => request<HealthzResponse>('/healthz'),
  getModelSettings: () => request<ModelSettings>('/model/settings'),
  updateModelSettings: (payload: { base_url?: string; model?: string; api_key?: string }) =>
    request<ModelSettings>('/model/settings', {
      method: 'PUT',
      body: JSON.stringify(payload)
    }),
  chat: (content: string) =>
    request<ChatCompletionResult>('/model/chat', {
      method: 'POST',
      body: JSON.stringify({ messages: [{ role: 'user', content }], temperature: 0.2 })
    }),
  createSession: (userId: string) =>
    request<SessionState>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId || null })
    }),
  getSession: (threadId: string) => request<SessionState>(`/sessions/${threadId}`),
  runSession: (payload: JsonObject, langGraph = false) =>
    request<RunSessionResult>(langGraph ? '/sessions/run-langgraph' : '/sessions/run', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  listTools: () => request<FunctionToolSpec[]>('/sessions/tools/list'),
  listPendingApprovals: () => request<ApprovalRecord[]>('/approvals/pending'),
  decideApproval: (approvalId: string, approved: boolean, reason: string) =>
    request<JsonObject>(`/approvals/${approvalId}/decide`, {
      method: 'POST',
      body: JSON.stringify({ approved_by: 'console-user', approved, reason })
    }),
  ingestRag: (payload: JsonObject) =>
    request<JsonObject>('/rag/ingest', { method: 'POST', body: JSON.stringify(payload) }),
  uploadRagDocument: (payload: JsonObject) =>
    request<JsonObject>('/rag/upload', { method: 'POST', body: JSON.stringify(payload) }),
  retrieveRag: (mode: 'text' | 'visual' | 'fused', query: string) =>
    request<RetrievalResult>(`/rag/retrieve/${mode}`, {
      method: 'POST',
      body: JSON.stringify({ query })
    }),
  listMcpCapabilities: () => request<McpCapability[]>('/mcp/capabilities'),
  callMcpTool: (payload: JsonObject) =>
    request<JsonObject>('/mcp/tools/call', { method: 'POST', body: JSON.stringify(payload) }),
  readMcpResource: (payload: JsonObject) =>
    request<JsonObject>('/mcp/resources/read', { method: 'POST', body: JSON.stringify(payload) }),
  getDefaultEvaluationRubric: () => request<JsonObject>('/evaluation/rubric/default'),
  evaluateProject: (payload: JsonObject) =>
    request<ProjectEvaluationResult>('/evaluation/analyze', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  postOneBotEvent: (payload: JsonObject) =>
    request<JsonObject>('/qq/onebot/webhook', { method: 'POST', body: JSON.stringify(payload) }),
  listQqEvents: () => request<QqEvent[]>('/qq/events'),
  getQqAutomationSettings: () => request<QqAutomationSettings>('/qq/automation/settings'),
  updateQqAutomationSettings: (payload: JsonObject) =>
    request<QqAutomationSettings>('/qq/automation/settings', {
      method: 'PUT',
      body: JSON.stringify(payload)
    }),
  downloadQqAttachment: (payload: JsonObject) =>
    request<JsonObject>('/qq/files/download', { method: 'POST', body: JSON.stringify(payload) }),
  inspectQqArchive: (path: string) =>
    request<ArchiveInspectionResult>('/qq/archive/inspect', {
      method: 'POST',
      body: JSON.stringify({ path })
    }),
  extractQqArchive: (payload: JsonObject) =>
    request<JsonObject>('/qq/archive/extract', { method: 'POST', body: JSON.stringify(payload) }),
  evaluateQqArchive: (payload: JsonObject) =>
    request<ArchiveEvaluateResult>('/qq/archive/evaluate', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  sendQqMessage: (payload: JsonObject) =>
    request<JsonObject>('/qq/send', { method: 'POST', body: JSON.stringify(payload) }),

  // Auth
  login: (username: string, password: string) =>
    request<JsonObject>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password })
    }),
  getMe: () => request<JsonObject>('/auth/me'),
  generateApiKey: () =>
    request<JsonObject>('/auth/api-keys', { method: 'POST' }),

  // Evaluation Workflow
  reviewProject: (payload: { source_url?: string; archive_path?: string; topic_title: string; topic_goal: string }) =>
    request<ReviewResponse>('/evaluation/review', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  getEvaluationHistory: () => request<ReviewHistoryRecord[]>('/evaluation/history'),
  deleteEvaluationHistory: (url: string) =>
    request<JsonObject>(`/evaluation/history/${encodeURIComponent(url)}`, { method: 'DELETE' }),
  getToolLogs: (limit = 100, sessionId?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (sessionId) params.set('session_id', sessionId);
    return request<ToolLogEntry[]>(`/evaluation/tool-logs?${params}`);
  },
  uploadReference: (file: File, description: string) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('description', description);
    return request<ReferenceDocument>('/evaluation/references/upload', {
      method: 'POST',
      body: formData,
      headers: {} // Let browser set multipart content-type
    });
  },
  listReferences: () =>
    request<{ references: ReferenceDocument[] }>('/evaluation/references'),
  deleteReference: (refId: string) =>
    request<JsonObject>(`/evaluation/references/${refId}`, { method: 'DELETE' })
};

export function parseJsonObject(value: string): JsonObject {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('请输入 JSON object');
  }
  return parsed as JsonObject;
}

// ---------------------------------------------------------------------------
// WebSocket helper for real-time evaluation events
// ---------------------------------------------------------------------------

export type WsEvent = {
  type: string;
  session_id?: string;
  tool?: string;
  target?: string;
  status?: string;
  content?: string;
  detail?: string;
  message?: string;
  timestamp?: string;
  [key: string]: unknown;
};

export type WsEventHandler = (event: WsEvent) => void;

/**
 * Connect to the evaluation WebSocket for real-time progress.
 *
 * @param sessionId - Optional session to subscribe to (null = all events)
 * @param onEvent - Callback for each received event
 * @returns Object with close() method to disconnect
 */
export function connectEvaluationWs(
  sessionId: string | null,
  onEvent: WsEventHandler,
): { close: () => void } {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const params = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
  const url = `${protocol}//${host}/ws/evaluation${params}`;

  let ws: WebSocket | null = new WebSocket(url);
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;

  function connect() {
    ws = new WebSocket(url);

    ws.onopen = () => {
      onEvent({ type: 'ws_connected' });
    };

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as WsEvent;
        onEvent(data);
      } catch {
        // Ignore unparseable messages
      }
    };

    ws.onclose = () => {
      if (!closed) {
        // Auto-reconnect after 3s
        reconnectTimer = setTimeout(() => {
          if (!closed) connect();
        }, 3000);
      }
    };

    ws.onerror = () => {
      ws?.close();
    };
  }

  connect();

  return {
    close() {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
      ws = null;
    },
  };
}
