"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { buttonClass, ErrorState, inputClass } from "../../components/AppShell";
import { login, setStoredAuthToken } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setHydrated(true);
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await login({ email, password });
      setStoredAuthToken(result.access_token);
      window.dispatchEvent(new Event("auth-changed"));
      router.push("/courses");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Login</h1>
        <p className="mt-2 text-sm text-slate-400">Sign in to open your courses, assessments, and supervised grading workflow.</p>
      </div>
      {error ? <ErrorState message={error} /> : null}
      <form data-testid="login-form" onSubmit={handleSubmit} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <input data-testid="login-email-input" className={inputClass} name="email" type="email" placeholder="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        <input data-testid="login-password-input" className={inputClass} name="password" type="password" placeholder="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        <button data-testid="login-submit-button" className={buttonClass} disabled={submitting || !hydrated} type="submit">
          {submitting ? "Logging in..." : "Login"}
        </button>
      </form>
    </div>
  );
}
