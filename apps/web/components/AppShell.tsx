"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { getCurrentUser, logout, type User } from "../lib/api";

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const [currentUser, setCurrentUser] = useState<User | null>(null);

  const loadCurrentUser = useCallback(async () => {
    try {
      setCurrentUser(await getCurrentUser());
    } catch {
      setCurrentUser(null);
    }
  }, []);

  useEffect(() => {
    void loadCurrentUser();
    window.addEventListener("auth-changed", loadCurrentUser);
    return () => window.removeEventListener("auth-changed", loadCurrentUser);
  }, [loadCurrentUser]);

  async function handleLogout() {
    await logout();
    setCurrentUser(null);
    window.dispatchEvent(new Event("auth-changed"));
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-6 py-5 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <Link href="/dashboard" className="grid h-10 w-10 place-items-center rounded-xl bg-cyan-400 font-bold text-slate-950">
              TA
            </Link>
            <div>
              <Link href="/dashboard" className="text-lg font-semibold tracking-tight">
                Teacher Assistant
              </Link>
            {currentUser ? (
                <p data-testid="current-teacher" className="text-xs text-slate-400">Signed in as {currentUser.name}</p>
            ) : (
                <p className="text-xs text-slate-500">Teacher-controlled grading</p>
            )}
            </div>
          </div>
          <nav className="flex flex-wrap gap-3 text-sm">
            <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" href="/dashboard">
              Dashboard
            </Link>
            <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" href="/courses">
              Courses
            </Link>
            {currentUser ? (
              <button data-testid="logout-button" className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" type="button" onClick={() => void handleLogout()}>
                Logout
              </button>
            ) : (
              <>
                <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" href="/login">
                  Login
                </Link>
                <Link className="rounded bg-cyan-400 px-3 py-2 font-semibold text-slate-950 hover:bg-cyan-300" href="/register">
                  Create account
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>
      <section className="mx-auto max-w-6xl px-6 py-8">{children}</section>
    </main>
  );
}

export function EmptyState({ message }: Readonly<{ message: string }>) {
  return <p className="rounded border border-slate-800 bg-slate-900 p-4 text-slate-400">{message}</p>;
}

export function ErrorState({ message }: Readonly<{ message: string }>) {
  return <p className="rounded border border-red-800 bg-red-950/40 p-4 text-red-200">{message}</p>;
}

export function LoadingState() {
  return <p className="rounded border border-slate-800 bg-slate-900 p-4 text-slate-300">Loading...</p>;
}

export const inputClass =
  "w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 placeholder:text-slate-500";
export const buttonClass =
  "rounded bg-cyan-500 px-4 py-2 font-semibold text-slate-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50";
