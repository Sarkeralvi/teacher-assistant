import Link from "next/link";

import { AppShell } from "../../components/AppShell";

export default function DashboardPage() {
  return (
    <AppShell>
      <div className="space-y-8">
        <section className="overflow-hidden rounded-3xl border border-cyan-900/80 bg-gradient-to-br from-slate-900 via-slate-900 to-cyan-950/70 p-7 md:p-10">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">Local-first · teacher controlled</p>
          <h1 className="mt-4 max-w-3xl text-4xl font-semibold tracking-tight md:text-5xl">
            Prepare answer scripts and create draft grades on this computer.
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-slate-300">
            PaddleOCR reads the uploaded papers, Qwen connects each answer to the finalized question, solution, and rubric, and you approve every piece of evidence before grading.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link href="/courses" className="rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950 hover:bg-cyan-300">
              Open teacher workspace
            </Link>
            <Link href="/login" className="rounded-xl border border-slate-600 px-5 py-3 font-semibold text-slate-100 hover:border-slate-400">
              Sign in
            </Link>
          </div>
        </section>

        <section>
          <div className="mb-4">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Supervised workflow</p>
            <h2 className="mt-2 text-2xl font-semibold">Three clear checkpoints</h2>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            {[
              ["01", "Finalize references", "Upload the question, solution, and rubric once. Review the local extraction and lock the grading reference."],
              ["02", "Prepare student evidence", "Upload the complete script. PaddleOCR and Qwen identify ordered answer regions without manual coordinates or retyping."],
              ["03", "Review draft grades", "Qwen grades only approved evidence. Suggestions remain pending until the teacher reviews and approves them."],
            ].map(([number, title, description]) => (
              <article key={number} className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
                <span className="text-sm font-semibold text-cyan-300">{number}</span>
                <h3 className="mt-3 text-lg font-semibold">{title}</h3>
                <p className="mt-2 text-sm leading-6 text-slate-400">{description}</p>
              </article>
            ))}
          </div>
        </section>

        <div className="grid gap-3 rounded-2xl border border-emerald-900/80 bg-emerald-950/20 p-5 text-sm text-emerald-100 md:grid-cols-3">
          <p>Local models only</p>
          <p>Explicit teacher confirmation</p>
          <p>Draft grades—never automatic final grades</p>
        </div>
      </div>
    </AppShell>
  );
}
