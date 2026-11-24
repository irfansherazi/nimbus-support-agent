import { describe, expect, it } from "vitest";
import { voiceErrorToHandle } from "./voice-errors";

describe("voiceErrorToHandle", () => {
  const limit = { code: "VOICE_LIMIT", message: "silence", retryable: false, seq: 12 };

  it("hands a new voice error to the call once", () => {
    expect(voiceErrorToHandle(limit, 0)).toBe(limit);
    expect(voiceErrorToHandle(limit, 12)).toBeNull(); // already handled: the next call must not be killed
  });

  it("ignores errors that aren't about voice", () => {
    expect(voiceErrorToHandle({ ...limit, code: "LLM_UNAVAILABLE" }, 0)).toBeNull();
    expect(voiceErrorToHandle(null, 0)).toBeNull();
  });

  it("local errors without a seq are never voice-handled", () => {
    expect(voiceErrorToHandle({ code: "VOICE_LIMIT", message: "x", retryable: false }, 0)).toBeNull();
  });
});
