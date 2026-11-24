// What the voice UI shows, driven by local actions and the Realtime data-channel events (names from the spike).

export type VoiceStatus =
  | "idle"
  | "connecting"
  | "listening"
  | "user_speaking"
  | "thinking"
  | "agent_speaking"
  | "ended"
  | "error";

export interface VoiceState {
  status: VoiceStatus;
  partialUser: string;
  interruptedAt: number | null;
  consulting: boolean; // the agent is working on a consult_agent call
  message: string | null;
}

export type VoiceAction =
  | { kind: "local"; action: "start" | "connected" | "end"; message?: string }
  | { kind: "local"; action: "failed"; message: string }
  | { kind: "dc"; event: { type: string; [k: string]: unknown }; now?: number };

export const initialVoice: VoiceState = {
  status: "idle",
  partialUser: "",
  interruptedAt: null,
  consulting: false,
  message: null,
};

const LIVE: VoiceStatus[] = ["listening", "user_speaking", "thinking", "agent_speaking"];

export function isLive(status: VoiceStatus): boolean {
  return status === "connecting" || LIVE.includes(status);
}

export function voiceReducer(state: VoiceState, action: VoiceAction): VoiceState {
  if (action.kind === "local") {
    switch (action.action) {
      case "start":
        return { ...initialVoice, status: "connecting" };
      case "connected":
        return { ...state, status: "listening" };
      case "end":
        return { ...state, status: "ended", partialUser: "", consulting: false, message: action.message ?? null };
      case "failed":
        return { ...state, status: "error", partialUser: "", consulting: false, message: action.message ?? null };
    }
  }

  if (!LIVE.includes(state.status)) return state; // ignore stray events before connect / after the call
  const e = action.event;
  switch (e.type) {
    case "input_audio_buffer.speech_started":
      return {
        ...state,
        status: "user_speaking",
        partialUser: "",
        interruptedAt: state.status === "agent_speaking" ? (action.now ?? Date.now()) : state.interruptedAt,
      };
    case "input_audio_buffer.speech_stopped":
      return { ...state, status: "thinking" };
    case "conversation.item.input_audio_transcription.delta":
      return { ...state, partialUser: state.partialUser + String(e.delta ?? "") };
    case "conversation.item.input_audio_transcription.completed":
      return { ...state, partialUser: "" };
    case "response.function_call_arguments.done":
      return { ...state, consulting: true, status: state.status === "agent_speaking" ? state.status : "thinking" };
    case "output_audio_buffer.started":
      return { ...state, status: "agent_speaking", consulting: false };
    case "output_audio_buffer.stopped":
      if (state.status === "user_speaking") return state;
      return { ...state, status: state.consulting ? "thinking" : "listening" };
    default:
      return state;
  }
}
