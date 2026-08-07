"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import {
  confirmGradingRunMaterials,
  confirmGradingRunQuestionsRubrics,
  createCohortDispatch,
  createCustomGradingRun,
  getAssessment,
  getAssessmentFinalGradesExportUrl,
  getGradingDispatchRun,
  getGradingQueueSummary,
  getLocalAiStatus,
  gradeGradingRunReadyRegionsMock,
  listAssessmentGradingRuns,
  listQuestions,
  listRubrics,
  preflightCohortDispatch,
  resumeGradingDispatchRun,
  stopGradingDispatchRun,
  updateGradingRun,
  uploadGradingRunMaterials,
  type Assessment,
  type BatchMockGradeResponse,
  type CohortDispatchPreflight,
  type CohortDispatchRequest,
  type GradingDispatchRun,
  type GradingQueueRun,
  type GradingRun,
  type GradingRunWorkflowState,
  type LocalAiStatus,
  type MarkingPolicy,
  type Question,
  type Rubric,
} from "../lib/api";

const workflowSteps = [
  "Start grading run",
  "Upload/confirm materials",
  "Confirm or create questions/rubrics",
  "Upload scripts",
  "Create answer regions manually",
  "Preflight and run draft grading",
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
    countText: (state) => `Answer regions created: ${state.answer_region_count} · mapped questions: ${state.mapped_question_count}/${state.question_count} · unmapped questions: ${state.unmapped_question_count}`,
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

export function CustomControlledGradingRunClient({
  assessmentId,
  mode = "custom_controlled",
}: Readonly<{ assessmentId: number; mode?: "custom_controlled" | "semi_automated" }>) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [gradingRuns, setGradingRuns] = useState<GradingRun[]>([]);
  const [canonicalUnits, setCanonicalUnits] = useState<Array<{ question: Question; activeRubrics: Rubric[] }>>([]);
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
  const [lastGradingResult, setLastGradingResult] = useState<BatchMockGradeResponse | null>(null);
  const [localAiStatus, setLocalAiStatus] = useState<LocalAiStatus | null>(null);
  const [gradingQueue, setGradingQueue] = useState<GradingQueueRun | null>(null);
  const [dispatchQuestionId, setDispatchQuestionId] = useState("");
  const [dispatchCallLimit, setDispatchCallLimit] = useState("5");
  const [draftOnlyConfirmed, setDraftOnlyConfirmed] = useState(false);
  const [dispatchPreflight, setDispatchPreflight] = useState<CohortDispatchPreflight | null>(null);
  const [dispatchRun, setDispatchRun] = useState<GradingDispatchRun | null>(null);
  const [dispatchBusy, setDispatchBusy] = useState(false);

  const isSemiAutomated = mode === "semi_automated";
  const modeTitle = isSemiAutomated ? "Semi-Automated Grading Run" : "Custom Controlled Grading Run";
  const startRunTitle = isSemiAutomated ? "Start semi-automated run" : "Start custom controlled run";
  const runNotes = isSemiAutomated
    ? "Semi-automated mode: teacher confirmation required."
    : "Custom controlled mode: teacher confirmation required.";

  const selectedRun = gradingRuns.find((run) => run.id === selectedRunId) ?? gradingRuns[0] ?? null;
  const workflowState = selectedRun?.workflow_state ?? null;
  const localQwenReady = Boolean(
    localAiStatus?.real_providers_allowed &&
    localAiStatus.cohort_model_grading_enabled &&
    localAiStatus.qwen.enabled &&
    localAiStatus.qwen.available,
  );

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [assessmentData, runData, questionData, localAiData, gradingQueueData] = await Promise.all([
        getAssessment(assessmentId),
        listAssessmentGradingRuns(assessmentId),
        listQuestions(assessmentId),
        getLocalAiStatus().catch(() => null),
        getGradingQueueSummary(assessmentId).catch(() => null),
      ]);
      const rubricData = await Promise.all(questionData.map(async (question) => ({
        question,
        activeRubrics: (await listRubrics(question.id)).filter((rubric) => rubric.is_active),
      })));
      setAssessment(assessmentData);
      setGradingRuns(runData);
      setCanonicalUnits(rubricData);
      setLocalAiStatus(localAiData);
      setGradingQueue(gradingQueueData);
      if (!dispatchQuestionId && questionData[0]) {
        setDispatchQuestionId(String(questionData[0].id));
      }
      const preferredRun = runData.find((run) => run.id === selectedRunId) ?? runData[0] ?? null;
      setSelectedRunId(preferredRun?.id ?? null);
      setStatus(preferredRun?.status ?? "draft");
      setMarkingPolicy(preferredRun?.marking_policy ?? "general");
      setNotes(preferredRun?.notes ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load grading run");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [assessmentId]);

  useEffect(() => {
    const storedRunId = window.localStorage.getItem(`teacher-assistant-dispatch-${assessmentId}`);
    if (!storedRunId) {
      return;
    }
    void getGradingDispatchRun(Number(storedRunId))
      .then(setDispatchRun)
      .catch(() => window.localStorage.removeItem(`teacher-assistant-dispatch-${assessmentId}`));
  }, [assessmentId]);

  useEffect(() => {
    if (!dispatchRun || !["queued", "running", "stopping"].includes(dispatchRun.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void getGradingDispatchRun(dispatchRun.id)
        .then(setDispatchRun)
        .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to refresh dispatch progress"));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [dispatchRun?.id, dispatchRun?.status]);

  async function handleStartRun() {
    setSaving(true);
    setError(null);
    try {
      const run = await createCustomGradingRun(assessmentId, {
        mode,
        notes: runNotes,
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
      setError("Start a grading run before uploading materials.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await uploadGradingRunMaterials(selectedRun.id, {
        question_pdf: questionPdf,
        solution_pdf: isSemiAutomated ? null : solutionPdf,
        rubric_pdf: isSemiAutomated ? null : rubricPdf,
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
      setLastGradingResult(result);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run bulk mock grading");
    } finally {
      setSaving(false);
    }
  }

  function cohortDispatchPayload(): CohortDispatchRequest | null {
    if (!selectedRun) {
      setError("Start and select a grading run before cohort preflight.");
      return null;
    }
    if (!gradingQueue?.id) {
      setError("Create a fresh grading queue on the assessment page before cohort preflight.");
      return null;
    }
    const questionId = Number(dispatchQuestionId);
    if (!questionId) {
      setError("Select one question for the cohort dispatch.");
      return null;
    }
    const callLimit = Number(dispatchCallLimit);
    if (!Number.isInteger(callLimit) || callLimit < 1 || callLimit > 25) {
      setError("Call limit must be a whole number from 1 to 25.");
      return null;
    }
    if (!draftOnlyConfirmed) {
      setError("Confirm that Qwen will create draft suggestions only before continuing.");
      return null;
    }
    return {
      queue_run_id: gradingQueue.id,
      grading_run_id: selectedRun.id,
      provider: "llama_cpp_qwen",
      expected_model: localAiStatus?.qwen.model ?? "qwen3.6-35b-a3b-q4km",
      call_limit: callLimit,
      draft_only_confirmed: true,
    };
  }

  async function handleCohortPreflight() {
    const payload = cohortDispatchPayload();
    const questionId = Number(dispatchQuestionId);
    if (!payload || !questionId) {
      return;
    }
    setDispatchBusy(true);
    setDispatchPreflight(null);
    setError(null);
    try {
      setDispatchPreflight(await preflightCohortDispatch(assessmentId, questionId, payload));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cohort preflight failed");
    } finally {
      setDispatchBusy(false);
    }
  }

  async function handleCreateCohortDispatch() {
    const payload = cohortDispatchPayload();
    const questionId = Number(dispatchQuestionId);
    if (!payload || !questionId || !dispatchPreflight) {
      setError("Run and review a cohort preflight before authorizing model calls.");
      return;
    }
    setDispatchBusy(true);
    setError(null);
    try {
      const run = await createCohortDispatch(assessmentId, questionId, payload);
      setDispatchRun(run);
      setDispatchPreflight(null);
      window.localStorage.setItem(`teacher-assistant-dispatch-${assessmentId}`, String(run.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start cohort dispatch");
    } finally {
      setDispatchBusy(false);
    }
  }

  async function handleStopDispatch() {
    if (!dispatchRun) {
      return;
    }
    setDispatchBusy(true);
    setError(null);
    try {
      setDispatchRun(await stopGradingDispatchRun(dispatchRun.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to stop cohort dispatch");
    } finally {
      setDispatchBusy(false);
    }
  }

  async function handleResumeDispatch() {
    if (!dispatchRun) {
      return;
    }
    setDispatchBusy(true);
    setError(null);
    try {
      setDispatchRun(await resumeGradingDispatchRun(dispatchRun.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resume cohort dispatch");
    } finally {
      setDispatchBusy(false);
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
      setError("Start a grading run before updating status.");
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
        <h1 className="text-3xl font-semibold">{modeTitle}</h1>
        <p className="mt-2 text-slate-300">{assessment?.title ?? "Loading assessment..."}</p>
        <p className="mt-3 rounded border border-amber-700 bg-amber-950/40 p-3 text-sm text-amber-100">
          {runNotes} This wizard organizes existing tools; it does not finalize grades automatically.
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
        ) : <EmptyState message="Start a grading run to see blockers and next actions." />}
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
            <h2 className="text-xl font-semibold">{startRunTitle}</h2>
            <p className="text-sm text-slate-400">Mode: {mode} · status: {selectedRun?.status ?? "not started"}</p>
          </div>
          <button className={buttonClass} disabled={saving} onClick={handleStartRun} type="button">
            {saving ? "Saving..." : startRunTitle}
          </button>
        </div>
        {!loading && gradingRuns.length === 0 ? <EmptyState message="No grading run started yet." /> : null}
        {selectedRun ? (
          <div className="mt-4 rounded border border-slate-800 p-3 text-sm text-slate-300">
            <p>Run #{selectedRun.id}</p>
            <p>Marking policy: {selectedRun.marking_policy}</p>
            <p>Mode: {selectedRun.mode}</p>
            <p>Question paper uploaded: {selectedRun.workflow_state.question_paper_uploaded ? "yes" : "no"}</p>
            <p>Drafts created: {selectedRun.workflow_state.drafts_created ? "yes" : "no"} · confirmed: {selectedRun.workflow_state.drafts_confirmed ? "yes" : "no"}</p>
            <p>Question PDF: {selectedRun.question_pdf_path ?? "pending"}</p>
            <p>Solution/model answer PDF: {selectedRun.solution_pdf_path ?? "pending"}</p>
            <p>Rubric PDF: {selectedRun.rubric_pdf_path ?? "pending"}</p>
            <p>Materials confirmed: {selectedRun.materials_confirmed_at ?? "pending"}</p>
            <p>Answer regions: {selectedRun.workflow_state.answer_region_count} total · mapped questions {selectedRun.workflow_state.mapped_question_count}/{selectedRun.workflow_state.question_count} · unmapped questions {selectedRun.workflow_state.unmapped_question_count}</p>
            <p>Mapped pages: {selectedRun.workflow_state.mapped_page_count}/{selectedRun.workflow_state.submission_page_count} · mapped submissions: {selectedRun.workflow_state.mapped_submission_count}/{selectedRun.workflow_state.submission_count}</p>
            <p>Questions/rubrics confirmed: {selectedRun.questions_confirmed_at && selectedRun.rubrics_confirmed_at ? "yes" : "pending"}</p>
          </div>
        ) : null}
      </section>

      <form onSubmit={handleUploadMaterials} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Upload/confirm materials</h2>
        <label className="grid gap-2 text-sm">
          {isSemiAutomated ? "Question paper PDF" : "Question PDF"}
          <input className={inputClass} type="file" accept="application/pdf,.pdf" onChange={handleFileChange(setQuestionPdf)} />
        </label>
        {!isSemiAutomated ? (
          <>
            <label className="grid gap-2 text-sm">
              Solution/model answer PDF
              <input className={inputClass} type="file" accept="application/pdf,.pdf" onChange={handleFileChange(setSolutionPdf)} />
            </label>
            <label className="grid gap-2 text-sm">
              Rubric PDF
              <input className={inputClass} type="file" accept="application/pdf,.pdf" onChange={handleFileChange(setRubricPdf)} />
            </label>
          </>
        ) : null}
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
        <h2 className="text-xl font-semibold">Confirm {isSemiAutomated ? "draft questions/rubrics" : "questions/rubrics"}</h2>
        <p className="text-sm text-slate-300">
          {isSemiAutomated
            ? "Upload a question paper on the assessment page, generate drafts, and confirm them here."
            : "Create or edit canonical questions/model answers/rubrics on the assessment page, then confirm them here."}
        </p>
        <div data-testid="canonical-grading-unit-table" className="overflow-x-auto rounded border border-slate-800">
          <table className="min-w-full text-left text-sm">
            <thead className="text-slate-300">
              <tr>
                <th className="p-2">label</th>
                <th className="p-2">max marks</th>
                <th className="p-2">model answer/rubric present</th>
                <th className="p-2">active rubric present</th>
                <th className="p-2">grading unit type</th>
              </tr>
            </thead>
            <tbody>
              {canonicalUnits.length === 0 ? (
                <tr><td className="p-2 text-amber-200" colSpan={5}>No canonical grading units yet.</td></tr>
              ) : canonicalUnits.map(({ question, activeRubrics }) => (
                <tr key={question.id} className="border-t border-slate-800">
                  <td className="p-2 font-medium">{question.question_no}</td>
                  <td className="p-2">{question.total_marks}</td>
                  <td className="p-2">{question.model_answer ? "model answer present" : "model answer missing"} / {activeRubrics.length > 0 ? "rubric present" : "rubric missing"}</td>
                  <td className="p-2">{activeRubrics.length > 0 ? "yes" : "no"}</td>
                  <td className="p-2">{gradingUnitType(question.question_no)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-sm text-amber-200">Founder/teacher must verify this canonical grading-unit table before grading. Labels like 1(a)(i) and max marks must match the paper/rubric.</p>
        <div className="flex flex-wrap gap-3">
          <Link className={buttonClass} href={`/assessments/${assessmentId}`}>
            {isSemiAutomated ? "Open assessment page for draft review" : "Confirm or create questions/rubrics, upload scripts, create answer regions manually, run mock grading"}
          </Link>
          <button className={buttonClass} disabled={saving || !selectedRun || !workflowState?.materials_confirmed} onClick={handleConfirmQuestionsRubrics} type="button">
            {isSemiAutomated ? "Confirm drafts" : "Confirm questions/rubrics"}
          </button>
        </div>
      </section>

      <section className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Grading readiness</h2>
        <p className="text-sm text-amber-100">Mock remains the default. Local Qwen requires a separate explicit preflight and draft-only authorization below.</p>
        <div className="flex flex-wrap gap-3">
          <button className={buttonClass} disabled={saving || !selectedRun || !workflowState?.grading_ready} onClick={handleRunGatedMockGrading} type="button">
            {saving ? "Grading..." : "Bulk mock grade ungraded answers"}
          </button>
          <Link className={buttonClass} href={`/assessments/${assessmentId}/review`}>
            Review queue
          </Link>
        </div>
        {lastGradingResult ? <MockGradingResultPanel result={lastGradingResult} /> : null}
      </section>

      <section className="grid gap-4 rounded border border-violet-800 bg-slate-900 p-5" data-testid="local-cohort-grading-panel">
        <div>
          <h2 className="text-xl font-semibold">Local Qwen cohort grading — draft suggestions only</h2>
          <p className="mt-1 text-sm text-amber-100">
            Text only: Qwen receives teacher-confirmed manual/OCR text, never answer images. Every suggestion still requires teacher review.
          </p>
          <p className="mt-1 text-sm text-red-200">No provider fallback, no automatic retry, no final-grade creation.</p>
        </div>

        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <SafetyStatus label="Real-provider gate" ready={Boolean(localAiStatus?.real_providers_allowed)} />
          <SafetyStatus label="Cohort execution gate" ready={Boolean(localAiStatus?.cohort_model_grading_enabled)} />
          <SafetyStatus label="Local Qwen enabled" ready={Boolean(localAiStatus?.qwen.enabled)} />
          <SafetyStatus label="Qwen reachable/model verified" ready={Boolean(localAiStatus?.qwen.available)} />
        </div>
        <div className="rounded border border-slate-800 p-3 text-sm text-slate-300">
          <p>Provider: llama_cpp_qwen</p>
          <p>Expected model alias: {localAiStatus?.qwen.model ?? "qwen3.6-35b-a3b-q4km"}</p>
          <p>Device: {localAiStatus?.qwen.device ?? "GPU/hybrid"}</p>
          <p>Status: {localQwenReady ? "ready for explicit preflight" : (localAiStatus?.qwen.detail ?? "Local AI status unavailable")}</p>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <label className="grid gap-2 text-sm">
            Question-wise cohort
            <select
              className={inputClass}
              value={dispatchQuestionId}
              onChange={(event) => {
                setDispatchQuestionId(event.target.value);
                setDispatchPreflight(null);
              }}
            >
              <option value="">Select a question</option>
              {canonicalUnits.map(({ question }) => (
                <option key={question.id} value={question.id}>{question.question_no} · {question.question_text}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm">
            Provider-call limit (server ceiling 25)
            <input
              className={inputClass}
              type="number"
              min={1}
              max={25}
              step={1}
              value={dispatchCallLimit}
              onChange={(event) => {
                setDispatchCallLimit(event.target.value);
                setDispatchPreflight(null);
              }}
            />
          </label>
          <div className="rounded border border-slate-800 p-3 text-sm text-slate-300">
            <p>Queue snapshot: {gradingQueue?.id ? `#${gradingQueue.id}` : "missing"}</p>
            <p>Queue items: {gradingQueue?.queued_item_count ?? 0}</p>
            <p>Marking policy copied from run: {selectedRun?.marking_policy ?? "not selected"}</p>
          </div>
        </div>

        <label className="flex items-start gap-3 rounded border border-amber-700 bg-amber-950/30 p-3 text-sm text-amber-100">
          <input
            className="mt-1"
            type="checkbox"
            checked={draftOnlyConfirmed}
            onChange={(event) => {
              setDraftOnlyConfirmed(event.target.checked);
              setDispatchPreflight(null);
            }}
          />
          <span>I authorize only the selected number of local Qwen calls and confirm that outputs are draft GradeSuggestions requiring teacher review.</span>
        </label>

        <div className="flex flex-wrap gap-3">
          <button
            className={buttonClass}
            type="button"
            disabled={dispatchBusy || !localQwenReady || !gradingQueue?.id || !selectedRun}
            onClick={() => void handleCohortPreflight()}
          >
            {dispatchBusy ? "Checking..." : "Run question-wise preflight"}
          </button>
          <Link className={buttonClass} href={`/assessments/${assessmentId}#grading-queue`}>
            Prepare or refresh grading queue
          </Link>
        </div>

        {dispatchPreflight ? (
          <section className="grid gap-3 rounded border border-cyan-800 bg-cyan-950/20 p-4" data-testid="cohort-preflight-result">
            <h3 className="text-lg font-semibold">Preflight result</h3>
            <div className="grid gap-2 text-sm md:grid-cols-4 lg:grid-cols-7">
              <SummaryMetric label="fresh" value={dispatchPreflight.fresh_count} />
              <SummaryMetric label="refused" value={dispatchPreflight.refused_count} />
              <SummaryMetric label="existing" value={dispatchPreflight.existing_count} />
              <SummaryMetric label="stale" value={dispatchPreflight.stale_count} />
              <SummaryMetric label="active" value={dispatchPreflight.active_job_count} />
              <SummaryMetric label="eligible" value={dispatchPreflight.eligible_count} />
              <SummaryMetric label="selected calls" value={dispatchPreflight.selected_call_count} />
            </div>
            <div className="text-sm text-slate-300">
              <p>Provider/model: {dispatchPreflight.provider} / {dispatchPreflight.model_name}</p>
              <p>Marking policy: {dispatchPreflight.marking_policy}</p>
              <p>Requested calls: {dispatchPreflight.requested_call_limit} · hard ceiling: {dispatchPreflight.server_call_ceiling}</p>
            </div>
            {dispatchPreflight.items.some((item) => item.reason) ? (
              <div className="max-h-48 overflow-y-auto rounded border border-slate-800 p-3 text-xs">
                {dispatchPreflight.items.filter((item) => item.reason).map((item) => (
                  <p key={item.queue_item_id}>Region #{item.answer_region_id}: {item.status} — {item.reason}</p>
                ))}
              </div>
            ) : null}
            <button
              className={buttonClass}
              type="button"
              disabled={dispatchBusy || dispatchPreflight.selected_call_count === 0}
              onClick={() => void handleCreateCohortDispatch()}
            >
              Authorize {dispatchPreflight.selected_call_count} draft-only Qwen call{dispatchPreflight.selected_call_count === 1 ? "" : "s"}
            </button>
          </section>
        ) : null}

        {dispatchRun ? <DispatchProgressPanel
          run={dispatchRun}
          busy={dispatchBusy}
          assessmentId={assessmentId}
          onStop={handleStopDispatch}
          onResume={handleResumeDispatch}
        /> : null}
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
          Run mock grading by default, or use the explicit capped local-Qwen preflight only after teacher-confirmed materials and evidence are ready.
        </p>
      </section>
    </div>
  );
}

function gradingUnitType(questionNo: string): string {
  const parentheticalCount = (questionNo.match(/\(/g) ?? []).length;
  return parentheticalCount >= 2 ? "subpart" : "whole sub-question";
}

function MockGradingResultPanel({ result }: Readonly<{ result: BatchMockGradeResponse }>) {
  return (
    <section className="rounded border border-cyan-800 bg-cyan-950/20 p-4 text-sm text-cyan-100">
      <h3 className="text-lg font-semibold">Bulk mock grading result</h3>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <SummaryMetric label="graded_count" value={result.graded_count} />
        <SummaryMetric label="skipped_count" value={result.skipped_count} />
        <SummaryMetric label="failed_count" value={result.failed_count} />
        <SummaryMetric label="created suggestions" value={result.created_grade_suggestion_ids.length} />
      </div>
      {result.errors.length > 0 ? (
        <ul className="mt-3 list-disc pl-5 text-red-200">
          {result.errors.map((error) => <li key={error}>{error}</li>)}
        </ul>
      ) : null}
    </section>
  );
}

function SummaryMetric({ label, value }: Readonly<{ label: string; value: string | number }>) {
  return (
    <div className="rounded border border-slate-800 p-3">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function SafetyStatus({ label, ready }: Readonly<{ label: string; ready: boolean }>) {
  return (
    <div className={`rounded border p-3 text-sm ${ready ? "border-emerald-700 bg-emerald-950/20 text-emerald-100" : "border-red-700 bg-red-950/20 text-red-100"}`}>
      <p className="font-semibold">{label}</p>
      <p>{ready ? "enabled / available" : "blocked"}</p>
    </div>
  );
}

function DispatchProgressPanel({
  run,
  busy,
  assessmentId,
  onStop,
  onResume,
}: Readonly<{
  run: GradingDispatchRun;
  busy: boolean;
  assessmentId: number;
  onStop: () => Promise<void>;
  onResume: () => Promise<void>;
}>) {
  const canStop = ["queued", "running", "stopping", "failed"].includes(run.status) && run.status !== "stopping";
  const canResume = ["stopped", "failed"].includes(run.status) && run.pending_count > 0;
  const attentionItems = run.items.filter((item) =>
    ["failed", "refused", "uncertain", "running", "pending"].includes(item.status),
  );
  return (
    <section className="grid gap-3 rounded border border-emerald-800 bg-emerald-950/10 p-4" data-testid="grading-dispatch-progress">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">Dispatch #{run.id}: {run.status}</h3>
          <p className="text-sm text-slate-300">{run.provider} / {run.model_name} · {run.marking_policy} marking</p>
          <p className="text-xs text-amber-200">Stop prevents the next call; it does not interrupt a call already running.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canStop ? <button className={buttonClass} disabled={busy} type="button" onClick={() => void onStop()}>Stop before next call</button> : null}
          {canResume ? <button className={buttonClass} disabled={busy} type="button" onClick={() => void onResume()}>Resume never-started items</button> : null}
          <Link className={buttonClass} href={`/assessments/${assessmentId}/review`}>Open review queue</Link>
        </div>
      </div>
      <div className="grid gap-2 md:grid-cols-4 lg:grid-cols-8">
        <SummaryMetric label="selected" value={run.selected_count} />
        <SummaryMetric label="calls started" value={run.calls_started} />
        <SummaryMetric label="remaining" value={run.pending_count} />
        <SummaryMetric label="running" value={run.running_count} />
        <SummaryMetric label="succeeded" value={run.succeeded_count} />
        <SummaryMetric label="failed" value={run.failed_count} />
        <SummaryMetric label="refused" value={run.refused_count} />
        <SummaryMetric label="uncertain" value={run.uncertain_count} />
      </div>
      {run.uncertain_count > 0 ? (
        <p className="rounded border border-red-700 bg-red-950/30 p-3 text-sm text-red-100">
          Uncertain means a worker stopped during a provider call. These items are never retried automatically; inspect them manually.
        </p>
      ) : null}
      {attentionItems.length > 0 ? (
        <div className="max-h-64 overflow-y-auto rounded border border-slate-800 p-3 text-sm">
          {attentionItems.map((item) => (
            <article key={item.id} className="border-b border-slate-800 py-2 last:border-b-0">
              <p>Region #{item.answer_region_id} · {item.status} · attempt {item.attempt_count}/1</p>
              {item.refusal_reason ? <p className="text-amber-200">{item.refusal_reason}</p> : null}
              {item.error ? <p className="text-red-200">{item.error}</p> : null}
              <Link className="text-cyan-300 underline" href={`/assessments/${assessmentId}#answer-region-${item.answer_region_id}`}>Inspect answer evidence</Link>
            </article>
          ))}
        </div>
      ) : <p className="text-sm text-emerald-200">No remaining or attention-required items.</p>}
    </section>
  );
}
