/**
 * Typed API client for Entrix AI backend.
 */

import {
  ActionHistoryItem,
  ActionRequest,
  ActionResponse,
  DocumentSummary,
  IngestRequest,
  IngestResponse,
  LoginRequest,
  QueryRequest,
  QueryResponse,
  TokenResponse,
  UserInfo,
} from './types';

export const API_BASE = 'http://localhost:8000';

const TOKEN_KEY = 'entrix_access_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function removeToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

function getAuthHeaders(): HeadersInit {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detailMessage = `Request failed with status ${res.status} (${res.statusText})`;
    try {
      const errBody = await res.json();
      if (errBody) {
        if (typeof errBody.detail === 'string') {
          detailMessage = errBody.detail;
        } else if (Array.isArray(errBody.detail)) {
          // Pydantic validation errors
          detailMessage = errBody.detail
            .map((e: { msg?: string; loc?: (string | number)[] }) => {
              const field = e.loc ? e.loc.join('.') : '';
              return field ? `${field}: ${e.msg}` : e.msg;
            })
            .join('; ');
        } else if (errBody.error) {
          detailMessage = errBody.detail ? `${errBody.error}: ${errBody.detail}` : errBody.error;
        }
      }
    } catch {
      // Body was not JSON, fallback to default message
    }
    throw new Error(detailMessage);
  }
  return res.json() as Promise<T>;
}

/**
 * Authenticate user and receive access token.
 */
export async function login(req: LoginRequest): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  return handleResponse<TokenResponse>(res);
}

/**
 * Retrieve current authenticated user profile.
 */
export async function getMe(): Promise<UserInfo> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    method: 'GET',
    headers: getAuthHeaders(),
  });
  return handleResponse<UserInfo>(res);
}

/**
 * List permitted documents within the authenticated user's organization.
 */
export async function getDocuments(): Promise<DocumentSummary[]> {
  const res = await fetch(`${API_BASE}/documents`, {
    method: 'GET',
    headers: getAuthHeaders(),
  });
  return handleResponse<DocumentSummary[]>(res);
}

/**
 * Ingest a new document into the tenant store.
 */
export async function ingestDocument(req: IngestRequest): Promise<IngestResponse> {
  const res = await fetch(`${API_BASE}/documents/ingest`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(req),
  });
  return handleResponse<IngestResponse>(res);
}

/**
 * Submit an enterprise RAG query with sufficiency checking and tenant isolation.
 */
export async function submitQuery(req: QueryRequest): Promise<QueryResponse> {
  const res = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(req),
  });
  return handleResponse<QueryResponse>(res);
}

/**
 * Execute a policy-governed agentic action.
 */
export async function executeAction(req: ActionRequest): Promise<ActionResponse> {
  const res = await fetch(`${API_BASE}/actions/execute`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(req),
  });
  return handleResponse<ActionResponse>(res);
}

/**
 * Retrieve historical action execution audit records.
 */
export async function getActionHistory(): Promise<ActionHistoryItem[]> {
  const res = await fetch(`${API_BASE}/actions/history`, {
    method: 'GET',
    headers: getAuthHeaders(),
  });
  return handleResponse<ActionHistoryItem[]>(res);
}
