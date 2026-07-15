/* The LiveKit half of the call panel, split into its own chunk.
 *
 * livekit-client + the components library are ~600kB — most visits to the console
 * are an approver working the queue, never opening a call. This module is lazily
 * imported the moment a call actually starts, so the console itself loads light.
 */
import {
  BarVisualizer,
  DisconnectButton,
  LiveKitRoom,
  RoomAudioRenderer,
  VoiceAssistantControlBar,
  useDataChannel,
  useTranscriptions,
  useVoiceAssistant,
} from "@livekit/components-react";
import { useEffect, useRef, useState } from "react";
import type { TokenResp } from "../api";
import { Icon } from "./Badge";
import { Latency, type Sample } from "./Latency";
import { MicStatus } from "./MicStatus";

const AGENT_STATE_COPY: Record<string, string> = {
  connecting: "Connecting…",
  initializing: "Waking the agent…",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  disconnected: "Agent offline — is the voice worker running?",
};

/** Rendered inside the room, so the hooks have a room to read from. */
function CallStage({ onHold }: { onHold: boolean }) {
  const { state, audioTrack, agent } = useVoiceAssistant();
  const transcriptions = useTranscriptions();
  const [samples, setSamples] = useState<Sample[]>([]);
  const feed = useRef<HTMLDivElement>(null);

  // The worker publishes one message per completed turn on this topic — so the numbers
  // live next to the conversation instead of being buried in the worker's log stream.
  useDataChannel("latency", (msg) => {
    try {
      setSamples((prev) => [...prev, JSON.parse(new TextDecoder().decode(msg.payload)) as Sample]);
    } catch {
      /* a malformed telemetry frame must never break the call */
    }
  });

  // Keep the newest turn in view as the conversation grows.
  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight });
  }, [transcriptions.length]);

  return (
    <>
      {onHold && (
        <div className="hold">
          <span style={{ color: "var(--warning)", display: "inline-flex" }}>
            <Icon name="clock" size={15} />
          </span>
          The agent paused this call and is waiting on your approval →
        </div>
      )}

      <MicStatus />

      <div className="stage">
        <BarVisualizer className="viz" state={state} track={audioTrack} barCount={7} />
        <span className="agentstate">
          <span className="pulse" />
          {AGENT_STATE_COPY[state] ?? state}
        </span>
        <div className="btns">
          <VoiceAssistantControlBar controls={{ leave: false }} />
          <DisconnectButton className="btn btn--critical">End call</DisconnectButton>
        </div>
      </div>

      <Latency samples={samples} />

      <div className="transcript" ref={feed}>
        {transcriptions.length === 0 ? (
          <div className="transcript__empty">Say something — the transcript appears here.</div>
        ) : (
          transcriptions.map((t, i) => {
            const fromAgent = !!agent && t.participantInfo.identity === agent.identity;
            // The stream's own timestamp — not `new Date()`, which would re-evaluate on
            // every render and stamp every past turn with the current time.
            const at = t.streamInfo?.timestamp;
            return (
              <div className={`turn ${fromAgent ? "turn--agent" : ""}`} key={t.streamInfo?.id ?? i}>
                <span className="turn__who">{fromAgent ? "Agent" : "You"}</span>
                <span className="turn__text">{t.text}</span>
                {at ? (
                  <span className="turn__time">
                    {new Date(at).toLocaleTimeString([], {
                      hour12: false,
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>
                ) : null}
              </div>
            );
          })
        )}
      </div>
      <RoomAudioRenderer />
    </>
  );
}

export default function LiveCall({
  conn,
  onHold,
  onDisconnected,
  onError,
}: {
  conn: TokenResp;
  onHold: boolean;
  onDisconnected: () => void;
  onError: (e: Error) => void;
}) {
  return (
    <LiveKitRoom
      serverUrl={conn.url}
      token={conn.token}
      connect
      audio
      video={false}
      onDisconnected={onDisconnected}
      onError={onError}
    >
      <CallStage onHold={onHold} />
    </LiveKitRoom>
  );
}
