import Link from "next/link";

import { API_BASE_URL } from "../lib/api";

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/80">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-6 py-5 md:flex-row md:items-center md:justify-between">
          <div>
            <Link href="/dashboard" className="text-xl font-semibold">
              Teacher Assistant
            </Link>
            <p className="text-sm text-slate-400">Backend: {API_BASE_URL}</p>
          </div>
          <nav className="flex flex-wrap gap-3 text-sm">
            <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" href="/dashboard">
              Dashboard
            </Link>
            <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" href="/users">
              Users
            </Link>
            <Link className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" href="/courses">
              Courses
            </Link>
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
