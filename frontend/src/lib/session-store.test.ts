import { describe, expect, it } from "vitest";
import type { AgentEvent, SessionView } from "./events";
import { initialState, sessionReducer, type SessionState } from "./session-store";

let seq = 0;
function ev(e: Record<string, unknown>): { kind: "event"; event: AgentEvent } {
  seq += 1;
  return { kind: "event", event: { seq, turn_id: "t1", ...e } as unknown as AgentEvent };
}
function run(state: SessionState, ...actions: Parameters<typeof sessionReducer>[1][]): SessionState {
  return actions.reduce(sessionReducer, state);
}
const init = () => initialState("s1");

describe("sessionReducer", () => {
  it("ignores duplicate seq after reconnect", () => {
    const started = ev({ type: "turn_started", channel: "chat" });
    const token = ev({ type: "token", text: "Hi" });
    const s = run(init(), started, token, token);
    expect(s.turns[0].answer).toBe("Hi");
    expect(s.lastSeq).toBe(token.event.seq);
  });

  it("step chips transition started → completed", () => {
    const s = run(
      init(),
      ev({ type: "turn_started", channel: "chat" }),
      ev({ type: "step_started", step_id: "c1", tool: "verify_customer", label: "Verifying account & tier…", kind: "tool" }),
      ev({ type: "step_completed", step_id: "c1", tool: "verify_customer", label: "Verifying account & tier…", kind: "tool", duration_ms: 42 }),
    );
    expect(s.turns[0].steps).toEqual([
      { stepId: "c1", tool: "verify_customer", label: "Verifying account & tier…", kind: "tool", status: "done", durationMs: 42, error: null },
    ]);
  });

  it("failed steps keep their error code", () => {
    const s = run(
      init(),
      ev({ type: "step_started", step_id: "c1", tool: "issue_refund", label: "Issuing refund…", kind: "tool" }),
      ev({ type: "step_failed", step_id: "c1", tool: "issue_refund", label: "Issuing refund…", kind: "tool", error: "NOT_VERIFIED" }),
    );
    expect(s.turns[0].steps[0]).toMatchObject({ status: "failed", error: "NOT_VERIFIED" });
  });

  it("retraction replaces answer and marks turn; escalation sets session escalation", () => {
    const s = run(
      init(),
      ev({ type: "turn_started", channel: "chat" }),
      ev({ type: "token", text: "Refunds take 90 days." }),
      ev({ type: "answer_retracted", reason: "unsupported" }),
      ev({ type: "escalation", ticket_id: "T-101", reason: "unsupported_answer" }),
      ev({ type: "token", text: "I've passed it to a specialist." }),
    );
    expect(s.turns[0].retracted).toBe(true);
    expect(s.turns[0].answer).toBe("I've passed it to a specialist.");
    expect(s.escalation).toEqual({ ticket_id: "T-101", reason: "unsupported_answer" });
  });

  it("failed turn keeps user text for retry, and retry clears it", () => {
    let s = run(
      init(),
      { kind: "local_send", turnId: "t1", text: "hi" },
      ev({ type: "turn_started", channel: "chat" }),
      ev({ type: "error", code: "LLM_UNAVAILABLE", retryable: true, message: "down" }),
      ev({ type: "turn_completed", status: "failed" }),
    );
    expect(s.pendingRetry).toEqual({ turnId: "t1", text: "hi" });
    expect(s.error?.code).toBe("LLM_UNAVAILABLE");
    s = sessionReducer(s, { kind: "local_send", turnId: "t2", text: "hi", retryOf: "t1" });
    expect(s.pendingRetry).toBeNull();
    expect(s.error).toBeNull();
    expect(s.turns.map((t) => t.turnId)).toEqual(["t2"]);
  });

  it("events that arrive before the POST resolves still attach to the turn", () => {
    const s = run(init(), ev({ type: "turn_started", channel: "chat" }), { kind: "local_send", turnId: "t1", text: "hello" });
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0].userText).toBe("hello");
  });

  it("turn_completed requests a session refresh; hydrate clears it", () => {
    let s = run(init(), ev({ type: "turn_started", channel: "chat" }), ev({ type: "turn_completed", status: "ok" }));
    expect(s.needsRefresh).toBe(true);
    s = sessionReducer(s, { kind: "hydrate", session: view() });
    expect(s.needsRefresh).toBe(false);
  });

  it("hydrate maps stored messages into turns and keeps channel and interrupted flag", () => {
    const s = sessionReducer(init(), {
      kind: "hydrate",
      session: view({
        messages: [
          msg(1, "t1", "chat", "user", "hi"),
          msg(2, "t1", "chat", "assistant", "Hello!"),
          msg(3, "t2", "voice", "user", "what's my limit"),
          msg(4, "t2", "voice", "assistant", "Up to two hundred…", true),
        ],
        last_event_seq: 17,
      }),
    });
    expect(s.turns.map((t) => [t.turnId, t.channel, t.userText, t.answer, t.interrupted])).toEqual([
      ["t1", "chat", "hi", "Hello!", false],
      ["t2", "voice", "what's my limit", "Up to two hundred…", true],
    ]);
    expect(s.lastSeq).toBe(17);
  });

  it("hydrate keeps a running turn the server hasn't persisted yet", () => {
    let s = run(init(), { kind: "local_send", turnId: "t9", text: "pending" }, ev({ turn_id: "t9", type: "turn_started", channel: "chat" }));
    s = sessionReducer(s, { kind: "hydrate", session: view() });
    expect(s.turns.map((t) => t.turnId)).toEqual(["t9"]);
  });

  it("voice transcripts become the user text and spoken answer of the voice turn", () => {
    const s = run(
      init(),
      ev({ turn_id: null, type: "transcript", role: "user", text: "refund my invoice", final: true, interrupted: false, channel: "voice" }),
      ev({ turn_id: "v1", type: "turn_started", channel: "voice" }),
      ev({ turn_id: "v1", type: "turn_completed", status: "ok" }),
      ev({ turn_id: null, type: "transcript", role: "assistant", text: "Done, I refunded…", final: true, interrupted: true, channel: "voice" }),
    );
    expect(s.turns[0]).toMatchObject({ turnId: "v1", channel: "voice", userText: "refund my invoice", answer: "Done, I refunded…", interrupted: true });
  });

  it("usage updates the session total; guardrail keeps the latest verdict", () => {
    const s = run(
      init(),
      ev({ type: "guardrail", band: "grey", top_score: 0.38, verify: "not_run" }),
      ev({ type: "guardrail", band: "grey", top_score: 0.38, verify: "supported" }),
      ev({ type: "usage", calls: [], turn_cost_usd: 0.002, session_cost_usd: 0.031, latency: { total_ms: 900 } }),
    );
    expect(s.turns[0].guardrail).toEqual({ band: "grey", topScore: 0.38, verify: "supported" });
    expect(s.usageTotal).toBe(0.031);
  });

  it("reset starts a fresh session", () => {
    const s = run(init(), ev({ type: "turn_started", channel: "chat" }), { kind: "reset", sessionId: "s2" });
    expect(s).toEqual(initialState("s2"));
  });

  it("hydrate after a live turn keeps its steps, trace and guardrail", () => {
    let s = run(
      init(),
      { kind: "local_send", turnId: "t1", text: "hi" },
      ev({ type: "turn_started", channel: "chat" }),
      ev({ type: "step_started", step_id: "c1", tool: "verify_customer", label: "Verifying…", kind: "tool" }),
      ev({ type: "guardrail", band: "high", top_score: 0.8, verify: "not_run" }),
      ev({ type: "trace", spans: [] }),
      ev({ type: "turn_completed", status: "ok" }),
    );
    s = sessionReducer(s, { kind: "hydrate", session: view({ messages: [msg(1, "t1", "chat", "user", "hi"), msg(2, "t1", "chat", "assistant", "Hello")] }) });
    expect(s.turns[0]).toMatchObject({ answer: "Hello", status: "ok", trace: [] });
    expect(s.turns[0].steps).toHaveLength(1);
    expect(s.turns[0].guardrail?.band).toBe("high");
  });

  it("local_error shows a banner without touching turns", () => {
    const s = sessionReducer(init(), { kind: "local_error", error: { code: "RATE_LIMITED", message: "slow down", retryable: false } });
    expect(s.error?.code).toBe("RATE_LIMITED");
    expect(s.turns).toEqual([]);
  });

  it("hydrate keeps a failed turn (never persisted) so the user still sees what didn't go through", () => {
    let s = run(
      init(),
      { kind: "local_send", turnId: "t1", text: "hi" },
      ev({ type: "turn_started", channel: "chat" }),
      ev({ type: "error", code: "LLM_UNAVAILABLE", retryable: true, message: "down" }),
      ev({ type: "turn_completed", status: "failed" }),
    );
    s = sessionReducer(s, { kind: "hydrate", session: view() });
    expect(s.turns.map((t) => [t.turnId, t.userText, t.status])).toEqual([["t1", "hi", "failed"]]);
  });

  it("hydrate exposes the pending failure-simulation flags", () => {
    const s = sessionReducer(init(), { kind: "hydrate", session: view({ chaos: { ...NO_CHAOS, llm_outage_next: true } }) });
    expect(s.chaos.llm_outage_next).toBe(true);
  });

  it("clear_error removes the banner once the service is reachable again", () => {
    let s = sessionReducer(init(), { kind: "local_error", error: { code: "NETWORK", message: "x", retryable: false } });
    s = sessionReducer(s, { kind: "clear_error" });
    expect(s.error).toBeNull();
  });

  it("voice transcripts with turn ids build a turn even without an agent run (small talk)", () => {
    const s = run(
      init(),
      ev({ turn_id: "v_a", type: "transcript", role: "user", text: "Hi there.", final: true, interrupted: false, channel: "voice" }),
      ev({ turn_id: "v_a", type: "transcript", role: "assistant", text: "Hi! How can I help?", final: true, interrupted: false, channel: "voice" }),
    );
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0]).toMatchObject({ turnId: "v_a", channel: "voice", userText: "Hi there.", answer: "Hi! How can I help?", status: "ok" });
  });

  it("a late user transcript joins the agent turn that already started", () => {
    const s = run(
      init(),
      ev({ turn_id: "v_b", type: "turn_started", channel: "voice" }),
      ev({ turn_id: "v_b", type: "transcript", role: "user", text: "What's my refund limit?", final: true, interrupted: false, channel: "voice" }),
      ev({ turn_id: "v_b", type: "turn_completed", status: "ok" }),
      ev({ turn_id: "v_b", type: "transcript", role: "assistant", text: "Up to two hundred…", final: true, interrupted: true, channel: "voice" }),
    );
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0]).toMatchObject({ userText: "What's my refund limit?", answer: "Up to two hundred…", interrupted: true, status: "ok" });
  });

  it("a refresh never rewinds the event sequence (in-flight events would be dropped)", () => {
    // Review M7: hydrate runs after every turn while later events may still be in flight.
    let s = sessionReducer(init(), { kind: "hydrate", session: view({ last_event_seq: 5 }) });
    s = run(s, ev({ seq: 9, type: "turn_started", channel: "chat" }) as never);
    s = sessionReducer(s, { kind: "hydrate", session: view({ last_event_seq: 7 }) });
    expect(s.lastSeq).toBe(9);
  });

  it("a server restart (new bus epoch) resets the event sequence", () => {
    let s = sessionReducer(init(), { kind: "hydrate", session: view({ last_event_seq: 40 }) });
    s = sessionReducer(s, { kind: "hydrate", session: view({ last_event_seq: 2, bus_epoch: "e2" }) });
    expect(s.lastSeq).toBe(2);
  });

  it("errors remember the event seq they came from", () => {
    const s = run(init(), ev({ type: "error", code: "VOICE_LIMIT", retryable: false, message: "silence" }));
    expect(s.error?.seq).toBe(s.lastSeq);
  });
});

const NO_CHAOS = { llm_timeout_next: false, llm_429_next: false, llm_outage_next: false, tool_fail_next: null, tool_slow: null };

function view(over: Partial<SessionView> = {}): SessionView {
  return { session_id: "s1", customer: null, escalation: null, messages: [], last_event_seq: 0, bus_epoch: "e1", chaos: NO_CHAOS, ...over };
}

function msg(id: number, turn: string, channel: "chat" | "voice", role: "user" | "assistant", content: string, interrupted = false) {
  return { id, session_id: "s1", turn_id: turn, channel, role, content, interrupted, created_at: "2026-11-24T00:00:00Z" };
}
