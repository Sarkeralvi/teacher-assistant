"use client";

import { FormEvent, useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import { createUser, listUsers, type User } from "../lib/api";

export function UsersClient() {
  const [users, setUsers] = useState<User[]>([]);
  const [name, setName] = useState("Dev Teacher");
  const [email, setEmail] = useState("teacher@example.com");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadUsers() {
    setLoading(true);
    setError(null);
    try {
      setUsers(await listUsers());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadUsers();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createUser({ name, email, role: "teacher" });
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Users / teacher setup</h1>
        <p className="mt-2 text-slate-400">Dev-only teacher records. No auth or login here.</p>
      </div>

      <form onSubmit={handleSubmit} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5 md:grid-cols-3">
        <label className="space-y-1">
          <span className="text-sm text-slate-300">Name</span>
          <input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label className="space-y-1">
          <span className="text-sm text-slate-300">Email</span>
          <input className={inputClass} value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <div className="flex items-end">
          <button className={buttonClass} disabled={submitting} type="submit">
            {submitting ? "Creating..." : "Create teacher"}
          </button>
        </div>
      </form>

      {error && <ErrorState message={error} />}
      {loading ? <LoadingState /> : null}
      {!loading && users.length === 0 ? <EmptyState message="No users yet." /> : null}
      <div className="grid gap-3">
        {users.map((user) => (
          <article key={user.id} className="rounded border border-slate-800 bg-slate-900 p-4">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <h2 className="text-lg font-semibold">{user.name}</h2>
                <p className="text-sm text-slate-400">{user.email}</p>
              </div>
              <code className="rounded bg-slate-950 px-3 py-2 text-cyan-300">teacher_id: {user.id}</code>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
