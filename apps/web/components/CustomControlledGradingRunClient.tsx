"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import {
  createCustomGradingRun,
  getAssessment,
  getAssessmentFinalGradesExportUrl,
  listAssessmentGradingRuns,
  updateGradingRun,
  uploadGradingRunMaterials,
  type Assessment,
  type GradingRun,
} from "../lib/api";

const workflowSteps = [
  "Start custom controlled run",
  "Upload/confirm materials",
  "Confirm or create questions/rubrics",
  "Upload scripts",
  "Create answer regions manually",
  "Run mock batch grading",
  "Review suggestions",
  "Approve selected / export",
];

const statusOptions = [
  "draft",
  "materials_uploaded",
  "questions_ready",
  "scripts_uploaded",
  "regions_ready",
  "grading_ready",
  "review_ready",
  "completed",
];

export function CustomControlledGradingRunClient({ assessmentId }: Readonly<{ assessmentId: number }>) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [gradingRuns, setGradingRuns] = useState<GradingRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState("draft");
  const [questionPdf, setQuestionPdf] = useState<File | null>(null);
  const [solutionPdf, setSolutionPdf] = useState<File | null>(null);
  const [rubricPdf, setRubricPdf] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedRun = gradingRuns.find((run) => run.id === selectedRunId) ?? gradingRuns[0] ?? null;

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [assessmentData, runData] = await Promise.all([
        getAssessment(assessmentId),
        listAssessmentGradingRuns(assessmentId),
      ]);
      setAssessment(assessmentData);
      setGradingRuns(runData);
      const firstRun = runData[0] ?? null;
      setSelectedRunId((current) => current ?? firstRun?.id ?? null);
      setStatus(firstRun?.status ?? "draft");
      setNotes(firstRun?.notes ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load custom controlled grading run");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [assessmentId]);

  async function handleStartRun() {
    setSaving(true);
    setError(null);
    try {
      const run = await createCustomGradingRun(assessmentId, {
        notes: notes || "Custom controlled mode: teacher confirmation required.",
      });
      setGradingRuns((current) => [run, ...current]);
      setSelectedRunId(run.id);
      setStatus(run.status);
      setNotes(run.notes ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start grading run");
    } finally {
      setSaving(false);
    }
  }

  async function handleUploadMaterials(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedRun) {
      setError("Start custom controlled run before uploading materials.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await uploadGradingRunMaterials(selectedRun.id, {
        question_pdf: questionPdf,
        solution_pdf: solutionPdf,
        rubric_pdf: rubricPdf,
      });
      replaceRun(updated);
      setStatus(updated.status);
      setQuestionPdf(null);
      setSolutionPdf(null);
      setRubricPdf(null);
      event.currentTarget.reset();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload grading-run materials");
    } finally {
      setSaving(false);
    }
  }

  async function handleUpdateRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedRun) {
      setError("Start custom controlled run before updating status.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await updateGradingRun(selectedRun.id, { status, notes });
      replaceRun(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update grading run");
    } finally {
      setSaving(false);
    }
  }

  function replaceRun(updated: GradingRun) {
    setGradingRuns((current) => current.map((run) => (run.id === updated.id ? updated : run)));
    setSelectedRunId(updated.id);
    setNotes(updated.notes ?? "");
    setStatus(updated.status);
  }

  function handleFileChange(setter: (file: File | null) => void) {
    return (event: ChangeEvent<HTMLInputElement>) => setter(event.target.files?.[0] ?? null);
  }

  return (
    <div className="space-y-6">
      {loading ? <LoadingState /> : null}
      {error && <ErrorState message={error} />}

      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <p className="text-sm text-slate-400">Assessment #{assessmentId}</p>
        <h1 className="text-3xl font-semibold">Custom Controlled Grading Run</h1>
        <p className="mt-2 text-slate-300">{assessment?.title ?? "Loading assessment..."}</p>
        <p className="mt-3 rounded border border-amber-700 bg-amber-950/40 p-3 text-sm text-amber-100">
          Custom controlled mode: teacher confirmation required. This wizard organizes existing tools; it does not finalize grades automatically.
        </p>
        <div className="mt-4 grid gap-2 text-sm text-slate-300 md:grid-cols-2">
          <p>No automatic answer-region detection.</p>
          <p>No real Codex batch grading by default.</p>
          <p>Teacher must confirm questions/model answers/rubrics before grading.</p>
          <p>Final grades still require teacher review and approval.</p>
        </div>
      </section>

      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Wizard steps</h2>
        <ol className="mt-4 grid gap-2 md:grid-cols-2">
          {workflowSteps.map((step, index) => (
            <li key={step} className="rounded border border-slate-800 p-3 text-sm">
              <span className="text-slate-500">Step {index + 1}</span>
              <p className="font-medium">{step}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">Start custom controlled run</h2>
            <p className="text-sm text-slate-400">Mode: custom_controlled · status: {selectedRun?.status ?? "not started"}</p>
          </div>
          <button className={buttonClass} disabled={saving} onClick={handleStartRun} type="button">
            {saving ? "Saving..." : "Start custom controlled run"}
          </button>
        </div>
        {!loading && gradingRuns.length === 0 ? <EmptyState message="No custom controlled grading run started yet." /> : null}
        {selectedRun ? (
          <div className="mt-4 rounded border border-slate-800 p-3 text-sm text-slate-300">
            <p>Run #{selectedRun.id}</p>
            <p>Question PDF: {selectedRun.question_pdf_path ?? "pending"}</p>
            <p>Solution/model answer PDF: {selectedRun.solution_pdf_path ?? "pending"}</p>
            <p>Rubric PDF: {selectedRun.rubric_pdf_path ?? "pending"}</p>
          </div>
        ) : null}
      </section>

      <form onSubmit={handleUploadMaterials} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Upload/confirm materials</h2>
        <label className="grid gap-2 text-sm">
          Question PDF
          <input className={inputClass} type="file" accept="application/pdf,.pdf" onChange={handleFileChange(setQuestionPdf)} />
        </label>
        <label className="grid gap-2 text-sm">
          Solution/model answer PDF
          <input className={inputClass} type="file" accept="application/pdf,.pdf" onChange={handleFileChange(setSolutionPdf)} />
        </label>
        <label className="grid gap-2 text-sm">
          Rubric PDF
          <input className={inputClass} type="file" accept="application/pdf,.pdf" onChange={handleFileChange(setRubricPdf)} />
        </label>
        <button className={buttonClass} disabled={saving || !selectedRun} type="submit">
          Upload/confirm materials
        </button>
      </form>

      <form onSubmit={handleUpdateRun} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Current status</h2>
        <select className={inputClass} value={status} onChange={(event) => setStatus(event.target.value)}>
          {statusOptions.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
        <textarea
          className={inputClass}
          placeholder="Run notes"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
        />
        <button className={buttonClass} disabled={saving || !selectedRun} type="submit">
          Save status / notes
        </button>
      </form>

      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Existing workflow links</h2>
        <div className="mt-4 flex flex-wrap gap-3">
          <Link className={buttonClass} href={`/assessments/${assessmentId}`}>
            Confirm or create questions/rubrics, upload scripts, create answer regions manually, run mock grading
          </Link>
          <Link className={buttonClass} href={`/assessments/${assessmentId}/review`}>
            Review suggestions and approve selected
          </Link>
          <a className={buttonClass} href={getAssessmentFinalGradesExportUrl(assessmentId)}>
            Approve selected / export
          </a>
        </div>
        <p className="mt-3 text-sm text-slate-400">
          Run mock batch grading from the review page or use existing controlled grading actions only after teacher-confirmed materials are ready.
        </p>
      </section>
    </div>
  );
}
