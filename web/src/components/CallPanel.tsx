import { Suspense, lazy, useState } from "react";
import { api, type Approval, type TokenResp } from "../api";
import { Icon } from "./Badge";

// Loaded only when a call actually starts — keeps LiveKit out of the initial bundle.
const LiveCall = lazy(() => import("./LiveCall"));

function VoiceTab({
  approvals,
  notify,
  onActivity,
}: {
  approvals: Approval[];
  notify: (msg: string, ok?: boolean) => void;
  onActivity: () => void;
}) {
  const [conn, setConn] = useState<TokenResp | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [unavailable, setUnavailable] = useState<string | null>(null);

  // The token response carries this call's graph thread, so we can tell the caller
  // when *their* action is the one sitting in the approval queue.
  const onHold = !!conn && approvals.some((a) => a.thread_id === conn.thread_id);

  async function start() {
    setConnecting(true);
    try {
      setConn(await api.token());
      setUnavailable(null);
    } catch {
      setUnavailable(
        "LiveKit isn’t configured on the backend. Set LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET in .env — or use the Text tab.",
      );
    } finally {
      setConnecting(false);
    }
  }

  if (!conn) {
    return (
      <div className="stage">
        <button className="btn btn--primary" onClick={start} disabled={connecting}>
          <Icon name="phone" /> {connecting ? "Connecting…" : "Start a voice call"}
        </button>
        <p className="stage__hint">
          {unavailable ??
            "Talk to the support agent in your browser. It can look up orders and issue refunds — high-stakes actions pause for your approval."}
        </p>
      </div>
    );
  }

  return (
    <Suspense fallback={<div className="stage">Connecting to the call…</div>}>
      <LiveCall
        conn={conn}
        onHold={onHold}
        onDisconnected={() => {
          setConn(null);
          onActivity();
        }}
        onError={(e) => notify(`Call error: ${e.message}`, false)}
      />
    </Suspense>
  );
}

function TextTab({
  notify,
  onActivity,
}: {
  notify: (msg: string, ok?: boolean) => void;
  onActivity: () => void;
}) {
  const [message, setMessage] = useState("My order 4471 arrived damaged, I'd like a refund.");
  const [thread, setThread] = useState("web-demo");
  const [reply, setReply] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send() {
    setBusy(true);
    setReply(null);
    try {
      const res = await api.chat(message, thread);
      setReply(
        res.status === "completed"
          ? res.reply || "(no reply)"
          : `Paused — ${res.approvals?.length ?? 0} action(s) need your approval.`,
      );
      onActivity();
    } catch (e) {
      notify(String(e), false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <label className="field">Message to the agent</label>
      <textarea rows={3} value={message} onChange={(e) => setMessage(e.target.value)} />
      <label className="field">Thread id</label>
      <input value={thread} onChange={(e) => setThread(e.target.value)} />
      <div className="btns" style={{ marginTop: 12 }}>
        <button className="btn btn--primary" onClick={send} disabled={busy}>
          {busy ? "Sending…" : "Send"}
        </button>
      </div>
      {reply && (
        <div className="outcome" style={{ marginTop: 12 }}>
          {reply}
        </div>
      )}
    </div>
  );
}

export function CallPanel(props: {
  approvals: Approval[];
  notify: (msg: string, ok?: boolean) => void;
  onActivity: () => void;
}) {
  const [tab, setTab] = useState<"voice" | "text">("voice");

  return (
    <section className="panel">
      <div className="panel__head">
        <span className="panel__title">Live call</span>
        <div className="spacer" />
        <div className="tabs" role="tablist">
          <button className="tab" role="tab" aria-selected={tab === "voice"} onClick={() => setTab("voice")}>
            Voice
          </button>
          <button className="tab" role="tab" aria-selected={tab === "text"} onClick={() => setTab("text")}>
            Text
          </button>
        </div>
      </div>
      <div className="panel__body">
        {tab === "voice" ? (
          <VoiceTab {...props} />
        ) : (
          <TextTab notify={props.notify} onActivity={props.onActivity} />
        )}
      </div>
    </section>
  );
}
