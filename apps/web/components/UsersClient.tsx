"use client";

import { useEffect, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "./AppShell";
import { listUsers, type User } from "../lib/api";
import { SetDemoTeacherButton } from "./DemoTeacherSelector";

export function UsersClient() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Users / teacher directory</h1>
        <p className="mt-2 text-slate-400">
          Registered teachers. Create an account via Register, then set it as the current demo
          teacher here.
        </p>
      </div>

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
              <div className="flex flex-wrap items-center gap-2">
                <code className="rounded bg-slate-950 px-3 py-2 text-cyan-300">teacher_id: {user.id}</code>
                {user.role === "teacher" ? <SetDemoTeacherButton user={user} onSelected={() => void loadUsers()} /> : null}
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
