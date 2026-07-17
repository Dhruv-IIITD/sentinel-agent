import { useEffect, useState } from "react";
import { api, type CreatedOrder, type Order, type Product } from "../api";
import { Badge, Icon, statusOf } from "./Badge";

function spellOrder(id: number): string {
  return String(id).split("").join(" ");
}

/** The order book — visible, so an operator can read off the number and email a caller
 *  must give to verify. Plus a create form: register yourself, then call in about your
 *  own order. This is the piece whose absence made the whole thing feel like a fixture. */
export function StorePanel({ onChange, notify }: { onChange: () => void; notify: (m: string, ok?: boolean) => void }) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [view, setView] = useState<"orders" | "products">("orders");
  const [created, setCreated] = useState<CreatedOrder | null>(null);
  const [form, setForm] = useState({
    name: "", email: "", productId: "", item: "Ceramic mug set", amount: "60",
  });
  const [busy, setBusy] = useState(false);

  const load = () =>
    Promise.all([api.orders(), api.products()])
      .then(([nextOrders, nextProducts]) => {
        setOrders(nextOrders);
        setProducts(nextProducts);
      })
      .catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const productId = Number(form.productId);
    const fromCatalog = productId > 0;
    const amount = Number(form.amount);
    if (
      !form.name.trim() ||
      !form.email.trim() ||
      (!fromCatalog && (!form.item.trim() || !(amount > 0)))
    ) {
      notify("Name, email, and either a product or custom item and amount are required.", false);
      return;
    }
    setBusy(true);
    try {
      const res = await api.createOrder({
        name: form.name.trim(),
        email: form.email.trim(),
        ...(fromCatalog
          ? { product_id: productId }
          : { item: form.item.trim(), amount }),
      });
      setCreated(res);
      await load();
      onChange();
      notify(`Order #${res.order.id} created for ${res.customer.name}.`);
    } catch (err) {
      notify(String(err), false);
    } finally {
      setBusy(false);
    }
  }

  function chooseProduct(value: string) {
    const product = products.find((p) => p.id === Number(value));
    setForm({
      ...form,
      productId: value,
      item: product?.name ?? "",
      amount: product ? String(product.price) : "",
    });
  }

  const custom = form.productId === "";

  return (
    <div className="store">
      <div className="store__book">
        <div className="tabs" role="tablist" style={{ width: "fit-content", marginBottom: 14 }}>
          <button
            className="tab"
            type="button"
            role="tab"
            aria-selected={view === "orders"}
            onClick={() => setView("orders")}
          >
            Orders
          </button>
          <button
            className="tab"
            type="button"
            role="tab"
            aria-selected={view === "products"}
            onClick={() => setView("products")}
          >
            Products
          </button>
        </div>

        {view === "orders" ? (
          <table className="tbl">
            <thead>
              <tr>
                <th>Order</th>
                <th>Customer</th>
                <th>Email</th>
                <th>Item</th>
                <th className="tbl__num">Amount</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 ? (
                <tr>
                  <td colSpan={6} className="tbl__empty">No orders yet — create one →</td>
                </tr>
              ) : (
                orders.map((o) => (
                  <tr key={o.id}>
                    <td className="tbl__mono">#{o.id}</td>
                    <td>{o.customer_name}</td>
                    <td className="tbl__mono tbl__email">{o.customer_email}</td>
                    <td>{o.item_description}</td>
                    <td className="tbl__num">${o.amount.toFixed(2)}</td>
                    <td>
                      <Badge status={statusOf(o.status)} label={o.status.replace("_", " ")} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Product</th>
                <th className="tbl__num">Price</th>
                <th>Active</th>
              </tr>
            </thead>
            <tbody>
              {products.length === 0 ? (
                <tr>
                  <td colSpan={4} className="tbl__empty">No products yet.</td>
                </tr>
              ) : (
                products.map((product) => (
                  <tr key={product.id}>
                    <td className="tbl__mono">{product.sku}</td>
                    <td>{product.emoji ? `${product.emoji} ` : ""}{product.name}</td>
                    <td className="tbl__num">${product.price.toFixed(2)}</td>
                    <td>
                      <Badge
                        status={product.active ? "good" : "neutral"}
                        label={product.active ? "active" : "inactive"}
                      />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
        <p className="store__hint">
          {view === "orders"
            ? "This is what a caller must verify against — the order number and the email. Pick a row, or create your own below."
            : "Catalog products supply the trusted item name and price when an order is created."}
        </p>
      </div>

      <form className="store__form" onSubmit={submit}>
        <div className="store__title">Create an order</div>
        <label className="field">Name on the order</label>
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Your name" />
        <label className="field">Email</label>
        <input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="you@example.com" />
        <label className="field">Product</label>
        <select value={form.productId} onChange={(e) => chooseProduct(e.target.value)}>
          <option value="">Custom item</option>
          {products.filter((product) => product.active).map((product) => (
            <option key={product.id} value={product.id}>
              {product.emoji ? `${product.emoji} ` : ""}{product.name} — ${product.price.toFixed(2)}
            </option>
          ))}
        </select>
        <div style={{ display: "flex", gap: 10 }}>
          <div style={{ flex: 2 }}>
            <label className="field">Item</label>
            <input
              value={form.item}
              onChange={(e) => setForm({ ...form, item: e.target.value })}
              readOnly={!custom}
            />
          </div>
          <div style={{ flex: 1 }}>
            <label className="field">Amount $</label>
            <input
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              inputMode="decimal"
              readOnly={!custom}
            />
          </div>
        </div>
        <div className="btns" style={{ marginTop: 12 }}>
          <button className="btn btn--primary" disabled={busy} type="submit">
            {busy ? "Creating…" : "Create order"}
          </button>
        </div>

        {created && (
          <div className="store__verify">
            <div className="store__verify-head">
              <Icon name="good" /> Order #{created.order.id} is ready
            </div>
            Start a voice call and say:
            <div className="store__say">
              “order {spellOrder(created.order.id)}, email {created.verify.email}”
            </div>
          </div>
        )}
      </form>
    </div>
  );
}
