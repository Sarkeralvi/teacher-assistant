"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";

import { buttonClass, ErrorState, inputClass, LoadingState } from "./AppShell";
import {
  confirmReferenceExtraction,
  createCustomGradingRun,
  getAssessment,
  getGradingRun,
  getLocalAiStatus,
  getReferenceExtraction,
  listAssessmentGradingRuns,
  startReferenceExtraction,
  uploadGradingRunMaterials,
  type Assessment,
  type GradingRun,
  type LocalAiStatus,
  type ReferenceExtraction,
  type ReferenceQuestionConfirmation,
} from "../lib/api";

const EXPECTED_MODEL = "qwen3.6-35b-a3b-q4km";

const stageLabels: Record<string, string> = {
  not_started: "Not started",
  queued: "Waiting for the local worker",
  validating_materials: "Checking the three uploaded files",
  starting_gpu_ocr: "Releasing Qwen and loading PaddleOCR on the GPU",
  ocr_question_paper: "Reading the question paper",
  ocr_solution: "Reading the solution / model answer",
  ocr_rubric: "Reading the rubric",
  releasing_ocr_gpu: "Releasing PaddleOCR from the GPU",
  linking_reference_drafts: "Linking questions, solutions, and criteria with Qwen",
  teacher_review_required: "Drafts ready for teacher review",
  teacher_confirmed: "Teacher confirmed",
  failed: "Extraction stopped",
};

export function CustomControlledGradingRunClient({
  assessmentId,
}: Readonly<{ assessmentId: number; mode?: "custom_controlled" | "semi_automated" }>) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [run, setRun] = useState<GradingRun | null>(null);
  const [extraction, setExtraction] = useState<ReferenceExtraction | null>(null);
  const [localAi, setLocalAi] = useState<LocalAiStatus | null>(null);
  const [questionPdf, setQuestionPdf] = useState<File | null>(null);
  const [solutionPdf, setSolutionPdf] = useState<File | null>(null);
  const [rubricPdf, setRubricPdf] = useState<File | null>(null);
  const [drafts, setDrafts] = useState<ReferenceQuestionConfirmation[]>([]);
  const [draftSource, setDraftSource] = useState<string | null>(null);
  const [materialsConfirmed, setMaterialsConfirmed] = useState(false);
  const [draftsConfirmed, setDraftsConfirmed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const materialsUploaded = Boolean(
    run?.question_pdf_path && run.solution_pdf_path && run.rubric_pdf_path,
  );
  const extractionActive = extraction?.status === "queued" || extraction?.status === "running";
  const referencesConfirmed = Boolean(run?.questions_confirmed_at && run.rubrics_confirmed_at);
  const localProviderConfigured = Boolean(
    localAi?.real_providers_allowed && localAi.qwen.enabled && localAi.ocr.enabled,
  );

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [assessmentData, runs, localStatus] = await Promise.all([
        getAssessment(assessmentId),
        listAssessmentGradingRuns(assessmentId),
        getLocalAiStatus().catch(() => null),
      ]);
      const currentRun = runs.at(-1) ?? null;
      setAssessment(assessmentData);
      setRun(currentRun);
      setLocalAi(localStatus);
      if (currentRun) {
        setExtraction(await getReferenceExtraction(currentRun.id));
      } else {
        setExtraction(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this grading workspace");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [assessmentId]);

  useEffect(() => {
    if (!run || !extractionActive) {
      return;
    }
    const timer = window.setInterval(() => {
      void Promise.all([getReferenceExtraction(run.id), getGradingRun(run.id)])
        .then(([nextExtraction, nextRun]) => {
          setExtraction(nextExtraction);
          setRun(nextRun);
        })
        .catch((err: unknown) => {
          setError(err instanceof Error ? err.message : "Could not refresh extraction progress");
        });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [run?.id, extractionActive]);

  useEffect(() => {
    if (extraction?.status !== "succeeded" || extraction.questions.length === 0) {
      return;
    }
    const source = `${extraction.completed_at ?? "completed"}:${extraction.question_run_id}`;
    if (source === draftSource) {
      return;
    }
    setDrafts(
      extraction.questions.map((question) => ({
        id: question.id,
        question_number: question.question_number,
        question_text: question.question_text,
        model_answer: question.model_answer ?? "",
        total_marks: question.total_marks ?? "",
        criteria: question.criteria.map((criterion) => ({
          id: criterion.id,
          criterion_label: criterion.criterion_label,
          description: criterion.description,
          max_marks: criterion.max_marks ?? "",
        })),
      })),
    );
    setDraftSource(source);
  }, [extraction, draftSource]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const creatingWorkspace = run === null;
    if (creatingWorkspace && (!questionPdf || !solutionPdf || !rubricPdf)) {
      setError("Choose the question, solution/model answer, and rubric PDFs.");
      return;
    }
    if (!questionPdf && !solutionPdf && !rubricPdf) {
      setError("Choose at least one replacement PDF.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const activeRun =
        run ??
        (await createCustomGradingRun(assessmentId, {
          mode: "custom_controlled",
          notes: "Teacher-controlled local reference extraction.",
          marking_policy: "general",
        }));
      const updated = await uploadGradingRunMaterials(activeRun.id, {
        question_pdf: questionPdf,
        solution_pdf: solutionPdf,
        rubric_pdf: rubricPdf,
      });
      setRun(updated);
      setExtraction(await getReferenceExtraction(updated.id));
      setQuestionPdf(null);
      setSolutionPdf(null);
      setRubricPdf(null);
      setMaterialsConfirmed(false);
      setDraftsConfirmed(false);
      setDrafts([]);
      setDraftSource(null);
      event.currentTarget.reset();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not upload the reference PDFs");
    } finally {
      setBusy(false);
    }
  }

  async function handleStartExtraction() {
    if (!run || !materialsUploaded || !materialsConfirmed) {
      setError("Confirm that the three uploaded files are correct before extraction.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setExtraction(await startReferenceExtraction(run.id));
      setRun(await getGradingRun(run.id));
      setMaterialsConfirmed(false);
      setDraftsConfirmed(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start local extraction");
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmDrafts() {
    if (!run || extraction?.status !== "succeeded" || !draftsConfirmed) {
      setError("Review every draft and tick the teacher-confirmation box first.");
      return;
    }
    const validationError = validateDrafts(drafts);
    if (validationError) {
      setError(validationError);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const confirmed = await confirmReferenceExtraction(
        run.id,
        drafts.map((question) => ({
          ...question,
          question_number: question.question_number.trim(),
          question_text: question.question_text.trim(),
          model_answer: question.model_answer.trim(),
          criteria: question.criteria.map((criterion) => ({
            ...criterion,
            criterion_label: criterion.criterion_label.trim(),
            description: criterion.description.trim(),
          })),
        })),
      );
      setRun(confirmed);
      setExtraction(await getReferenceExtraction(run.id));
      setDraftsConfirmed(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm the reference drafts");
    } finally {
      setBusy(false);
    }
  }

  function updateQuestion(index: number, patch: Partial<ReferenceQuestionConfirmation>) {
    setDrafts((current) =>
      current.map((question, questionIndex) =>
        questionIndex === index ? { ...question, ...patch } : question,
      ),
    );
    setDraftsConfirmed(false);
  }

  function updateCriterion(
    questionIndex: number,
    criterionIndex: number,
    patch: Partial<ReferenceQuestionConfirmation["criteria"][number]>,
  ) {
    setDrafts((current) =>
      current.map((question, currentQuestionIndex) => {
        if (currentQuestionIndex !== questionIndex) {
          return question;
        }
        return {
          ...question,
          criteria: question.criteria.map((criterion, currentCriterionIndex) =>
            currentCriterionIndex === criterionIndex ? { ...criterion, ...patch } : criterion,
          ),
        };
      }),
    );
    setDraftsConfirmed(false);
  }

  const progressStep = useMemo(() => {
    if (referencesConfirmed) return 3;
    if (extraction?.status === "succeeded") return 2;
    if (materialsUploaded) return 1;
    return 0;
  }, [referencesConfirmed, extraction?.status, materialsUploaded]);

  if (loading) {
    return <LoadingState />;
  }

  return (
    <div className="grid gap-6">
      <header className="grid gap-4 rounded-2xl border border-slate-800 bg-slate-900/70 p-6 md:grid-cols-[1fr_auto] md:items-start">
        <div>
          <Link className="text-sm text-cyan-300 hover:text-cyan-200" href={`/assessments/${assessmentId}`}>
            ← Back to assessment
          </Link>
          <p className="mt-5 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
            Custom Controlled
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">Prepare grading references</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
            {assessment?.title ?? "Assessment"}: upload the three source documents once, extract them together, then review the drafts before any student grading.
          </p>
        </div>
        <RuntimeBadge status={localAi} />
      </header>

      <div className="rounded-xl border border-amber-700/60 bg-amber-950/30 px-5 py-4 text-sm text-amber-100">
        <p className="font-semibold">Teacher control is mandatory</p>
        <p className="mt-1 text-amber-100/80">
          OCR and Qwen create drafts only. This screen cannot grade students, approve marks, or create final grades.
        </p>
      </div>

      <Progress current={progressStep} />

      {error ? <ErrorState message={error} /> : null}

      <section className="grid gap-5 rounded-2xl border border-slate-800 bg-slate-900 p-6">
        <SectionHeading
          number="1"
          title="Upload the three reference PDFs"
          description="A grading workspace is created automatically. You do not need to upload the question paper anywhere else."
          complete={materialsUploaded}
        />
        <form className="grid gap-5" onSubmit={handleUpload}>
          <div className="grid gap-4 lg:grid-cols-3">
            <FilePicker
              id="question-pdf"
              title="Question paper"
              hint="What students were asked"
              selected={questionPdf}
              uploadedName={run?.question_pdf_name}
              disabled={busy || extractionActive}
              onChange={(event) => setQuestionPdf(event.target.files?.[0] ?? null)}
            />
            <FilePicker
              id="solution-pdf"
              title="Solution / model answer"
              hint="The expected working and answer"
              selected={solutionPdf}
              uploadedName={run?.solution_pdf_name}
              disabled={busy || extractionActive}
              onChange={(event) => setSolutionPdf(event.target.files?.[0] ?? null)}
            />
            <FilePicker
              id="rubric-pdf"
              title="Rubric"
              hint="Criteria and marks"
              selected={rubricPdf}
              uploadedName={run?.rubric_pdf_name}
              disabled={busy || extractionActive}
              onChange={(event) => setRubricPdf(event.target.files?.[0] ?? null)}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              className={buttonClass}
              disabled={busy || extractionActive || (!questionPdf && !solutionPdf && !rubricPdf)}
              type="submit"
            >
              {busy ? "Uploading…" : materialsUploaded ? "Upload selected replacement" : "Upload three PDFs"}
            </button>
            {materialsUploaded ? (
              <span className="text-sm text-emerald-300">All three references are stored.</span>
            ) : (
              <span className="text-sm text-slate-400">PDF only. Files remain on this machine.</span>
            )}
          </div>
        </form>
      </section>

      {materialsUploaded ? (
        <section className="grid gap-5 rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <SectionHeading
            number="2"
            title="Confirm files and extract drafts"
            description="The worker will use GPU OCR first, unload it, then load Qwen. No cloud provider or retry is allowed."
            complete={extraction?.status === "succeeded"}
          />

          {extractionActive || extraction?.status === "failed" || extraction?.status === "succeeded" ? (
            <ExtractionStatus extraction={extraction} />
          ) : null}

          {!extractionActive && extraction?.status !== "succeeded" ? (
            <div className="grid gap-4 rounded-xl border border-slate-700 bg-slate-950/40 p-4">
              <label className="flex items-start gap-3 text-sm text-slate-200">
                <input
                  className="mt-1 h-4 w-4 accent-cyan-400"
                  type="checkbox"
                  checked={materialsConfirmed}
                  onChange={(event) => setMaterialsConfirmed(event.target.checked)}
                />
                <span>
                  I confirm these are the correct question, solution/model answer, and rubric files. I authorize local draft extraction with PaddleOCR and {EXPECTED_MODEL}.
                </span>
              </label>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  className={buttonClass}
                  disabled={busy || !materialsConfirmed || !localProviderConfigured}
                  type="button"
                  onClick={() => void handleStartExtraction()}
                >
                  {busy ? "Starting…" : extraction?.status === "failed" ? "Start a new extraction" : "Confirm and extract drafts"}
                </button>
                {!localProviderConfigured ? (
                  <span className="text-sm text-amber-200">Local providers are not enabled in the backend.</span>
                ) : null}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {extraction?.status === "succeeded" && drafts.length > 0 ? (
        <section className="grid gap-5 rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <SectionHeading
            number="3"
            title="Review questions, model answers, and rubric"
            description="Edit anything OCR or Qwen got wrong. Confirmation creates the canonical grading references, but still does not grade a student."
            complete={referencesConfirmed}
          />

          {extraction.warnings.length > 0 ? (
            <div className="rounded-xl border border-amber-800 bg-amber-950/30 p-4 text-sm text-amber-100">
              <p className="font-semibold">Extraction warnings</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {extraction.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </div>
          ) : null}

          <div className="grid gap-5">
            {drafts.map((question, questionIndex) => (
              <article className="grid gap-4 rounded-xl border border-slate-700 bg-slate-950/35 p-5" key={question.id}>
                <div className="grid gap-4 md:grid-cols-[10rem_1fr]">
                  <label className="grid gap-2 text-sm text-slate-300">
                    Question number
                    <input
                      className={inputClass}
                      value={question.question_number}
                      onChange={(event) => updateQuestion(questionIndex, { question_number: event.target.value })}
                    />
                  </label>
                  <label className="grid gap-2 text-sm text-slate-300">
                    Total marks
                    <input
                      className={inputClass}
                      inputMode="decimal"
                      value={question.total_marks}
                      onChange={(event) => updateQuestion(questionIndex, { total_marks: event.target.value })}
                    />
                  </label>
                </div>
                <label className="grid gap-2 text-sm text-slate-300">
                  Question text
                  <textarea
                    className={`${inputClass} min-h-28`}
                    value={question.question_text}
                    onChange={(event) => updateQuestion(questionIndex, { question_text: event.target.value })}
                  />
                </label>
                <label className="grid gap-2 text-sm text-slate-300">
                  Model answer
                  <textarea
                    className={`${inputClass} min-h-40`}
                    value={question.model_answer}
                    onChange={(event) => updateQuestion(questionIndex, { model_answer: event.target.value })}
                  />
                </label>
                <div className="grid gap-3">
                  <div>
                    <h3 className="font-semibold">Rubric criteria</h3>
                    <p className="text-xs text-slate-400">Criterion marks must add up to the question total.</p>
                  </div>
                  {question.criteria.map((criterion, criterionIndex) => (
                    <div className="grid gap-3 rounded-lg border border-slate-800 p-4 md:grid-cols-[1fr_7rem]" key={criterion.id}>
                      <div className="grid gap-3">
                        <input
                          aria-label={`Criterion label ${criterion.id}`}
                          className={inputClass}
                          value={criterion.criterion_label}
                          onChange={(event) => updateCriterion(questionIndex, criterionIndex, { criterion_label: event.target.value })}
                        />
                        <textarea
                          aria-label={`Criterion description ${criterion.id}`}
                          className={inputClass}
                          value={criterion.description}
                          onChange={(event) => updateCriterion(questionIndex, criterionIndex, { description: event.target.value })}
                        />
                      </div>
                      <label className="grid content-start gap-2 text-xs text-slate-400">
                        Marks
                        <input
                          className={inputClass}
                          inputMode="decimal"
                          value={criterion.max_marks}
                          onChange={(event) => updateCriterion(questionIndex, criterionIndex, { max_marks: event.target.value })}
                        />
                      </label>
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>

          {!referencesConfirmed ? (
            <div className="grid gap-4 rounded-xl border border-emerald-800/70 bg-emerald-950/25 p-4">
              <label className="flex items-start gap-3 text-sm text-slate-200">
                <input
                  className="mt-1 h-4 w-4 accent-emerald-400"
                  type="checkbox"
                  checked={draftsConfirmed}
                  onChange={(event) => setDraftsConfirmed(event.target.checked)}
                />
                <span>I reviewed every question, model answer, mark total, and rubric criterion. Save these as the grading references.</span>
              </label>
              <div>
                <button
                  className={buttonClass}
                  disabled={busy || !draftsConfirmed}
                  type="button"
                  onClick={() => void handleConfirmDrafts()}
                >
                  {busy ? "Saving…" : "Confirm grading references"}
                </button>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-emerald-700 bg-emerald-950/30 p-4 text-emerald-100">
              <p className="font-semibold">Reference setup complete</p>
              <p className="mt-1 text-sm text-emerald-100/80">The teacher-confirmed questions and rubrics are ready for answer-evidence preparation.</p>
            </div>
          )}
        </section>
      ) : null}

      {referencesConfirmed ? (
        <section className="grid gap-4 rounded-2xl border border-cyan-800/70 bg-cyan-950/20 p-6 md:grid-cols-[1fr_auto] md:items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Next</p>
            <h2 className="mt-2 text-xl font-semibold">Upload student scripts and confirm answer evidence</h2>
            <p className="mt-1 text-sm text-slate-300">Student grading remains blocked until each answer region and OCR text is teacher-confirmed.</p>
          </div>
          <Link className={buttonClass} href={`/assessments/${assessmentId}`}>
            Continue to student evidence
          </Link>
        </section>
      ) : null}
    </div>
  );
}

function FilePicker({
  id,
  title,
  hint,
  selected,
  uploadedName,
  disabled,
  onChange,
}: Readonly<{
  id: string;
  title: string;
  hint: string;
  selected: File | null;
  uploadedName: string | null | undefined;
  disabled: boolean;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
}>) {
  const name = selected?.name ?? uploadedName;
  return (
    <div className="grid gap-3 rounded-xl border border-slate-700 bg-slate-950/35 p-4">
      <div>
        <p className="font-semibold">{title}</p>
        <p className="mt-1 text-xs text-slate-400">{hint}</p>
      </div>
      <input
        className="sr-only"
        id={id}
        type="file"
        accept=".pdf,application/pdf"
        disabled={disabled}
        onChange={onChange}
      />
      <label
        className={`cursor-pointer rounded-lg border border-dashed px-4 py-5 text-center text-sm transition ${disabled ? "cursor-not-allowed border-slate-800 text-slate-600" : "border-slate-600 text-cyan-300 hover:border-cyan-500 hover:bg-cyan-950/20"}`}
        htmlFor={id}
      >
        {name ? "Choose replacement" : "Choose PDF"}
      </label>
      <p className={`truncate text-sm ${name ? "text-emerald-300" : "text-slate-500"}`} title={name ?? undefined}>
        {name ?? "No file selected"}
      </p>
    </div>
  );
}

function SectionHeading({
  number,
  title,
  description,
  complete,
}: Readonly<{ number: string; title: string; description: string; complete: boolean }>) {
  return (
    <div className="flex items-start gap-4">
      <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full text-sm font-bold ${complete ? "bg-emerald-400 text-emerald-950" : "bg-slate-800 text-slate-200"}`}>
        {complete ? "✓" : number}
      </span>
      <div>
        <h2 className="text-xl font-semibold">{title}</h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-400">{description}</p>
      </div>
    </div>
  );
}

function Progress({ current }: Readonly<{ current: number }>) {
  const labels = ["Files", "Extract", "Review"];
  return (
    <ol className="grid gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-3 sm:grid-cols-3">
      {labels.map((label, index) => (
        <li className={`rounded-lg px-3 py-2 text-center text-xs font-semibold ${index < current ? "bg-emerald-950 text-emerald-300" : index === current ? "bg-cyan-950 text-cyan-200 ring-1 ring-cyan-700" : "text-slate-500"}`} key={label}>
          {index + 1}. {label}
        </li>
      ))}
    </ol>
  );
}

function ExtractionStatus({ extraction }: Readonly<{ extraction: ReferenceExtraction | null }>) {
  if (!extraction) return null;
  const failed = extraction.status === "failed";
  const complete = extraction.status === "succeeded";
  return (
    <div className={`grid gap-3 rounded-xl border p-4 ${failed ? "border-red-800 bg-red-950/30" : complete ? "border-emerald-800 bg-emerald-950/25" : "border-cyan-800 bg-cyan-950/20"}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-semibold">{stageLabels[extraction.stage] ?? extraction.stage.replaceAll("_", " ")}</p>
          <p className="mt-1 text-sm text-slate-300">
            {failed ? friendlyExtractionError(extraction.error) : complete ? "Review and edit the drafts below." : "You may leave this page; progress is saved automatically."}
          </p>
        </div>
        {!failed && !complete ? <span className="h-5 w-5 animate-spin rounded-full border-2 border-cyan-300 border-t-transparent" aria-label="Working" /> : null}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-400">
        <span>OCR calls: {extraction.ocr_call_count}</span>
        <span>Qwen calls: {extraction.qwen_call_count} / 1</span>
        <span>Provider: local only</span>
      </div>
    </div>
  );
}

function friendlyExtractionError(error: string | null): string {
  if (!error) return "Local extraction stopped before drafts were created.";
  if (error.toLowerCase().includes("timed out")) {
    return "Local Qwen took too long to finish. No partial draft was saved and no retry was made.";
  }
  return error;
}

function RuntimeBadge({ status }: Readonly<{ status: LocalAiStatus | null }>) {
  const phase = status?.ocr.available
    ? `OCR active · ${status.ocr.device}`
    : status?.qwen.available
      ? "Qwen active"
      : "Local models on demand";
  const configured = Boolean(status?.real_providers_allowed && status.qwen.enabled && status.ocr.enabled);
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm ${configured ? "border-emerald-800 bg-emerald-950/30 text-emerald-200" : "border-amber-800 bg-amber-950/30 text-amber-200"}`}>
      <p className="font-semibold">{configured ? "Local AI configured" : "Local AI unavailable"}</p>
      <p className="mt-1 text-xs opacity-80">{phase}</p>
    </div>
  );
}

function validateDrafts(drafts: ReferenceQuestionConfirmation[]): string | null {
  if (drafts.length === 0) return "No question drafts were extracted.";
  for (const question of drafts) {
    if (!question.question_number.trim() || !question.question_text.trim() || !question.model_answer.trim()) {
      return "Every question needs a number, question text, and model answer.";
    }
    const total = Number(question.total_marks);
    if (!Number.isFinite(total) || total <= 0) return `Enter a positive total for question ${question.question_number}.`;
    if (question.criteria.length === 0) return `Question ${question.question_number} needs at least one rubric criterion.`;
    let criterionTotal = 0;
    for (const criterion of question.criteria) {
      const marks = Number(criterion.max_marks);
      if (!criterion.criterion_label.trim() || !criterion.description.trim() || !Number.isFinite(marks) || marks <= 0) {
        return `Complete every rubric criterion for question ${question.question_number}.`;
      }
      criterionTotal += marks;
    }
    if (Math.abs(criterionTotal - total) > 0.0001) {
      return `Rubric marks for question ${question.question_number} add to ${criterionTotal}, not ${total}.`;
    }
  }
  return null;
}
