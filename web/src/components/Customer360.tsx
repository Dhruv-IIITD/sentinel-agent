import { useEffect, useState } from "react";
import { api, type Customer360 as Customer360Data } from "../api";
import { Badge, statusOf } from "./Badge";

export function Customer360({ orderId }: { orderId: number }) {
  const [data, setData] = useState<Customer360Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    api.customer360(orderId)
      .then((next) => {
        if (!active) return;
        if ("error" in next) setError(next.error);
        else setData(next);
      })
      .catch((reason) => {
        if (active) setError(String(reason));
      });
    return () => {
      active = false;
    };
  }, [orderId]);

  if (error) {
    return <div className="customer360 customer360--muted">Customer context unavailable.</div>;
  }
  if (!data) {
    return <div className="customer360 customer360--muted">Loading customer context…</div>;
  }

  return (
    <section className="customer360" aria-label={`Customer context for order ${orderId}`}>
      <div className="customer360__head">
        <div>
          <div className="customer360__eyebrow">Customer 360</div>
          <strong>{data.customer.name}</strong>
          <div className="customer360__email">{data.customer.email}</div>
        </div>
        <Badge
          status="neutral"
          label={`${data.orders.length} order${data.orders.length === 1 ? "" : "s"}`}
        />
      </div>

      <div className="customer360__section">
        <div className="customer360__label">Order history</div>
        {data.orders.map((order) => (
          <div className="customer360__row" key={order.id}>
            <span className="customer360__id">#{order.id}</span>
            <span className="customer360__item">{order.item_description}</span>
            <span className="customer360__amount">${order.amount.toFixed(2)}</span>
            <Badge status={statusOf(order.status)} label={order.status.replace("_", " ")} />
          </div>
        ))}
      </div>

      <div className="customer360__columns">
        <div className="customer360__section">
          <div className="customer360__label">Past refunds</div>
          {data.refunds.length === 0 ? (
            <div className="customer360__empty">No past refunds</div>
          ) : (
            data.refunds.map((refund, index) => (
              <div className="customer360__row" key={`${refund.order_id}-${index}`}>
                <span className="customer360__id">#{refund.order_id}</span>
                <span className="customer360__amount">${refund.amount.toFixed(2)}</span>
                <Badge status={statusOf(refund.status)} label={refund.status.replace("_", " ")} />
              </div>
            ))
          )}
        </div>

        <div className="customer360__section">
          <div className="customer360__label">Notes</div>
          {data.notes.length === 0 ? (
            <div className="customer360__empty">No notes</div>
          ) : (
            data.notes.map((note, index) => (
              <div className="customer360__note" key={`${note.order_id}-${index}`}>
                <span>#{note.order_id} · {note.author}</span>
                {note.note}
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
