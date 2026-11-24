"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { createLevelMeter, type LevelMeter } from "@/lib/voice/analyser";
import { connectVoice, hangUp, MicrophoneError, type VoiceConnection } from "@/lib/voice/rtc";
import { initialVoice, isLive, voiceReducer } from "@/lib/voice/voice-state";

/** Owns one voice call: mic, WebRTC, the remote <audio>, level meters and the UI state machine. */
export function useVoice(sessionId: string | null) {
  const [state, dispatch] = useReducer(voiceReducer, initialVoice);
  const conn = useRef<VoiceConnection | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const ctx = useRef<AudioContext | null>(null);
  const mic = useRef<LevelMeter | null>(null);
  const agent = useRef<LevelMeter | null>(null);

  const teardown = useCallback(() => {
    mic.current?.close();
    agent.current?.close();
    mic.current = agent.current = null;
    conn.current?.close();
    conn.current = null;
    if (audio.current) audio.current.srcObject = null;
    void ctx.current?.close();
    ctx.current = null;
  }, []);

  const start = useCallback(async () => {
    if (!sessionId || conn.current) return;
    dispatch({ kind: "local", action: "start" });
    // Create and resume the AudioContext inside the click handler (browsers require a user gesture).
    ctx.current = new AudioContext();
    void ctx.current.resume();
    try {
      const c = await connectVoice(sessionId, (event) => dispatch({ kind: "dc", event, now: Date.now() }));
      conn.current = c;
      mic.current = createLevelMeter(ctx.current, c.localStream);
      c.pc.onconnectionstatechange = () => {
        if (c.pc.connectionState === "failed" || c.pc.connectionState === "disconnected") {
          teardown();
          dispatch({ kind: "local", action: "failed", message: "Voice connection dropped. You can keep chatting." });
        }
      };
      const remote = await c.remoteStream;
      // The remote stream must also play through an <audio> element, or Chrome's analyser reads silence.
      audio.current ??= Object.assign(new Audio(), { autoplay: true });
      audio.current.srcObject = remote;
      if (ctx.current) agent.current = createLevelMeter(ctx.current, remote);
      dispatch({ kind: "local", action: "connected" });
    } catch (e) {
      teardown();
      const message =
        e instanceof MicrophoneError || e instanceof Error ? e.message : "Can't start voice. Try again.";
      dispatch({ kind: "local", action: "failed", message });
    }
  }, [sessionId, teardown]);

  const end = useCallback(
    async (message?: string) => {
      const id = sessionId;
      const wasLive = conn.current !== null;
      teardown();
      dispatch({ kind: "local", action: "end", message });
      if (id && wasLive) await hangUp(id);
    },
    [sessionId, teardown],
  );

  // Hang up on unmount (page close / navigation).
  useEffect(() => () => teardown(), [teardown]);

  const micLevel = useCallback(() => mic.current?.bars(24) ?? [], []);
  const agentLevel = useCallback(() => agent.current?.bars(24) ?? [], []);

  return { state, live: isLive(state.status), start, end, micLevel, agentLevel };
}
