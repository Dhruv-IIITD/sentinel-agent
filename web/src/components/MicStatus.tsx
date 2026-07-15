import {
  BarVisualizer,
  useLocalParticipant,
  useMediaDeviceSelect,
  useRoomContext,
  useTrackVolume,
} from "@livekit/components-react";
import { LocalAudioTrack, Track } from "livekit-client";
import { useEffect, useRef, useState } from "react";
import { Badge, Icon } from "./Badge";

/** Why the mic isn't live — in the caller's words, not the browser's. */
function explain(err: unknown): string {
  const name = (err as { name?: string })?.name ?? "";
  if (name === "NotAllowedError")
    return "You blocked microphone access. Click the 🔒 in the address bar → allow the mic → reload.";
  if (name === "NotFoundError") return "No microphone found. Plug one in and reload.";
  if (name === "NotReadableError")
    return "Another app is holding the microphone. Close it (Zoom, Teams, Discord) and reload.";
  return `Microphone failed: ${(err as Error)?.message ?? String(err)}`;
}

/**
 * The agent can talk to you without your mic ever carrying sound — you'd hear the
 * greeting, then nothing, with no clue why. Two distinct failures hide behind one
 * happy-looking call:
 *
 *   1. no track published  (permission denied, or a non-secure origin)
 *   2. a track publishing SILENCE  (wrong input device — Windows loves picking
 *      "Stereo Mix" or a disabled array mic)
 *
 * (2) is the nasty one: everything reports healthy, the agent sits in `listening`
 * forever, and nothing in the logs says why. So we show the live input level *and*
 * name the device, rather than asking the user to trust a green badge.
 */
export function MicStatus() {
  const room = useRoomContext();
  const { localParticipant, isMicrophoneEnabled } = useLocalParticipant();
  const [error, setError] = useState<string | null>(null);

  const { devices, activeDeviceId, setActiveMediaDevice } = useMediaDeviceSelect({
    kind: "audioinput",
    room,
  });

  // getUserMedia only exists in a secure context. http://localhost counts;
  // http://<some-ip>:8000 does NOT — a classic way to lose your mic on WSL.
  const insecure = typeof window !== "undefined" && !window.isSecureContext;

  useEffect(() => {
    if (insecure || !localParticipant) return;
    let cancelled = false;
    localParticipant
      .setMicrophoneEnabled(true)
      .then(() => !cancelled && setError(null))
      .catch((e) => !cancelled && setError(explain(e)));
    return () => {
      cancelled = true;
    };
  }, [localParticipant, insecure]);

  if (insecure) {
    return (
      <div className="hold" style={{ borderColor: "var(--critical)" }}>
        <span style={{ color: "var(--critical)", display: "inline-flex" }}>
          <Icon name="critical" size={15} />
        </span>
        Your browser blocks the microphone on this address. Open the console at{" "}
        <code>http://localhost:8000/ui</code> (not an IP) and try again.
      </div>
    );
  }

  if (error) {
    return (
      <div className="hold" style={{ borderColor: "var(--critical)" }}>
        <span style={{ color: "var(--critical)", display: "inline-flex" }}>
          <Icon name="critical" size={15} />
        </span>
        {error}
      </div>
    );
  }

  const micTrack = localParticipant?.getTrackPublication(Track.Source.Microphone)?.track;
  const volume = useTrackVolume(micTrack instanceof LocalAudioTrack ? micTrack : undefined);

  // The killer bug, surfaced to the user: a *live* mic that carries only silence. If the
  // level never crosses a floor for a few seconds while enabled, the device is dead — the
  // browser twin of the worker's "peak 0/100 · SILENT" log. Any real signal clears the flag.
  const [deadMic, setDeadMic] = useState(false);
  const silentSince = useRef<number | null>(null);
  useEffect(() => {
    if (!isMicrophoneEnabled) return;
    if (volume > 0.005) {
      silentSince.current = null;
      setDeadMic(false);
      return;
    }
    if (silentSince.current === null) silentSince.current = Date.now();
    else if (Date.now() - silentSince.current > 4000) setDeadMic(true);
  }, [volume, isMicrophoneEnabled]);

  return (
    <div className="mic">
      <div className="mic__row">
        {isMicrophoneEnabled ? (
          <Badge status="good" label="Mic live" />
        ) : (
          <Badge status="warning" label="Mic muted" />
        )}

        {micTrack ? (
          <BarVisualizer className="viz viz--mic" track={micTrack as never} barCount={9} />
        ) : null}

        <span className="mic__hint">speak — these bars should move</span>
      </div>

      {deadMic && (
        <div className="hold" style={{ borderColor: "var(--critical)", marginTop: 9, marginBottom: 0 }}>
          <span style={{ color: "var(--critical)", display: "inline-flex" }}>
            <Icon name="critical" size={15} />
          </span>
          No sound is reaching us from this microphone. Pick a different device below, and
          check Windows → Settings → Privacy → Microphone (allow desktop apps).
        </div>
      )}

      <label className="mic__row">
        <span className="mic__label">Microphone</span>
        <select
          className="mic__select"
          value={activeDeviceId}
          onChange={(e) => setActiveMediaDevice(e.target.value)}
        >
          {devices.length === 0 && <option>No microphone found</option>}
          {devices.map((d, i) => (
            <option key={d.deviceId} value={d.deviceId}>
              {d.label || `Microphone ${i + 1}`}
            </option>
          ))}
        </select>
      </label>

      {isMicrophoneEnabled && (
        <div className="mic__hint">
          Bars flat while you talk? That device is publishing silence — pick a different one
          above, and check Windows → Privacy → Microphone.
        </div>
      )}
    </div>
  );
}
