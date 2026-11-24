// WebRTC connection to the Realtime call. The SDP offer goes to OUR backend, which creates the call with its own
// key (the browser never holds an OpenAI key). Audio flows browser <-> OpenAI; events arrive on the data channel.
import { API_URL, ApiError } from "@/lib/api";

export interface VoiceConnection {
  pc: RTCPeerConnection;
  localStream: MediaStream;
  remoteStream: Promise<MediaStream>;
  close: () => void;
}

export class MicrophoneError extends Error {}

export async function connectVoice(
  sessionId: string,
  onEvent: (event: { type: string; [k: string]: unknown }) => void,
): Promise<VoiceConnection> {
  let localStream: MediaStream;
  try {
    localStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch {
    throw new MicrophoneError("Microphone access is blocked — allow it in the browser to use voice.");
  }

  const pc = new RTCPeerConnection();
  const remoteStream = new Promise<MediaStream>((resolve) => {
    pc.ontrack = (e) => resolve(e.streams[0]);
  });
  localStream.getTracks().forEach((t) => pc.addTrack(t, localStream));
  const dc = pc.createDataChannel("oai-events");
  dc.onmessage = (m) => {
    try {
      onEvent(JSON.parse(m.data));
    } catch {
      /* ignore malformed frames */
    }
  };

  const close = () => {
    dc.close();
    pc.close();
    localStream.getTracks().forEach((t) => t.stop());
  };

  try {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const res = await fetch(`${API_URL}/api/voice/calls?session_id=${sessionId}`, {
      method: "POST",
      body: offer.sdp,
      headers: { "Content-Type": "application/sdp" },
    });
    if (res.status !== 201) {
      let code = `HTTP_${res.status}`;
      let message = "Voice is unavailable right now. You can keep chatting.";
      try {
        const detail = (await res.json())?.detail;
        if (detail?.code) {
          code = detail.code;
          message = detail.message ?? message;
        }
      } catch {
        /* non-JSON */
      }
      throw new ApiError(res.status, code, message);
    }
    await pc.setRemoteDescription({ type: "answer", sdp: await res.text() });
  } catch (e) {
    close();
    throw e instanceof ApiError ? e : new ApiError(0, "NETWORK", "Can't start voice. Check your connection.");
  }

  return { pc, localStream, remoteStream, close };
}

/** Mute keeps the call open but sends silence, so the assistant neither hears nor gets interrupted. */
export function setMicEnabled(stream: MediaStream, enabled: boolean): void {
  stream.getAudioTracks().forEach((t) => {
    t.enabled = enabled;
  });
}

export async function hangUp(sessionId: string): Promise<void> {
  try {
    await fetch(`${API_URL}/api/voice/calls/${sessionId}`, { method: "DELETE" });
  } catch {
    /* the server ends idle calls on its own */
  }
}
