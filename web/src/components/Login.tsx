import { useState, type FormEvent } from "react";
import { Icon } from "./Badge";

export function Login({ onLogin }: { onLogin: (email: string, password: string) => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onLogin(email, password);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-card__head">
          <span className="mark">
            <Icon name="phone" size={14} />
          </span>
          <div>
            <strong>HITL Agent</strong>
            <div>Operator console</div>
          </div>
        </div>

        <h1>Sign in</h1>
        <p>Use your operator credentials to review and resolve approval requests.</p>

        <label className="field" htmlFor="login-email">Email</label>
        <input
          id="login-email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          autoFocus
        />

        <label className="field" htmlFor="login-password">Password</label>
        <input
          id="login-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />

        {error && <div className="auth-error" role="alert">{error}</div>}

        <button className="btn btn--primary auth-submit" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
