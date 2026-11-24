import type { ErrorView } from "@/lib/session-store";

const VOICE_CODES = new Set(["VOICE_LIMIT", "VOICE_DROPPED"]);

export function isVoiceError(code?: string): boolean {
  return code !== undefined && VOICE_CODES.has(code);
}

/** The server-sent voice error to act on (end the call), or null. Each error is handled once, by its event seq,
 *  so a stale error left in session state can't kill the next call. */
export function voiceErrorToHandle(error: ErrorView | null, handledSeq: number): ErrorView | null {
  if (!error || !isVoiceError(error.code) || error.seq === undefined) return null;
  return error.seq > handledSeq ? error : null;
}
