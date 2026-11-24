"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { API_URL, ApiError, createSession, getSession, getTraces, sendMessage } from "@/lib/api";
import { subscribe, type StreamStatus } from "@/lib/events";
import { initialState, sessionReducer } from "@/lib/session-store";

const STORAGE_KEY = "nimbus.sessionId";

function readStoredId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeId(id: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // private mode / blocked storage: the session simply won't survive a reload
  }
}

/** Owns the conversation: session bootstrap, hydration, the live event stream, send/retry/new conversation. */
export function useSession() {
  const [state, dispatch] = useReducer(sessionReducer, initialState(null));
  const [stream, setStream] = useState<StreamStatus>("connecting");
  const [ready, setReady] = useState(false);
  const unsubscribe = useRef<(() => void) | null>(null);
  const sessionRef = useRef<string | null>(null);

  const hydrate = useCallback(async (id: string, withTraces = false) => {
    const [view, traces] = await Promise.all([getSession(id), withTraces ? getTraces(id).catch(() => []) : undefined]);
    if (view) dispatch({ kind: "hydrate", session: view, traces });
    return view;
  }, []);

  const connect = useCallback(
    async (id: string) => {
      unsubscribe.current?.();
      sessionRef.current = id;
      const view = await hydrate(id, true);
      if (!view) return false;
      let wasDown = false;
      unsubscribe.current = subscribe(
        API_URL,
        id,
        view.last_event_seq,
        (event) => dispatch({ kind: "event", event }),
        (status) => {
          setStream(status);
          if (status === "reconnecting") wasDown = true;
          if (status === "open" && wasDown) {
            wasDown = false;
            void hydrate(id); // the backend may have restarted: realign seq and history
          }
        },
      );
      setReady(true);
      return true;
    },
    [hydrate],
  );

  const startNew = useCallback(async () => {
    const id = await createSession();
    storeId(id);
    dispatch({ kind: "reset", sessionId: id });
    await connect(id);
  }, [connect]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const boot = async (attempt: number) => {
      if (cancelled) return;
      try {
        const stored = readStoredId();
        if (!(stored && (await connect(stored))) && !cancelled) await startNew(); // none yet, or gone (DB reset)
        if (attempt > 0) dispatch({ kind: "clear_error" });
      } catch (e) {
        // The service may be starting up or briefly unreachable: keep trying instead of giving up.
        const message = e instanceof ApiError ? e.message : "Can't reach the support service.";
        dispatch({ kind: "local_error", error: { code: "NETWORK", message, retryable: false } });
        timer = setTimeout(() => void boot(attempt + 1), Math.min(2000 * (attempt + 1), 10000));
      }
    };
    void boot(0);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      unsubscribe.current?.();
    };
  }, [connect, startNew]);

  // After each turn, pull the session again (verified customer, escalation, persisted text).
  useEffect(() => {
    if (state.needsRefresh && sessionRef.current) void hydrate(sessionRef.current);
  }, [state.needsRefresh, hydrate]);

  const send = useCallback(async (text: string, retryOf?: string) => {
    const id = sessionRef.current;
    if (!text.trim()) return;
    if (!id) {
      const error = { code: "NETWORK", message: "Can't reach the support service.", retryable: false };
      dispatch({ kind: "local_error", error });
      return;
    }
    try {
      const { turnId } = await sendMessage(id, text.trim());
      dispatch({ kind: "local_send", turnId, text: text.trim(), retryOf });
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "NETWORK", "Message not sent. Try again.");
      dispatch({ kind: "local_error", error: { code: err.code, message: err.message, retryable: false } });
    }
  }, []);

  const retry = useCallback(async () => {
    if (state.pendingRetry) await send(state.pendingRetry.text, state.pendingRetry.turnId);
  }, [state.pendingRetry, send]);

  return { state, stream, ready, send, retry, newConversation: startNew };
}
