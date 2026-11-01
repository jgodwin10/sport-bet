import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, setToken } from "../api/client";
import { LoginForm } from "../api/types";
import { Icon } from "../components/icons";
import { Field } from "../components/ui";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const qc = useQueryClient();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const parsed = LoginForm.safeParse({ email, password });
    if (!parsed.success) return setError(parsed.error.issues[0].message);
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ access_token: string }>("/auth/login", { method: "POST", body: parsed.data });
      setToken(res.access_token);
      await qc.invalidateQueries();
      nav("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[60dvh] grid place-items-center">
      <div className="w-full max-w-sm">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
          <p className="mt-1.5 text-sm text-ink-3">Anyone can browse predictions. Sign in to manage settings.</p>
        </div>
        <form onSubmit={submit} className="card p-5 sm:p-6 space-y-4" noValidate>
          <Field label="Email"><input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Password"><input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          {error && (
            <p role="alert" className="flex gap-2 text-[13px] text-neg">
              <Icon name="alert" size={15} className="shrink-0 mt-0.5" />{error}
            </p>
          )}
          <button className="btn btn-primary w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      </div>
    </div>
  );
}
