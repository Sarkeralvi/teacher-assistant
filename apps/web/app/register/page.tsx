"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { buttonClass, ErrorState, inputClass } from "../../components/AppShell";
import { register, setStoredAuthToken } from "../../lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
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
      const result = await register({ name, email, password, role: "teacher" });
      setStoredAuthToken(result.access_token);
      window.dispatchEvent(new Event("auth-changed"));
      router.push("/courses");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Register</h1>
        <p className="mt-2 text-sm text-slate-400">Creates a teacher account. Token storage uses localStorage and is dev-only.</p>
      </div>
      {error ? <ErrorState message={error} /> : null}
      <form data-testid="register-form" onSubmit={handleSubmit} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <input data-testid="register-name-input" className={inputClass} name="name" placeholder="name" value={name} onChange={(event) => setName(event.target.value)} required />
        <input data-testid="register-email-input" className={inputClass} name="email" type="email" placeholder="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        <input data-testid="register-password-input" className={inputClass} name="password" type="password" placeholder="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        <button data-testid="register-submit-button" className={buttonClass} disabled={submitting || !hydrated} type="submit">
          {submitting ? "Registering..." : "Register"}
        </button>
      </form>
    </div>
  );
}
