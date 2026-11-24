import { describe, expect, it } from "vitest";
import { setMicEnabled } from "./rtc";

function fakeStream(n = 1) {
  const tracks = Array.from({ length: n }, () => ({ enabled: true }));
  return { stream: { getAudioTracks: () => tracks } as unknown as MediaStream, tracks };
}

describe("setMicEnabled", () => {
  it("mutes every audio track, so the call hears silence, and unmutes them again", () => {
    const { stream, tracks } = fakeStream(2);
    setMicEnabled(stream, false);
    expect(tracks.map((t) => t.enabled)).toEqual([false, false]);
    setMicEnabled(stream, true);
    expect(tracks.map((t) => t.enabled)).toEqual([true, true]);
  });
});
