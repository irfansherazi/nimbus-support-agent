// Thin typed client for the backend REST API.
import type { ChaosState, SessionView, Ticket, TraceView } from "./events";

// Same origin in production (the backend serves this app); .env.development points local dev at :8000.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Can't reach the support service. Check your connection and try again.");
  }
  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    let message = "Something went wrong. Please try again.";
    try {
      const body = await res.json();
      const detail = body?.detail;
      if (detail && typeof detail === "object" && "code" in detail) {
        code = String(detail.code);
        message = String(detail.message ?? message);
      }
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, code, message);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export async function createSession(): Promise<string> {
  return (await request<{ session_id: string }>("/api/sessions", { method: "POST" })).session_id;
}

/** null when the session no longer exists (e.g. the database was reset). */
export async function getSession(id: string): Promise<SessionView | null> {
  try {
    return await request<SessionView>(`/api/sessions/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export async function sendMessage(id: string, text: string): Promise<{ turnId: string }> {
  const r = await request<{ turn_id: string }>(`/api/sessions/${id}/messages`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  return { turnId: r.turn_id };
}

export const getTraces = (id: string) => request<TraceView[]>(`/api/sessions/${id}/traces`);
export const getTickets = (id: string) => request<Ticket[]>(`/api/sessions/${id}/tickets`);

export const setChaos = (id: string, state: Partial<ChaosState>) =>
  request<ChaosState>(`/api/sessions/${id}/chaos`, { method: "PUT", body: JSON.stringify(state) });

export const postMetric = (id: string, kind: "voice_e2e_ms", value: number, turnId?: string) =>
  request<void>(`/api/sessions/${id}/metrics`, {
    method: "POST",
    body: JSON.stringify({ kind, value, turn_id: turnId ?? null }),
  });
