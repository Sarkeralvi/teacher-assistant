"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import {
  confirmGradingRunMaterials,
  confirmGradingRunQuestionsRubrics,
  createCustomGradingRun,
  getAssessment,
  getAssessmentFinalGradesExportUrl,
  gradeGradingRunReadyRegionsMock,
  listAssessmentGradingRuns,
  updateGradingRun,
  uploadGradingRunMaterials,
  type Assessment,
  type GradingRun,
  type GradingRunWorkflowState,
  type MarkingPolicy,
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

const markingPolicyOptions: Array<{ value: MarkingPolicy; label: string; description: string }> = [
  { value: "tough", label: "Tough", description: "Tough: stricter rubric interpretation." },
  { value: "general", label: "General", description: "General: normal rubric interpretation." },
  { value: "easy", label: "Easy", description: "Easy: more lenient interpretation." },
];

const dashboardSections: Array<{
  key: string;
  label: string;
  isReady: (state: GradingRunWorkflowState) => boolean;
  countText: (state: GradingRunWorkflowState) => string;
}> = [
  {
    key: "materials",
    label: "Materials",
    isReady: (state) => state.materials_uploaded && state.materials_confirmed,
    countText: (state) => `Materials confirmed: ${state.materials_confirmed ? "yes" : "no"}`,
  },
  {
    key: "questions-rubrics",
    label: "Questions/rubrics",
    isReady: (state) => state.questions_confirmed && state.rubrics_confirmed,
    countText: (state) => `Questions/rubrics confirmed: ${state.question_count}/${state.rubric_count}`,
  },
  {
    key: "scripts",
    label: "Scripts",
    isReady: (state) => state.scripts_uploaded,
    countText: (state) => `Scripts uploaded: ${state.submission_count} submissions, ${state.submission_page_count} pages`,
  },
  {
    key: "regions",
    label: "Answer regions",
    isReady: (state) => state.answer_regions_created,
    countText: (state) => `Answer regions created: ${state.answer_region_count}`,
  },
  {
    key: "grading",
    label: "Grading",
    isReady: (state) => state.grading_ready,
    countText: (state) => `Grading readiness: ${state.grading_ready ? "ready" : "blocked"}`,
  },
  {
    key: "review",
    label: "Review",
    isReady: (state) => state.review_ready,
    countText: (state) => `Review readiness: ${state.grade_suggestion_count} suggestions`,
  },
  {
    key: "export",
    label: "Export",
    isReady: (state) => state.export_ready,
    countText: (state) => `Export readiness: ${state.final_grade_count} final grades`,
  },
];

export function CustomControlledGradingRunClient({ assessmentId }: Readonly<{ assessmentId: number }>) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [gradingRuns, setGradingRuns] = useState<GradingRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState("draft");
  const [markingPolicy, setMarkingPolicy] = useState<MarkingPolicy>("general");
  const [questionPdf, setQuestionPdf] = useState<File | null>(null);
  const [solutionPdf, setSolutionPdf] = useState<File | null>(null);
  const [rubricPdf, setRubricPdf] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastGradingResult, setLastGradingResult] = useState<string | null>(null);

  const selectedRun = gradingRuns.find((run) => run.id === selectedRunId) ?? gradingRuns[0] ?? null;
  const workflowState = selectedRun?.workflow_state ?? null;

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
      const preferredRun = runData.find((run) => run.id === selectedRunId) ?? runData[0] ?? null;
      setSelectedRunId(preferredRun?.id ?? null);
      setStatus(preferredRun?.status ?? "draft");
      setMarkingPolicy(preferredRun?.marking_policy ?? "general");
      setNotes(preferredRun?.notes ?? "");
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
        marking_policy: markingPolicy,
      });
      setGradingRuns((current) => [run, ...current]);
      replaceRun(run);
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

  async function handleConfirmMaterials() {
    if (!selectedRun) {
      return;
    }
    await runAndRefresh(() => confirmGradingRunMaterials(selectedRun.id), "Failed to confirm uploaded materials");
  }

  async function handleConfirmQuestionsRubrics() {
    if (!selectedRun) {
      return;
    }
    await runAndRefresh(
      () => confirmGradingRunQuestionsRubrics(selectedRun.id),
      "Failed to confirm questions/rubrics",
    );
  }

  async function handleRunGatedMockGrading() {
    if (!selectedRun) {
      return;
    }
    setSaving(true);
    setError(null);
    setLastGradingResult(null);
    try {
      const result = await gradeGradingRunReadyRegionsMock(selectedRun.id);
      setLastGradingResult(
        `Gated mock grading completed: ${result.graded_count} graded, ${result.skipped_count} skipped, ${result.failed_count} failed.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run gated mock grading");
    } finally {
      setSaving(false);
    }
  }

  async function runAndRefresh(action: () => Promise<GradingRun>, fallback: string) {
    setSaving(true);
    setError(null);
    try {
      const updated = await action();
      replaceRun(updated);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
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
      const updated = await updateGradingRun(selectedRun.id, { status, notes, marking_policy: markingPolicy });
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
    setMarkingPolicy(updated.marking_policy ?? "general");
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
        <h2 className="text-xl font-semibold">Functional V0 workflow dashboard</h2>
        {workflowState ? (
          <>
            <p className="mt-2 text-sm text-slate-400">
              Backend-derived status: {workflowState.derived_status}. Manual status note: {selectedRun?.status ?? "not started"}.
            </p>
            <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {dashboardSections.map((section) => {
                const ready = section.isReady(workflowState);
                return (
                  <article key={section.key} className={`rounded border p-3 text-sm ${ready ? "border-emerald-700 bg-emerald-950/20" : "border-amber-700 bg-amber-950/20"}`}>
                    <p className="font-semibold">{section.label}</p>
                    <p>{ready ? "pass" : "warning/blocker"}</p>
                    <p className="text-slate-300">{section.countText(workflowState)}</p>
                  </article>
                );
              })}
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="rounded border border-slate-800 p-3">
                <h3 className="font-semibold">Workflow blockers</h3>
                {workflowState.blockers.length > 0 ? (
                  <ul className="mt-2 list-disc pl-5 text-sm text-amber-100">
                    {workflowState.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
                  </ul>
                ) : <p className="mt-2 text-sm text-emerald-200">No blockers.</p>}
              </div>
              <div className="rounded border border-slate-800 p-3">
                <h3 className="font-semibold">Next actions</h3>
                {workflowState.next_actions.length > 0 ? (
                  <ul className="mt-2 list-disc pl-5 text-sm text-cyan-100">
                    {workflowState.next_actions.map((action) => <li key={action}>{action}</li>)}
                  </ul>
                ) : <p className="mt-2 text-sm text-emerald-200">Workflow complete.</p>}
              </div>
            </div>
          </>
        ) : <EmptyState message="Start a custom controlled run to see blockers and next actions." />}
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
            <p>Marking policy: {selectedRun.marking_policy}</p>
            <p>Question PDF: {selectedRun.question_pdf_path ?? "pending"}</p>
            <p>Solution/model answer PDF: {selectedRun.solution_pdf_path ?? "pending"}</p>
            <p>Rubric PDF: {selectedRun.rubric_pdf_path ?? "pending"}</p>
            <p>Materials confirmed: {selectedRun.materials_confirmed_at ?? "pending"}</p>
            <p>Questions/rubrics confirmed: {selectedRun.questions_confirmed_at && selectedRun.rubrics_confirmed_at ? "yes" : "pending"}</p>
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
        <div className="flex flex-wrap gap-3">
          <button className={buttonClass} disabled={saving || !selectedRun} type="submit">
            Upload/confirm materials
          </button>
          <button className={buttonClass} disabled={saving || !selectedRun || !workflowState?.materials_uploaded} onClick={handleConfirmMaterials} type="button">
            Confirm uploaded materials
          </button>
        </div>
      </form>

      <section className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Confirm or create questions/rubrics</h2>
        <p className="text-sm text-slate-300">Create or edit canonical questions/model answers/rubrics on the assessment page, then confirm them here.</p>
        <div className="flex flex-wrap gap-3">
          <Link className={buttonClass} href={`/assessments/${assessmentId}`}>
            Confirm or create questions/rubrics, upload scripts, create answer regions manually, run mock grading
          </Link>
          <button className={buttonClass} disabled={saving || !selectedRun || !workflowState?.materials_confirmed} onClick={handleConfirmQuestionsRubrics} type="button">
            Confirm questions/rubrics
          </button>
        </div>
      </section>

      <section className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Grading readiness</h2>
        <p className="text-sm text-amber-100">Grading is blocked until readiness requirements pass.</p>
        <button className={buttonClass} disabled={saving || !selectedRun || !workflowState?.grading_ready} onClick={handleRunGatedMockGrading} type="button">
          Run gated mock grading
        </button>
        {lastGradingResult ? <p className="text-sm text-emerald-200">{lastGradingResult}</p> : null}
      </section>

      <form onSubmit={handleUpdateRun} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Current status and marking policy</h2>
        <p className="text-sm text-slate-400">Manual status is a note only. Backend readiness comes from the derived checklist above.</p>
        <label className="grid gap-2 text-sm">
          Marking policy selector
          <select
            className={inputClass}
            value={markingPolicy}
            onChange={(event) => setMarkingPolicy(event.target.value as MarkingPolicy)}
          >
            {markingPolicyOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <div className="grid gap-2 text-sm text-slate-300 md:grid-cols-3">
          {markingPolicyOptions.map((option) => <p key={option.value}>{option.description}</p>)}
        </div>
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
            Upload scripts and create answer regions manually
          </Link>
          <Link className={buttonClass} href={`/assessments/${assessmentId}/review`}>
            Review suggestions and approve selected
          </Link>
          <a className={buttonClass} href={getAssessmentFinalGradesExportUrl(assessmentId)}>
            Approve selected / export
          </a>
        </div>
        <p className="mt-3 text-sm text-slate-400">
          Run mock batch grading from this gated dashboard or use existing controlled grading actions only after teacher-confirmed materials are ready.
        </p>
      </section>
    </div>
  );
}
