import { useState, type FormEvent } from "react";
import { api, errorMessage } from "../services/api";
import { useAuth } from "../stores/auth";
import type { User } from "../types";

export default function Login() {
  const signIn = useAuth((s) => s.signIn);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ access_token: string; user: User }>("/auth/login", { email, password });
      signIn(r.access_token, r.user);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <h1>RenovAI</h1>
      <p className="muted">Estimating desk for renovation and interior projects.</p>
      <form onSubmit={submit} className="panel" aria-label="Sign in">
        <div className="field"><label htmlFor="email">Email</label><input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div className="field"><label htmlFor="pw">Password</label><input id="pw" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></div>
        {error && <div className="field-err" role="alert">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}
