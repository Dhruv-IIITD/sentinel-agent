import { useEffect, useRef, useState } from "react";

export type ApprovalEvent = {
  type: "approval.created" | "approval.resolved" | "approval.escalated";
  approval_id: string;
  thread_id: string;
  tool_name?: string;
  status?: string;
  age_seconds?: number;
  at: string;
};

const MAX_BACKOFF_MS = 10_000;

export function useApprovalEvents(onEvent: (event: ApprovalEvent) => void): boolean {
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    let active = true;
    let attempts = 0;
    let reconnectTimer: number | undefined;
    let socket: WebSocket | null = null;

    const scheduleReconnect = () => {
      if (!active) return;
      const delay = Math.min(1000 * 2 ** attempts, MAX_BACKOFF_MS);
      attempts += 1;
      reconnectTimer = window.setTimeout(connect, delay);
    };

    function connect() {
      if (!active) return;

      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      let nextSocket: WebSocket;
      try {
        nextSocket = new WebSocket(`${scheme}://${window.location.host}/ws/approvals`);
      } catch {
        setConnected(false);
        scheduleReconnect();
        return;
      }

      socket = nextSocket;
      nextSocket.onopen = () => {
        if (!active || socket !== nextSocket) return;
        attempts = 0;
        setConnected(true);
      };
      nextSocket.onmessage = (message) => {
        if (typeof message.data !== "string") return;
        let event: ApprovalEvent;
        try {
          event = JSON.parse(message.data) as ApprovalEvent;
        } catch {
          return;
        }
        onEventRef.current(event);
      };
      nextSocket.onerror = () => {
        if (!active || socket !== nextSocket) return;
        setConnected(false);
        nextSocket.close();
      };
      nextSocket.onclose = () => {
        if (!active || socket !== nextSocket) return;
        socket = null;
        setConnected(false);
        scheduleReconnect();
      };
    }

    connect();

    return () => {
      active = false;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      if (socket !== null) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        socket.close();
      }
    };
  }, []);

  return connected;
}
