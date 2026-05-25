const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-950 px-6 py-16 text-slate-100">
      <section className="mx-auto max-w-3xl rounded-2xl border border-slate-800 bg-slate-900 p-8 shadow-xl">
        <p className="text-sm uppercase tracking-[0.3em] text-cyan-300">Day 1 Scaffold</p>
        <h1 className="mt-4 text-4xl font-semibold">Teacher Assistant</h1>
        <p className="mt-4 text-slate-300">
          Independent AI-powered Teacher Assistant scaffold. No grading logic, no LLM calls,
          no uploads, and no auth implemented yet.
        </p>
        <p className="mt-6 text-sm text-slate-400">Backend API: {apiBaseUrl}</p>
      </section>
    </main>
  );
}
