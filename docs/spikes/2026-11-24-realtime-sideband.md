# Spike: OpenAI Realtime over WebRTC with a server-side ("sideband") connection

Date: 2026-11-24 · Model: `gpt-realtime` · Code: `spikes/realtime/` (throwaway) · Recordings: `backend/tests/fixtures/realtime/*.jsonl` (server side) and `frontend/src/lib/voice/fixtures/*.jsonl` (browser data channel), with per-token delta events removed.

## Decision

**The sideband flow works as designed (spec §8.1). No fallback is needed.** The browser never sees an API key, and every tool call is handled on our server.

## What was confirmed

| Question | Answer |
|---|---|
| Can our server relay the SDP offer? | Yes. `POST https://api.openai.com/v1/realtime/calls`, multipart fields `sdp` (offer) and `session` (JSON), server key as Bearer. **201**, body = SDP answer, `Location: /v1/realtime/calls/{call_id}`. |
| Can the server attach to that call? | Yes. `wss://api.openai.com/v1/realtime?call_id={call_id}` with the server key. It receives **every** event the browser's data channel receives, including `output_audio_buffer.*` and `conversation.item.truncated`. The socket closes when the call ends. |
| Tool calls | `response.function_call_arguments.done {response_id, item_id, call_id, name, arguments}`. `arguments` is a JSON string, sometimes with whitespace. Reply with `conversation.item.create {item: {type: "function_call_output", call_id, output}}`, then `response.create`. The output was spoken. |
| History injection | `conversation.item.create` with `{type: "message", role: "user", content: [{type: "input_text"}]}` and `role: "assistant"` with `output_text`. Both accepted; the model answered from them ("Dana, C-1001"). |
| User transcript | `conversation.item.input_audio_transcription.completed {item_id, transcript, usage}`. **It can arrive after the response, and after the tool call, for the same utterance.** Its `item_id` matches `input_audio_buffer.committed` and `speech_stopped`. |
| Assistant transcript | `response.output_audio_transcript.done {response_id, item_id, transcript}`. The text is what was *generated*, which can run ahead of what was *heard*. |
| Interruption | `input_audio_buffer.speech_started` → `output_audio_buffer.cleared {response_id}` → … → `conversation.item.truncated {item_id, audio_end_ms}`. `truncated` can arrive after `response.done`, and after the full transcript when generation finished before playback did. |
| Playback finished | `output_audio_buffer.started` and `output_audio_buffer.stopped {response_id}`. |
| Usage | `response.done.response.usage`: `input_tokens`, `output_tokens`, `input_token_details.{text_tokens, audio_tokens, cached_tokens}`, `output_token_details.{text_tokens, audio_tokens}`. Transcription usage comes on `...transcription.completed.usage`. |
| Holding line | With the instructions used, the model speaks a holding line and calls the tool **in the same response** (output = `message` + `function_call`). |
| Latency | Speech end → first audio of the holding line ≈ **0.3 s** (`speech_stopped` 201.329 → `output_audio_buffer.started` 201.647). |

## Problems seen, and their fixes (applied in Task 15)

1. **Wrong-language transcription.** Background noise was transcribed as Japanese ("そう、だから。") and Spanish, and the model then answered in Spanish ("Claro,"). → Set transcription `language: "en"` and input `noise_reduction: near_field`, and say "speak English only" in the instructions.
2. **Needless tool calls** for "Thank you." and fragments ("If you"). → The instructions say pleasantries are handled without tools, and to ask the customer to repeat unclear speech.
3. **Holding lines would pollute memory.** → Don't store assistant messages from a response that also made a tool call. Store only the answer that was actually heard.

## Design consequences for Task 15

- **Turn id** = `v_<user audio item_id>`, taken from `input_audio_buffer.committed`. Every response created after that commit belongs to the turn, including the follow-up response after the tool output. The late user transcript joins the same turn by its `item_id`.
- **When the assistant message is stored:**
  - on `output_audio_buffer.stopped`: heard in full;
  - on `conversation.item.truncated`: cut to `audio_end_ms` with `truncate_spoken`, marked interrupted.
- **Voice latency** is measured server-side from the sideband, `speech_stopped` → `output_audio_buffer.started`. No browser metric is needed.
