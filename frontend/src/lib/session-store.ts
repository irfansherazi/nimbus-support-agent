// Pure reducer from server events (and a few local actions) to what the chat, voice and drawer UIs render.
import type {
  AgentEvent,
  ChaosState,
  CustomerView,
  Escalation,
  Message,
  SessionView,
  Span,
  TraceView,
  UsageEvent,
} from "./events";

export type Channel = "chat" | "voice";
export type TurnStatus = "running" | "ok" | "escalated" | "failed";

export interface StepView {
  stepId: string;
  tool: string;
  label: string;
  kind: "tool" | "system";
  status: "running" | "done" | "failed";
  durationMs: number | null;
  error: string | null;
}

export interface GuardrailView {
  band: "high" | "grey" | "low" | "skipped";
  topScore: number | null;
  verify: "supported" | "unsupported" | "not_run";
}

export interface ErrorView {
  code: string;
  message: string;
  retryable: boolean;
}

export interface TurnView {
  turnId: string;
  channel: Channel;
  userText: string;
  answer: string;
  retracted: boolean;
  steps: StepView[];
  guardrail: GuardrailView | null;
  status: TurnStatus;
  trace: Span[] | null;
  usage: Pick<UsageEvent, "calls" | "turn_cost_usd" | "latency"> | null;
  interrupted: boolean;
  escalation: Escalation | null;
  error: ErrorView | null;
}

export interface SessionState {
  sessionId: string | null;
  customer: CustomerView | null;
  escalation: Escalation | null;
  turns: TurnView[];
  lastSeq: number;
  pendingRetry: { turnId: string; text: string } | null;
  error: ErrorView | null;
  usageTotal: number;
  needsRefresh: boolean;
  pendingVoiceUser: string | null;
  chaos: ChaosState;
}

export const NO_CHAOS: ChaosState = {
  llm_timeout_next: false,
  llm_429_next: false,
  llm_outage_next: false,
  tool_fail_next: null,
  tool_slow: null,
};

export type SessionAction =
  | { kind: "event"; event: AgentEvent }
  | { kind: "local_send"; turnId: string; text: string; retryOf?: string }
  | { kind: "hydrate"; session: SessionView; traces?: TraceView[] }
  | { kind: "local_error"; error: ErrorView }
  | { kind: "clear_error" }
  | { kind: "reset"; sessionId: string | null };

export function initialState(sessionId: string | null): SessionState {
  return {
    sessionId,
    customer: null,
    escalation: null,
    turns: [],
    lastSeq: 0,
    pendingRetry: null,
    error: null,
    usageTotal: 0,
    needsRefresh: false,
    pendingVoiceUser: null,
    chaos: NO_CHAOS,
  };
}

function newTurn(turnId: string, channel: Channel = "chat"): TurnView {
  return {
    turnId,
    channel,
    userText: "",
    answer: "",
    retracted: false,
    steps: [],
    guardrail: null,
    status: "running",
    trace: null,
    usage: null,
    interrupted: false,
    escalation: null,
    error: null,
  };
}

/** Return turns with `turnId` updated by `fn` (created at the end if missing). */
function updateTurn(turns: TurnView[], turnId: string, fn: (t: TurnView) => TurnView, channel?: Channel): TurnView[] {
  const i = turns.findIndex((t) => t.turnId === turnId);
  if (i === -1) return [...turns, fn(newTurn(turnId, channel))];
  const copy = turns.slice();
  copy[i] = fn(turns[i]);
  return copy;
}

function lastVoiceTurnId(turns: TurnView[]): string | null {
  for (let i = turns.length - 1; i >= 0; i--) if (turns[i].channel === "voice") return turns[i].turnId;
  return null;
}

function applyEvent(state: SessionState, e: AgentEvent): SessionState {
  const turnId = e.turn_id ?? "";
  switch (e.type) {
    case "turn_started": {
      const userText = e.channel === "voice" ? state.pendingVoiceUser ?? "" : undefined;
      return {
        ...state,
        pendingVoiceUser: e.channel === "voice" ? null : state.pendingVoiceUser,
        turns: updateTurn(
          state.turns,
          turnId,
          (t) => ({ ...t, channel: e.channel, status: "running", userText: userText ?? t.userText }),
          e.channel,
        ),
      };
    }
    case "token":
      return { ...state, turns: updateTurn(state.turns, turnId, (t) => ({ ...t, answer: t.answer + e.text })) };
    case "step_started":
    case "step_completed":
    case "step_failed": {
      const status = e.type === "step_started" ? "running" : e.type === "step_completed" ? "done" : "failed";
      const step: StepView = {
        stepId: e.step_id,
        tool: e.tool,
        label: e.label,
        kind: e.kind,
        status,
        durationMs: e.duration_ms ?? null,
        error: e.error ?? null,
      };
      return {
        ...state,
        turns: updateTurn(state.turns, turnId, (t) => {
          const i = t.steps.findIndex((s) => s.stepId === step.stepId);
          const steps = i === -1 ? [...t.steps, step] : t.steps.map((s, j) => (j === i ? step : s));
          return { ...t, steps };
        }),
      };
    }
    case "guardrail":
      return {
        ...state,
        turns: updateTurn(state.turns, turnId, (t) => ({
          ...t,
          guardrail: { band: e.band, topScore: e.top_score ?? null, verify: e.verify ?? "not_run" },
        })),
      };
    case "answer_retracted":
      return { ...state, turns: updateTurn(state.turns, turnId, (t) => ({ ...t, retracted: true, answer: "" })) };
    case "escalation": {
      const escalation = { ticket_id: e.ticket_id, reason: e.reason };
      return { ...state, escalation, turns: updateTurn(state.turns, turnId, (t) => ({ ...t, escalation })) };
    }
    case "transcript": {
      if (!e.final) return state;
      if (e.role === "user") return { ...state, pendingVoiceUser: e.text };
      const target = e.turn_id ?? lastVoiceTurnId(state.turns);
      if (!target) return state;
      return {
        ...state,
        turns: updateTurn(state.turns, target, (t) => ({ ...t, answer: e.text, interrupted: e.interrupted ?? false }), "voice"),
      };
    }
    case "trace":
      return { ...state, turns: updateTurn(state.turns, turnId, (t) => ({ ...t, trace: e.spans })) };
    case "usage":
      return {
        ...state,
        usageTotal: e.session_cost_usd,
        turns: updateTurn(state.turns, turnId, (t) => ({
          ...t,
          usage: { calls: e.calls, turn_cost_usd: e.turn_cost_usd, latency: e.latency },
        })),
      };
    case "error": {
      const error = { code: e.code, message: e.message, retryable: e.retryable };
      const turn = state.turns.find((t) => t.turnId === turnId);
      return {
        ...state,
        error,
        pendingRetry: e.retryable && turn?.userText ? { turnId, text: turn.userText } : state.pendingRetry,
        turns: turnId ? updateTurn(state.turns, turnId, (t) => ({ ...t, error })) : state.turns,
      };
    }
    case "turn_completed":
      return {
        ...state,
        needsRefresh: true,
        turns: updateTurn(state.turns, turnId, (t) => ({ ...t, status: e.status })),
      };
  }
}

function turnsFromMessages(messages: Message[], traces: TraceView[] = []): TurnView[] {
  const byTurn = new Map<string, TurnView>();
  for (const m of messages) {
    const t = byTurn.get(m.turn_id) ?? { ...newTurn(m.turn_id, m.channel), status: "ok" as TurnStatus };
    if (m.role === "user") t.userText = m.content;
    else {
      t.answer = m.content;
      t.interrupted = m.interrupted;
    }
    byTurn.set(m.turn_id, t);
  }
  for (const tr of traces) {
    const t = byTurn.get(tr.turn_id);
    if (!t) continue;
    t.trace = tr.spans;
    t.usage = {
      calls: tr.usage,
      turn_cost_usd: tr.usage.reduce((sum, u) => sum + (u.cost_usd ?? 0), 0),
      latency: tr.latency,
    };
    t.status = tr.status as TurnStatus;
  }
  return [...byTurn.values()];
}

export function sessionReducer(state: SessionState, action: SessionAction): SessionState {
  switch (action.kind) {
    case "event": {
      if (action.event.seq <= state.lastSeq) return state; // duplicate after a reconnect replay
      return { ...applyEvent(state, action.event), lastSeq: action.event.seq };
    }
    case "local_send": {
      const turns = (action.retryOf ? state.turns.filter((t) => t.turnId !== action.retryOf) : state.turns);
      return {
        ...state,
        error: null,
        pendingRetry: null,
        turns: updateTurn(turns, action.turnId, (t) => ({ ...t, userText: action.text })),
      };
    }
    case "hydrate": {
      const live = new Map(state.turns.map((t) => [t.turnId, t]));
      // Persisted text wins; live-only detail (steps, guardrail, trace, retraction) is kept.
      const persisted = turnsFromMessages(action.session.messages, action.traces).map((p) => {
        const t = live.get(p.turnId);
        if (!t) return p;
        return {
          ...t,
          userText: p.userText || t.userText,
          answer: p.answer || t.answer,
          interrupted: p.interrupted,
          trace: p.trace ?? t.trace,
          usage: p.usage ?? t.usage,
          status: t.status === "running" ? p.status : t.status,
        };
      });
      const known = new Set(persisted.map((t) => t.turnId));
      // Running turns aren't persisted yet; failed turns never are. Keep both so the user sees them.
      const running = state.turns.filter(
        (t) => !known.has(t.turnId) && (t.status === "running" || t.status === "failed"),
      );
      return {
        ...state,
        sessionId: action.session.session_id,
        customer: action.session.customer ?? null,
        escalation: action.session.escalation ?? null,
        turns: [...persisted, ...running],
        lastSeq: action.session.last_event_seq,
        chaos: action.session.chaos ?? NO_CHAOS,
        needsRefresh: false,
        usageTotal: Math.max(state.usageTotal, persisted.reduce((s, t) => s + (t.usage?.turn_cost_usd ?? 0), 0)),
      };
    }
    case "local_error":
      return { ...state, error: action.error };
    case "clear_error":
      return { ...state, error: null };
    case "reset":
      return initialState(action.sessionId);
  }
}
