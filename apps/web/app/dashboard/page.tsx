import Link from "next/link";

import { AppShell } from "../../components/AppShell";

export default function DashboardPage() {
  return (
    <AppShell>
      <div className="space-y-6">
        <section className="rounded border border-slate-800 bg-slate-900 p-6">
          <p className="text-sm uppercase tracking-[0.3em] text-cyan-300">TA-W1-006</p>
          <h1 className="mt-3 text-3xl font-semibold">Academic workflow dashboard</h1>
          <p className="mt-3 max-w-2xl text-slate-300">
            Functional browser workflow for Teacher/User placeholder → Course → Assessment → Question → Rubric. No auth, uploads, grading, or AI calls.
          </p>
        </section>

        <div className="grid gap-4 md:grid-cols-2">
          <Link href="/users" className="rounded border border-slate-800 bg-slate-900 p-5 hover:border-cyan-700">
            <h2 className="text-xl font-semibold">Users / teacher setup</h2>
            <p className="mt-2 text-slate-400">Create dev teacher users and copy teacher_id values.</p>
          </Link>
          <Link href="/courses" className="rounded border border-slate-800 bg-slate-900 p-5 hover:border-cyan-700">
            <h2 className="text-xl font-semibold">Courses</h2>
            <p className="mt-2 text-slate-400">Create courses and continue to assessments, questions, and rubrics.</p>
          </Link>
        </div>
      </div>
    </AppShell>
  );
}
