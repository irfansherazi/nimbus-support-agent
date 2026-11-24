"use client";

import { useEffect, useRef, useState } from "react";
import { Composer } from "@/components/chat/Composer";
import { ErrorBanner } from "@/components/chat/ErrorBanner";
import { MessageList } from "@/components/chat/MessageList";
import { ObservabilityDrawer } from "@/components/drawer/ObservabilityDrawer";
import { StatusBar } from "@/components/header/StatusBar";
import { MicButton, VoicePanel } from "@/components/voice/VoiceControls";
import { useSession } from "@/hooks/useSession";
import { useVoice } from "@/hooks/useVoice";
import { isVoiceError, voiceErrorToHandle } from "@/lib/voice/voice-errors";

const DRAWER_KEY = "nimbus.drawerOpen";

export default function Home() {
  const { state, stream, send, retry, updateChaos, newConversation } = useSession();
  const voice = useVoice(state.sessionId);
  const [voiceNoticeHidden, setVoiceNoticeHidden] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [dismissedError, setDismissedError] = useState<unknown>(null);

  useEffect(() => {
    try {
      setDrawerOpen(window.localStorage.getItem(DRAWER_KEY) === "1");
    } catch {
      /* storage unavailable */
    }
  }, []);

  function toggleDrawer() {
    setDrawerOpen((open) => {
      try {
        window.localStorage.setItem(DRAWER_KEY, open ? "0" : "1");
      } catch {
        /* storage unavailable */
      }
      return !open;
    });
  }

  const busy = state.turns.some((t) => t.status === "running");
  const error =
    state.error && state.error !== dismissedError && !isVoiceError(state.error.code) ? state.error : null;

  // The server ends idle or over-long calls; close our side and say why in the voice panel. Each server error is
  // acted on once (by its event seq), so a stale one can't end the next call.
  const voiceEnd = voice.end;
  const handledVoiceErrorSeq = useRef(0);
  useEffect(() => {
    const voiceError = voiceErrorToHandle(state.error, handledVoiceErrorSeq.current);
    if (!voiceError) return;
    handledVoiceErrorSeq.current = voiceError.seq ?? handledVoiceErrorSeq.current;
    if (voice.live) void voiceEnd(voiceError.message);
  }, [state.error, voice.live, voiceEnd]);
  // A new conversation hangs up any call from the old one.
  useEffect(() => () => void voiceEnd(), [state.sessionId, voiceEnd]);

  return (
    <div className="flex h-dvh flex-col">
      <StatusBar
        state={state}
        stream={stream}
        drawerOpen={drawerOpen}
        onToggleDrawer={toggleDrawer}
        onNew={() => void newConversation()}
      />
      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 sm:px-6">
            <MessageList turns={state.turns} onSuggest={(t) => void send(t)} />
          </div>
          <div className="mx-auto w-full max-w-2xl space-y-2 px-4 pb-4 sm:px-1">
            {error && (
              <ErrorBanner
                error={error}
                canRetry={Boolean(state.pendingRetry)}
                onRetry={() => void retry()}
                onDismiss={() => setDismissedError(state.error)}
              />
            )}
            {!voiceNoticeHidden && (
              <VoicePanel
                state={voice.state}
                live={voice.live}
                muted={voice.muted}
                micBars={voice.micLevel}
                agentBars={voice.agentLevel}
                onToggleMute={voice.toggleMute}
                onEnd={() => void voice.end()}
                onDismiss={() => setVoiceNoticeHidden(true)}
              />
            )}
            <Composer
              onSend={(t) => void send(t)}
              busy={busy}
              voiceSlot={
                <MicButton
                  live={voice.live}
                  disabled={!state.sessionId}
                  onStart={() => {
                    setVoiceNoticeHidden(false);
                    void voice.start();
                  }}
                />
              }
            />
          </div>
        </main>
        {drawerOpen && (
          <aside
            id="observability"
            aria-label="Agent trace"
            className={
              // Side panel on wide screens; a bottom sheet over the chat on small ones.
              "fixed inset-x-0 bottom-0 z-20 h-[72dvh] rounded-t-2xl border-t border-line bg-surface shadow-[0_-8px_24px_rgb(26_31_46/0.12)] " +
              "lg:static lg:z-auto lg:h-auto lg:w-[380px] lg:shrink-0 lg:rounded-none lg:border-l lg:border-t-0 lg:shadow-none"
            }
          >
            <ObservabilityDrawer state={state} onClose={toggleDrawer} onChaosChange={updateChaos} />
          </aside>
        )}
      </div>
    </div>
  );
}
