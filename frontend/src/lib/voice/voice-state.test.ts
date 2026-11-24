import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { initialVoice, voiceReducer, type VoiceAction, type VoiceState } from "./voice-state";

function fixture(name: string): Record<string, unknown>[] {
  return readFileSync(path.join(__dirname, "fixtures", `${name}.jsonl`), "utf-8")
    .split("\n")
    .filter(Boolean)
    .map((l) => JSON.parse(l));
}

const dc = (type: string, extra: Record<string, unknown> = {}, now = 0): VoiceAction => ({
  kind: "dc",
  event: { type, ...extra },
  now,
});
const run = (actions: VoiceAction[], from: VoiceState = initialVoice): VoiceState => actions.reduce(voiceReducer, from);
const live = () => run([{ kind: "local", action: "start" }, { kind: "local", action: "connected" }]);

describe("voiceReducer", () => {
  it("start → connecting → listening", () => {
    expect(voiceReducer(initialVoice, { kind: "local", action: "start" }).status).toBe("connecting");
    expect(live().status).toBe("listening");
  });

  it("barge-in during agent speech marks an interruption", () => {
    let s = run([dc("output_audio_buffer.started")], live());
    expect(s.status).toBe("agent_speaking");
    s = voiceReducer(s, dc("input_audio_buffer.speech_started", {}, 1234));
    expect(s.status).toBe("user_speaking");
    expect(s.interruptedAt).toBe(1234);
  });

  it("speech stopped moves to thinking", () => {
    expect(run([dc("input_audio_buffer.speech_started"), dc("input_audio_buffer.speech_stopped")], live()).status).toBe(
      "thinking",
    );
  });

  it("partial transcript accumulates and clears on completion", () => {
    let s = run(
      [
        dc("conversation.item.input_audio_transcription.delta", { delta: "What's the " }),
        dc("conversation.item.input_audio_transcription.delta", { delta: "refund" }),
      ],
      live(),
    );
    expect(s.partialUser).toBe("What's the refund");
    s = voiceReducer(s, dc("conversation.item.input_audio_transcription.completed", { transcript: "x" }));
    expect(s.partialUser).toBe("");
  });

  it("while the agent is consulting, the end of the holding line shows thinking, not listening", () => {
    const s = run(
      [dc("output_audio_buffer.started"), dc("response.function_call_arguments.done"), dc("output_audio_buffer.stopped")],
      live(),
    );
    expect(s.status).toBe("thinking");
    expect(voiceReducer(s, dc("output_audio_buffer.started")).status).toBe("agent_speaking");
  });

  it("failed and end", () => {
    const failed = voiceReducer(live(), { kind: "local", action: "failed", message: "Microphone blocked" });
    expect(failed).toMatchObject({ status: "error", message: "Microphone blocked" });
    expect(voiceReducer(live(), { kind: "local", action: "end" }).status).toBe("ended");
  });

  it("replays the recorded greeting and ends listening", () => {
    const s = run(
      fixture("greeting").map((e) => dc(e.type as string, e)),
      live(),
    );
    expect(s.status).toBe("listening");
  });

  it("replays the recorded interruption and notices it", () => {
    const s = fixture("interrupt").reduce<VoiceState>(
      (acc, e, i) => voiceReducer(acc, dc(e.type as string, e, i)),
      live(),
    );
    expect(s.interruptedAt).not.toBeNull();
  });

  it("events after the call ended are ignored", () => {
    const ended = voiceReducer(live(), { kind: "local", action: "end" });
    expect(voiceReducer(ended, dc("output_audio_buffer.started")).status).toBe("ended");
  });
});
