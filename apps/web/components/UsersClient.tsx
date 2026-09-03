"use client";

import { useCallback, useEffect, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "./AppShell";
import { getCurrentUser, type User } from "../lib/api";

export function UsersClient() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadUser = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setUser(await getCurrentUser());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Your teacher account</h1>
        <p className="mt-2 text-slate-400">
          Your signed-in account owns and reviews this teacher-controlled grading work.
        </p>
      </div>

      {error && <ErrorState message={error} />}
      {loading ? <LoadingState /> : null}
      {!loading && !user ? <EmptyState message="No signed-in account is available." /> : null}
      {user ? (
        <article className="rounded border border-slate-800 bg-slate-900 p-4">
          <h2 className="text-lg font-semibold">{user.name}</h2>
          <p className="text-sm text-slate-400">{user.email}</p>
          <p className="mt-2 text-sm text-slate-300">Role: {user.role}</p>
        </article>
      ) : null}
    </div>
  );
}
