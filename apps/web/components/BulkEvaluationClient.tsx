"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  approveCleanBulkEvaluation,
  createBulkEvaluationRun,
  downloadBulkEvaluationResults,
  getLocalAiStatus,
  listAssessmentGradingRuns,
  listBulkEvaluationExceptions,
  listBulkEvaluationRuns,
  resumeBulkEvaluationItem,
  resumeBulkEvaluationRun,
  stopBulkEvaluationRun,
  type BulkEvaluationException,
  type BulkEvaluationRun,
  type GradingRun,
  type LocalAiStatus,
  type MarkingPolicy,
} from "../lib/api";

const buttonClass =
  "inline-flex min-h-11 items-center justify-center rounded-lg bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50";
const secondaryButtonClass =
  "inline-flex min-h-11 items-center justify-center rounded-lg border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-100 disabled:cursor-not-allowed disabled:opacity-50";
const inputClass =
  "min-h-11 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100";
const activeStatuses = new Set([
  "preflighting",
  "queued",
  "mapping",
  "transcribing",
  "grading",
  "stopping",
]);

export function BulkEvaluationClient({ assessmentId }: Readonly<{ assessmentId: number }>) {
  const [runs, setRuns] = useState<BulkEvaluationRun[]>([]);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [exceptions, setExceptions] = useState<BulkEvaluationException[]>([]);
  const [gradingRuns, setGradingRuns] = useState<GradingRun[]>([]);
  const [localAi, setLocalAi] = useState<LocalAiStatus | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [gradingRunId, setGradingRunId] = useState<number | null>(null);
  const [markingPolicy, setMarkingPolicy] = useState<MarkingPolicy>("general");
  const [callLimit, setCallLimit] = useState(2000);
  const [authorized, setAuthorized] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const activeRun = runs.find((run) => run.id === activeRunId) ?? runs[0] ?? null;

  const refresh = useCallback(async () => {
    const [runRows, gradingRows, status] = await Promise.all([
      listBulkEvaluationRuns(assessmentId),
      listAssessmentGradingRuns(assessmentId),
      getLocalAiStatus(),
    ]);
    setRuns(runRows);
    setGradingRuns(gradingRows);
    setLocalAi(status);
    const selected = activeRunId
      ? runRows.find((run) => run.id === activeRunId) ?? runRows[0] ?? null
      : runRows[0] ?? null;
    setActiveRunId(selected?.id ?? null);
    setGradingRunId((current) => current ?? eligibleGradingRun(gradingRows)?.id ?? null);
    setExceptions(selected ? await listBulkEvaluationExceptions(selected.id) : []);
  }, [activeRunId, assessmentId]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        await refresh();
      } catch (caught) {
        if (!cancelled) setError(errorMessage(caught));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  useEffect(() => {
    if (!activeRun || !activeStatuses.has(activeRun.status)) return;
    const interval = window.setInterval(() => void refresh().catch(() => undefined), 5000);
    return () => window.clearInterval(interval);
  }, [activeRun, refresh]);

  const expectedModel = localAi?.qwen38.models[0] ?? "";
  const cleanSuggestionIds = useMemo(
    () =>
      activeRun?.items
        .filter(
          (item) =>
            item.status === "graded" &&
            item.grade_suggestion_id !== null &&
            item.final_grade_id === null &&
            item.exception_codes.length === 0,
        )
        .map((item) => item.grade_suggestion_id as number) ?? [],
    [activeRun],
  );
  const heartbeatStale = Boolean(
    activeRun &&
      activeStatuses.has(activeRun.status) &&
      activeRun.heartbeat_at &&
      Date.now() - new Date(activeRun.heartbeat_at).getTime() > 10 * 60 * 1000,
  );

  async function createRun() {
    if (!file || !gradingRunId || !expectedModel || !authorized) return;
    setBusy(true);
    setError(null);
    try {
      const run = await createBulkEvaluationRun(assessmentId, {
        file,
        grading_run_id: gradingRunId,
        expected_model: expectedModel,
        marking_policy: markingPolicy,
        maximum_provider_calls: callLimit,
      });
      setActiveRunId(run.id);
      setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      setExceptions([]);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function applyRunAction(action: "stop" | "resume") {
    if (!activeRun) return;
    setBusy(true);
    setError(null);
    try {
      const updated = action === "stop"
        ? await stopBulkEvaluationRun(activeRun.id)
        : await resumeBulkEvaluationRun(activeRun.id);
      setRuns((current) => current.map((run) => run.id === updated.id ? updated : run));
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function approveClean() {
    if (!activeRun?.review_snapshot_sha256 || cleanSuggestionIds.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await approveCleanBulkEvaluation(
        activeRun.id,
        cleanSuggestionIds,
        activeRun.review_snapshot_sha256,
      );
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function downloadResults() {
    if (!activeRun) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await downloadBulkEvaluationResults(activeRun.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `bulk-evaluation-${activeRun.id}.xlsx`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
          Bulk supervised evaluation
        </p>
        <h1 className="mt-2 text-3xl font-semibold">Upload once. Review exceptions first.</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">
          Qwen3.8 maps, transcribes, and creates draft scores sequentially. Unreadable,
          incomplete, or contradictory evidence is quarantined and never silently graded.
        </p>
      </header>

      {error ? <div className="rounded-lg border border-rose-700 bg-rose-950/40 p-4 text-rose-100">{error}</div> : null}
      {loading ? <p className="text-sm text-slate-400">Loading bulk evaluation state…</p> : null}

      <section className="grid gap-4 rounded-2xl border border-slate-800 bg-slate-900 p-6 lg:grid-cols-4">
        <StatusCard label="Qwen3.8" value={localAi?.qwen38.available ? "Ready" : localAi?.qwen38.enabled ? "Starts on authorization" : "Disabled"} />
        <StatusCard label="References" value={gradingRunId ? "Finalized" : "Blocked"} />
        <StatusCard label="Active run" value={activeRun ? `#${activeRun.id}` : "None"} />
        <StatusCard label="Safety" value="Draft only" />
      </section>

      <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-6">
        <div>
          <h2 className="text-xl font-semibold">1. Start a background run</h2>
          <p className="mt-1 text-sm text-slate-400">
            ZIP: one PDF per student at the root, or one folder per student with ordered images.
            Existing submissions are not modified.
          </p>
        </div>
        <div className="grid gap-3 lg:grid-cols-4">
          <input className={inputClass} type="file" accept=".zip,application/zip" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          <select className={inputClass} value={gradingRunId ?? ""} onChange={(event) => setGradingRunId(Number(event.target.value))}>
            <option value="">Select finalized reference run</option>
            {gradingRuns.map((run) => <option key={run.id} value={run.id}>Run #{run.id} · {run.marking_policy}</option>)}
          </select>
          <select className={inputClass} value={markingPolicy} onChange={(event) => setMarkingPolicy(event.target.value as MarkingPolicy)}>
            <option value="tough">Tough</option><option value="general">General</option><option value="easy">Easy</option>
          </select>
          <input className={inputClass} type="number" min={1} max={2000} value={callLimit} onChange={(event) => setCallLimit(Number(event.target.value))} aria-label="Maximum model calls" />
        </div>
        <label className="flex items-start gap-3 rounded-lg border border-amber-700/60 bg-amber-950/20 p-4 text-sm text-amber-100">
          <input className="mt-1" type="checkbox" checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} />
          <span>I authorize local-only Qwen3.8 processing under strict auto-pass rules. All scores remain drafts until I approve them.</span>
        </label>
        <button className={buttonClass} disabled={busy || !file || !gradingRunId || !expectedModel || !authorized || !localAi?.qwen38.enabled} type="button" onClick={() => void createRun()}>
          {busy ? "Working…" : "Start bulk evaluation"}
        </button>
      </section>

      {activeRun ? (
        <>
          <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><h2 className="text-xl font-semibold">2. Background progress</h2><p className="text-sm text-slate-400">Run #{activeRun.id} · {activeRun.status} · {activeRun.stage}</p></div>
              <select className={inputClass} value={activeRun.id} onChange={(event) => setActiveRunId(Number(event.target.value))}>
                {runs.map((run) => <option key={run.id} value={run.id}>Run #{run.id} · {run.status}</option>)}
              </select>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <StatusCard label="Scripts" value={`${activeRun.total_submissions}`} />
              <StatusCard label="Processed packets" value={`${activeRun.processed_items}/${activeRun.total_items}`} />
              <StatusCard label="Model calls" value={`${activeRun.calls_used}/${activeRun.authorized_call_limit}`} />
              <StatusCard label="Clean drafts" value={`${activeRun.clean_item_count}`} />
              <StatusCard label="Exceptions" value={`${activeRun.exception_count}`} />
            </div>
            {activeRun.error ? <p className="rounded-lg border border-rose-800 p-3 text-sm text-rose-200">{activeRun.error}</p> : null}
            <div className="flex flex-wrap gap-3">
              {activeStatuses.has(activeRun.status) ? <button className={secondaryButtonClass} disabled={busy} type="button" onClick={() => void applyRunAction("stop")}>Stop after current call</button> : null}
              {["paused", "stopped"].includes(activeRun.status) ? <button className={buttonClass} disabled={busy} type="button" onClick={() => void applyRunAction("resume")}>Resume never-started work</button> : null}
              {heartbeatStale ? <button className={buttonClass} disabled={busy} type="button" onClick={() => void applyRunAction("resume")}>Recover interrupted run</button> : null}
            </div>
          </section>

          <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <div><h2 className="text-xl font-semibold">3. Exceptions requiring attention</h2><p className="text-sm text-slate-400">Granular images and transcripts stay hidden until you inspect a manuscript.</p></div>
            {exceptions.length === 0 ? <p className="rounded-lg border border-emerald-800 bg-emerald-950/20 p-4 text-sm text-emerald-200">No unresolved exceptions.</p> : (
              <div className="space-y-3">{exceptions.map((item) => (
                <article key={item.item_id} className="grid gap-3 rounded-lg border border-amber-800/70 p-4 lg:grid-cols-[1fr_auto] lg:items-center">
                  <div><p className="font-semibold">{item.student_identifier ?? `Submission ${item.submission_id}`} · {item.question_label}</p><p className="mt-1 text-sm text-amber-200">{item.exception_codes.join(", ")}</p></div>
                  <div className="flex gap-2"><Link className={secondaryButtonClass} href={`/assessments/${assessmentId}?submission=${item.submission_id}&answerRegion=${item.answer_region_id ?? ""}`}>Inspect manuscript</Link><button className={secondaryButtonClass} disabled={busy} type="button" onClick={() => void resumeBulkEvaluationItem(activeRun.id, item.item_id).then(refresh).catch((caught) => setError(errorMessage(caught)))}>Resume item</button></div>
                </article>
              ))}</div>
            )}
          </section>

          <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <div><h2 className="text-xl font-semibold">4. Approve clean drafts and download</h2><p className="text-sm text-slate-400">Only unchanged, unflagged draft suggestions are selected. Students with unresolved questions remain INCOMPLETE.</p></div>
            <div className="flex flex-wrap gap-3"><button className={buttonClass} disabled={busy || cleanSuggestionIds.length === 0 || !activeRun.review_snapshot_sha256} type="button" onClick={() => void approveClean()}>Approve {cleanSuggestionIds.length} clean draft{cleanSuggestionIds.length === 1 ? "" : "s"}</button><button className={secondaryButtonClass} disabled={busy || !["completed", "completed_with_exceptions"].includes(activeRun.status)} type="button" onClick={() => void downloadResults()}>Download results workbook</button><Link className={secondaryButtonClass} href={`/assessments/${assessmentId}/review`}>Open individual grade review</Link></div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function eligibleGradingRun(runs: GradingRun[]) {
  return runs.find((run) => run.questions_confirmed_at && run.rubrics_confirmed_at) ?? null;
}

function StatusCard({ label, value }: Readonly<{ label: string; value: string }>) {
  return <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><p className="text-xs uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-lg font-semibold text-slate-100">{value}</p></div>;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Bulk evaluation request failed";
}
