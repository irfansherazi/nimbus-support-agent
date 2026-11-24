// Event and API types, aliased from the generated OpenAPI types (never hand-written).
import type { components } from "./api-types";

type S = components["schemas"];

export type TurnStartedEvent = S["TurnStartedEvent"];
export type TokenEvent = S["TokenEvent"];
export type StepEvent = S["StepEvent"];
export type GuardrailEvent = S["GuardrailEvent"];
export type EscalationEvent = S["EscalationEvent"];
export type AnswerRetractedEvent = S["AnswerRetractedEvent"];
export type TranscriptEvent = S["TranscriptEvent"];
export type TraceEvent = S["TraceEvent"];
export type UsageEvent = S["UsageEvent"];
export type ErrorEvent = S["ErrorEvent"];
export type TurnCompletedEvent = S["TurnCompletedEvent"];

export type AgentEvent =
  | TurnStartedEvent
  | TokenEvent
  | StepEvent
  | GuardrailEvent
  | EscalationEvent
  | AnswerRetractedEvent
  | TranscriptEvent
  | TraceEvent
  | UsageEvent
  | ErrorEvent
  | TurnCompletedEvent;

export type SessionView = S["SessionView"];
export type Message = S["Message"];
export type Span = S["Span"];
export type LLMUsage = S["LLMUsage"];
export type Latency = S["Latency"];
export type ChaosState = S["ChaosState"];
export type TraceView = S["TraceView"];
export type Ticket = S["Ticket"];
export type CustomerView = S["CustomerView"];
export type Escalation = S["Escalation"];

export const EVENT_TYPES: AgentEvent["type"][] = [
  "turn_started",
  "token",
  "step_started",
  "step_completed",
  "step_failed",
  "guardrail",
  "escalation",
  "answer_retracted",
  "transcript",
  "trace",
  "usage",
  "error",
  "turn_completed",
];

export type StreamStatus = "connecting" | "open" | "reconnecting";

/**
 * Subscribe to a session's event stream. The first connect resumes from `lastEventSeq` (from the hydrated
 * SessionView) via a query param; browser reconnects send Last-Event-ID themselves.
 */
export function subscribe(
  apiUrl: string,
  sessionId: string,
  lastEventSeq: number,
  onEvent: (e: AgentEvent) => void,
  onStatus: (s: StreamStatus) => void,
): () => void {
  const source = new EventSource(`${apiUrl}/api/sessions/${sessionId}/events?last_event_id=${lastEventSeq}`);
  onStatus("connecting");
  const handler = (msg: MessageEvent<string>) => {
    try {
      onEvent(JSON.parse(msg.data) as AgentEvent);
    } catch {
      // A malformed frame is dropped; the reducer's seq check keeps state consistent.
    }
  };
  for (const type of EVENT_TYPES) source.addEventListener(type, handler as EventListener);
  source.onopen = () => onStatus("open");
  source.onerror = () => onStatus("reconnecting");
  return () => source.close();
}
