"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import {
  acceptQuestionImportDrafts,
  createAnswerRegion,
  createQuestion,
  deleteSubmission,
  finalizeGradeSuggestion,
  getAnswerRegionImageUrl,
  getAssessment,
  getAssessmentFinalGradesExportUrl,
  getAssessmentReviewQueue,
  getSubmissionPageImageUrl,
  gradeAnswerRegion,
  importQuestionsFromPaper,
  listAssessmentAnswerRegions,
  listQuestions,
  listSubmissions,
  uploadSubmission,
  type AnswerRegion,
  type Assessment,
  type DraftQuestion,
  type FinalGrade,
  type Question,
  type QuestionImportJob,
  type ReviewQueueItem,
  type Submission,
} from "../lib/api";
import { type DemoTeacher } from "../lib/demoTeacher";
import { DemoTeacherSelector } from "./DemoTeacherSelector";

type FinalizeDraft = {
  finalScore: string;
  teacherComment: string;
};

type DraftQuestionEdit = {
  selected: boolean;
  question_no: string;
  question_text: string;
  model_answer: string;
  total_marks: string;
};

export function AssessmentDetailClient({ assessmentId }: Readonly<{ assessmentId: number }>) {
  const uploadFormRef = useRef<HTMLFormElement | null>(null);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [answerRegions, setAnswerRegions] = useState<AnswerRegion[]>([]);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueItem[]>([]);
  const [questionNo, setQuestionNo] = useState("");
  const [questionText, setQuestionText] = useState("");
  const [modelAnswer, setModelAnswer] = useState("");
  const [totalMarks, setTotalMarks] = useState("10.00");
  const [studentIdentifier, setStudentIdentifier] = useState("");
  const [studentName, setStudentName] = useState("");
  const [submissionFile, setSubmissionFile] = useState<File | null>(null);
  const [questionImportFile, setQuestionImportFile] = useState<File | null>(null);
  const [questionImportJob, setQuestionImportJob] = useState<QuestionImportJob | null>(null);
  const [draftQuestionEdits, setDraftQuestionEdits] = useState<Record<string, DraftQuestionEdit>>({});
  const [importingQuestions, setImportingQuestions] = useState(false);
  const [acceptingQuestions, setAcceptingQuestions] = useState(false);
  const [selectedPageId, setSelectedPageId] = useState("");
  const [selectedQuestionId, setSelectedQuestionId] = useState("");
  const [regionX, setRegionX] = useState("0");
  const [regionY, setRegionY] = useState("0");
  const [regionWidth, setRegionWidth] = useState("100");
  const [regionHeight, setRegionHeight] = useState("100");
  const [finalizeDrafts, setFinalizeDrafts] = useState<Record<number, FinalizeDraft>>({});
  const [selectedTeacher, setSelectedTeacher] = useState<DemoTeacher | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [creatingRegion, setCreatingRegion] = useState(false);
  const [gradingRegionId, setGradingRegionId] = useState<number | null>(null);
  const [finalizingRegionId, setFinalizingRegionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pages = submissions.flatMap((submission) => submission.pages);
  const selectedUploadFileName = submissionFile?.name ?? "";
  const selectedQuestionImportFileName = questionImportFile?.name ?? "";
  const draftQuestions = questionImportJob?.draft_questions ?? [];
  const selectedDraftCount = Object.values(draftQuestionEdits).filter((draft) => draft.selected).length;

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [assessmentData, questionData, submissionData, answerRegionData, reviewQueueData] =
        await Promise.all([
          getAssessment(assessmentId),
          listQuestions(assessmentId),
          listSubmissions(assessmentId),
          listAssessmentAnswerRegions(assessmentId),
          getAssessmentReviewQueue(assessmentId),
        ]);
      setAssessment(assessmentData);
      setQuestions(questionData);
      setSubmissions(submissionData);
      setAnswerRegions(answerRegionData);
      setReviewQueue(reviewQueueData);
      setFinalizeDrafts((current) => mergeFinalizeDrafts(current, reviewQueueData));
      if (!selectedPageId && submissionData[0]?.pages[0]) {
        setSelectedPageId(String(submissionData[0].pages[0].id));
      }
      if (!selectedQuestionId && questionData[0]) {
        setSelectedQuestionId(String(questionData[0].id));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load assessment");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [assessmentId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createQuestion(assessmentId, {
        question_no: questionNo,
        question_text: questionText,
        model_answer: modelAnswer || null,
        total_marks: totalMarks,
      });
      setQuestionNo("");
      setQuestionText("");
      setModelAnswer("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create question");
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmissionFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setSubmissionFile(file);
    if (file || error === "Choose a PDF or image file before uploading") {
      setError(null);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedFile =
      submissionFile ??
      ((new FormData(event.currentTarget).get("file") as File | null) ?? null);
    if (!selectedFile || selectedFile.size === 0) {
      setError("Choose a PDF or image file before uploading");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      await uploadSubmission(assessmentId, {
        student_identifier: studentIdentifier.trim(),
        student_name: studentName.trim(),
        file: selectedFile,
      });
      setStudentIdentifier("");
      setStudentName("");
      setSubmissionFile(null);
      uploadFormRef.current?.reset();
      await load();
    } catch (err) {
      setError(err instanceof Error ? `Upload failed: ${err.message}` : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function handleQuestionImportFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setQuestionImportFile(file);
    if (file || error === "Choose a question paper PDF or image before importing") {
      setError(null);
    }
  }

  async function handleQuestionImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedFile = questionImportFile ?? ((new FormData(event.currentTarget).get("file") as File | null) ?? null);
    if (!selectedFile || selectedFile.size === 0) {
      setError("Choose a question paper PDF or image before importing");
      return;
    }
    setImportingQuestions(true);
    setError(null);
    try {
      const job = await importQuestionsFromPaper(assessmentId, selectedFile);
      setQuestionImportJob(job);
      setDraftQuestionEdits(createDraftQuestionEdits(job.draft_questions));
    } catch (err) {
      setError(err instanceof Error ? `Question import failed: ${err.message}` : "Question import failed");
    } finally {
      setImportingQuestions(false);
    }
  }

  function updateDraftQuestionEdit(draftId: string, patch: Partial<DraftQuestionEdit>) {
    setDraftQuestionEdits((current) => ({
      ...current,
      [draftId]: {
        ...(current[draftId] ?? emptyDraftQuestionEdit()),
        ...patch,
      },
    }));
  }

  async function handleAcceptDraftQuestions() {
    if (!questionImportJob) {
      setError("Import a question paper before creating selected questions");
      return;
    }
    const selectedDrafts = Object.entries(draftQuestionEdits)
      .filter(([, draft]) => draft.selected)
      .map(([draft_id, draft]) => ({
        draft_id,
        question_no: draft.question_no,
        question_text: draft.question_text,
        model_answer: draft.model_answer.trim() || null,
        total_marks: draft.total_marks,
      }));
    if (selectedDrafts.length === 0) {
      setError("Select at least one draft question to create.");
      return;
    }
    setAcceptingQuestions(true);
    setError(null);
    try {
      await acceptQuestionImportDrafts(questionImportJob.id, selectedDrafts);
      setQuestionImportJob(null);
      setDraftQuestionEdits({});
      setQuestionImportFile(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create selected questions");
    } finally {
      setAcceptingQuestions(false);
    }
  }

  async function handleCreateRegion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedPageId || !selectedQuestionId) {
      setError("Select page and question before creating an answer region");
      return;
    }
    setCreatingRegion(true);
    setError(null);
    try {
      await createAnswerRegion(Number(selectedPageId), {
        question_id: Number(selectedQuestionId),
        x: regionX,
        y: regionY,
        width: regionWidth,
        height: regionHeight,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create answer region");
    } finally {
      setCreatingRegion(false);
    }
  }

  async function handleMockGrade(answerRegionId: number) {
    setGradingRegionId(answerRegionId);
    setError(null);
    try {
      await gradeAnswerRegion(answerRegionId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create mock grade suggestion");
    } finally {
      setGradingRegionId(null);
    }
  }

  async function handleDeleteSubmission(submissionId: number) {
    if (!window.confirm("Delete this submission? This is for demo cleanup only.")) {
      return;
    }
    setError(null);
    try {
      await deleteSubmission(assessmentId, submissionId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete submission");
    }
  }

  async function handleFinalize(item: ReviewQueueItem, approvalStatus: "approved" | "edited" | "rejected") {
    if (!item.latest_grade_suggestion) {
      setError("Create a mock grade suggestion before finalizing");
      return;
    }
    if (!selectedTeacher) {
      setError("Select a demo teacher first.");
      return;
    }
    const draft = finalizeDrafts[item.answer_region.id] ?? defaultFinalizeDraft(item);
    setFinalizingRegionId(item.answer_region.id);
    setError(null);
    try {
      await finalizeGradeSuggestion(item.latest_grade_suggestion.id, {
        teacher_id: selectedTeacher.id,
        final_score: draft.finalScore,
        teacher_comment: draft.teacherComment || null,
        approval_status: approvalStatus,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to finalize grade");
    } finally {
      setFinalizingRegionId(null);
    }
  }

  function updateFinalizeDraft(answerRegionId: number, patch: Partial<FinalizeDraft>) {
    setFinalizeDrafts((current) => ({
      ...current,
      [answerRegionId]: {
        ...(current[answerRegionId] ?? { finalScore: "0.00", teacherComment: "" }),
        ...patch,
      },
    }));
  }

  return (
    <div className="space-y-6">
      {loading ? <LoadingState /> : null}
      {error && <ErrorState message={error} />}
      {assessment ? (
        <section className="rounded border border-slate-800 bg-slate-900 p-5">
          <p className="text-sm text-slate-400">Assessment #{assessment.id}</p>
          <h1 className="text-3xl font-semibold">{assessment.title}</h1>
          <p className="mt-2 text-slate-400">{assessment.assessment_type} · {assessment.total_marks} marks · {assessment.status}</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link className={buttonClass} href={`/assessments/${assessmentId}/grading-run`}>
              Custom Controlled Grading Run
            </Link>
            <Link className={buttonClass} href={`/assessments/${assessmentId}/review`}>
              Review & export final grades
            </Link>
            <a className={buttonClass} href={getAssessmentFinalGradesExportUrl(assessmentId)}>
              Download final grades (.xlsx)
            </a>
          </div>
          {reviewQueue.every((item) => !item.final_grade) ? (
            <p className="mt-3 text-sm text-slate-400">Approve or edit at least one grade before export is useful.</p>
          ) : null}
          <p className="mt-3 text-sm text-amber-200">Custom controlled mode: teacher confirmation required.</p>
        </section>
      ) : null}

      <DemoTeacherSelector onTeacherChange={setSelectedTeacher} />

      <form ref={uploadFormRef} onSubmit={handleUpload} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Upload submission</h2>
          <p className="text-sm text-slate-400">Accepts PDF, PNG, JPG, or JPEG. This only stores pages; it does not grade or OCR.</p>
        </div>
        <input className={inputClass} name="student_identifier" placeholder="student_identifier" value={studentIdentifier} onChange={(event) => setStudentIdentifier(event.target.value)} required />
        <input className={inputClass} placeholder="Student name (optional)" value={studentName} onChange={(event) => setStudentName(event.target.value)} />
        <input
          className={inputClass}
          name="file"
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          onChange={handleSubmissionFileChange}
          required
        />
        {selectedUploadFileName ? (
          <p className="text-sm text-emerald-300">Selected file: {selectedUploadFileName}</p>
        ) : null}
        <button className={buttonClass} disabled={uploading || !studentIdentifier.trim() || !submissionFile} type="submit">
          {uploading ? "Uploading submission..." : "Upload submission"}
        </button>
      </form>

      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Submissions</h2>
        {!loading && submissions.length === 0 ? <EmptyState message="No submissions yet." /> : null}
        <div className="mt-4 grid gap-3">
          {submissions.map((submission) => (
            <article key={submission.id} className="rounded border border-slate-800 p-4">
              <h3 className="font-semibold">Submission #{submission.id} · {submission.student_identifier}</h3>
              <p className="text-sm text-slate-400">{submission.student_name || "Unnamed student"} · {submission.status}</p>
              <button
                className="mt-3 rounded border border-red-800 px-3 py-2 text-sm text-red-200 hover:border-red-600"
                type="button"
                onClick={() => void handleDeleteSubmission(submission.id)}
              >
                Delete submission
              </button>
              <p className="mt-2 text-sm font-medium">Pages</p>
              <div className="mt-2 grid gap-2 md:grid-cols-3">
                {submission.pages.map((page) => (
                  <a key={page.id} href={getSubmissionPageImageUrl(page.id)} target="_blank" rel="noreferrer" className="rounded border border-slate-700 p-3 text-sm hover:border-cyan-700">
                    Page {page.page_no}
                    <span className="block text-xs text-slate-500">{page.image_path}</span>
                  </a>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <form onSubmit={handleCreateRegion} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Answer regions</h2>
          <p className="text-sm text-slate-400">Manually map a question to a rectangular crop on an uploaded page. No OCR or automatic detection is run.</p>
        </div>
        {!loading && questions.length === 0 ? (
          <p className="text-sm text-amber-200">Create a question before mapping answer regions.</p>
        ) : null}
        <label className="grid gap-2 text-sm">
          Select page
          <select className={inputClass} value={selectedPageId} onChange={(event) => setSelectedPageId(event.target.value)} required>
            <option value="">Select page</option>
            {submissions.map((submission) =>
              submission.pages.map((page) => (
                <option key={page.id} value={page.id}>
                  Submission #{submission.id} · {submission.student_identifier} · page {page.page_no}
                </option>
              )),
            )}
          </select>
        </label>
        <label className="grid gap-2 text-sm">
          Select question
          <select className={inputClass} value={selectedQuestionId} onChange={(event) => setSelectedQuestionId(event.target.value)} required>
            <option value="">Select question</option>
            {questions.map((question) => (
              <option key={question.id} value={question.id}>Question {question.question_no}</option>
            ))}
          </select>
        </label>
        <div>
          <p className="text-sm font-medium">Crop coordinates</p>
          <div className="mt-2 grid gap-2 md:grid-cols-4">
            <input className={inputClass} aria-label="Crop x" placeholder="x" value={regionX} onChange={(event) => setRegionX(event.target.value)} required />
            <input className={inputClass} aria-label="Crop y" placeholder="y" value={regionY} onChange={(event) => setRegionY(event.target.value)} required />
            <input className={inputClass} aria-label="Crop width" placeholder="width" value={regionWidth} onChange={(event) => setRegionWidth(event.target.value)} required />
            <input className={inputClass} aria-label="Crop height" placeholder="height" value={regionHeight} onChange={(event) => setRegionHeight(event.target.value)} required />
          </div>
        </div>
        <button className={buttonClass} disabled={creatingRegion || pages.length === 0 || questions.length === 0} type="submit">
          {creatingRegion ? "Creating..." : "Create answer region"}
        </button>

        {!loading && answerRegions.length === 0 ? <EmptyState message="No answer regions yet." /> : null}
        <div className="grid gap-2 md:grid-cols-2">
          {answerRegions.map((region) => (
            <a key={region.id} href={getAnswerRegionImageUrl(region.id)} target="_blank" rel="noreferrer" className="rounded border border-slate-700 p-3 text-sm hover:border-cyan-700">
              Cropped image #{region.id} · question #{region.question_id}
              <span className="block text-xs text-slate-500">page #{region.page_id} · x {region.x}, y {region.y}, w {region.width}, h {region.height}</span>
            </a>
          ))}
        </div>
      </form>

      <section className="grid gap-4 rounded border border-amber-900 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Teacher review queue</h2>
          <p className="text-sm text-amber-200">MOCK grading only. Teacher review is required before any FinalGrade is created.</p>
          <p className="text-sm text-slate-300">Codex CLI provider is integrated in backend, but this demo button uses mock grading for safe local testing.</p>
          {!selectedTeacher ? <p className="text-sm text-amber-200">Select a demo teacher first.</p> : null}
        </div>
        {!loading && reviewQueue.length === 0 ? <EmptyState message="No mapped answer regions to review yet." /> : null}
        <div className="grid gap-4">
          {reviewQueue.map((item) => (
            <ReviewQueueCard
              key={item.answer_region.id}
              item={item}
              draft={finalizeDrafts[item.answer_region.id] ?? defaultFinalizeDraft(item)}
              grading={gradingRegionId === item.answer_region.id}
              finalizing={finalizingRegionId === item.answer_region.id}
              onMockGrade={() => void handleMockGrade(item.answer_region.id)}
              onDraftChange={(patch) => updateFinalizeDraft(item.answer_region.id, patch)}
              onFinalize={(status) => void handleFinalize(item, status)}
            />
          ))}
        </div>
      </section>

      <section className="grid gap-4 rounded border border-amber-900 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Import questions from paper</h2>
          <p className="text-sm text-amber-200">Draft extraction. Teacher review required.</p>
          <p className="text-sm text-slate-400">Default extraction is mock/simple.</p>
          <p className="text-sm text-slate-400">Real Codex extraction must be explicitly enabled.</p>
          <p className="text-sm text-slate-400">If real extraction is not enabled, uploaded images will not be treated as understood question papers.</p>
          <p className="text-sm text-slate-400">Upload a question paper PDF/image to generate draft questions by question number. No real Codex extraction is enabled by default.</p>
        </div>
        <form onSubmit={handleQuestionImport} className="grid gap-3">
          <label className="grid gap-2 text-sm">
            Question paper file
            <input
              className={inputClass}
              name="file"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
              onChange={handleQuestionImportFileChange}
            />
          </label>
          {selectedQuestionImportFileName ? (
            <p className="text-sm text-emerald-300">Selected question paper file: {selectedQuestionImportFileName}</p>
          ) : null}
          <button className={buttonClass} disabled={importingQuestions || !questionImportFile} type="submit">
            {importingQuestions ? "Extracting draft questions..." : "Extract draft questions"}
          </button>
        </form>
        {questionImportJob ? (
          <div className="grid gap-3 rounded border border-slate-800 p-4">
            <p className="text-sm text-slate-300">Import job #{questionImportJob.id} · {questionImportJob.status} · provider: {questionImportJob.provider}</p>
            {questionImportJob.provider_warnings.length > 0 ? (
              <div className="rounded border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-100">
                <p className="font-semibold">Extraction warnings</p>
                <ul className="list-disc pl-5">
                  {questionImportJob.provider_warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p className="text-sm text-slate-400">{selectedDraftCount} selected draft questions</p>
            {draftQuestions.map((draft) => {
              const edit = draftQuestionEdits[draft.draft_id] ?? draftQuestionToEdit(draft);
              return (
                <article key={draft.draft_id} className="grid gap-2 rounded border border-slate-700 p-3">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={edit.selected}
                      onChange={(event) => updateDraftQuestionEdit(draft.draft_id, { selected: event.target.checked })}
                    />
                    Select draft question {draft.question_no}
                  </label>
                  <input className={inputClass} aria-label="Draft question number" value={edit.question_no} onChange={(event) => updateDraftQuestionEdit(draft.draft_id, { question_no: event.target.value })} />
                  <textarea className={inputClass} aria-label="Draft question text" value={edit.question_text} onChange={(event) => updateDraftQuestionEdit(draft.draft_id, { question_text: event.target.value })} />
                  <input className={inputClass} aria-label="Draft total marks" value={edit.total_marks} onChange={(event) => updateDraftQuestionEdit(draft.draft_id, { total_marks: event.target.value })} />
                  <textarea className={inputClass} aria-label="Draft model answer optional" placeholder="Model answer optional" value={edit.model_answer} onChange={(event) => updateDraftQuestionEdit(draft.draft_id, { model_answer: event.target.value })} />
                  <p className="text-xs text-slate-400">source page {draft.source_page} · confidence {draft.confidence} · needs_review: {String(draft.needs_review)}</p>
                  <p className="text-xs text-slate-500">Excerpt: {draft.source_text_excerpt}</p>
                </article>
              );
            })}
            <button className={buttonClass} disabled={acceptingQuestions || selectedDraftCount === 0} type="button" onClick={() => void handleAcceptDraftQuestions()}>
              {acceptingQuestions ? "Creating selected questions..." : "Create selected questions"}
            </button>
          </div>
        ) : null}
      </section>

      <form onSubmit={handleSubmit} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Questions</h2>
        <p className="text-sm text-slate-400">Manual question creation remains available.</p>
        <input className={inputClass} placeholder="Question number" value={questionNo} onChange={(event) => setQuestionNo(event.target.value)} required />
        <textarea className={inputClass} placeholder="Question text" value={questionText} onChange={(event) => setQuestionText(event.target.value)} required />
        <textarea className={inputClass} placeholder="Model answer (optional)" value={modelAnswer} onChange={(event) => setModelAnswer(event.target.value)} />
        <input className={inputClass} placeholder="Total marks" value={totalMarks} onChange={(event) => setTotalMarks(event.target.value)} required />
        <button className={buttonClass} disabled={submitting} type="submit">
          {submitting ? "Creating..." : "Create question"}
        </button>
      </form>

      {!loading && questions.length === 0 ? <EmptyState message="No questions yet." /> : null}
      <div className="grid gap-3">
        {questions.map((question) => (
          <Link key={question.id} href={`/questions/${question.id}`} className="rounded border border-slate-800 bg-slate-900 p-4 hover:border-cyan-700">
            <h2 className="text-lg font-semibold">Question {question.question_no}</h2>
            <p className="text-sm text-slate-400">{question.total_marks} marks</p>
            <p className="mt-2 line-clamp-2 text-slate-300">{question.question_text}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

function ReviewQueueCard({
  item,
  draft,
  grading,
  finalizing,
  onMockGrade,
  onDraftChange,
  onFinalize,
}: Readonly<{
  item: ReviewQueueItem;
  draft: FinalizeDraft;
  grading: boolean;
  finalizing: boolean;
  onMockGrade: () => void;
  onDraftChange: (patch: Partial<FinalizeDraft>) => void;
  onFinalize: (status: "approved" | "edited" | "rejected") => void;
}>) {
  const suggestion = item.latest_grade_suggestion;
  const finalGrade: FinalGrade | null = item.final_grade;
  const rubricBreakdown = suggestion?.raw_response_json.rubric_breakdown ?? [];
  return (
    <article className="grid gap-4 rounded border border-slate-700 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">Submission {item.submission.student_identifier} · Question {item.question.question_no}</h3>
          <p className="text-sm text-slate-400">Review status: {item.review_status}</p>
        </div>
        <a className="text-sm text-cyan-300 underline" href={getAnswerRegionImageUrl(item.answer_region.id)} target="_blank" rel="noreferrer">
          Open cropped answer image
        </a>
      </div>
      <img className="max-h-72 rounded border border-slate-800 object-contain" src={getAnswerRegionImageUrl(item.answer_region.id)} alt={`Cropped answer region ${item.answer_region.id}`} />

      {!suggestion ? (
        <button className={buttonClass} type="button" disabled={grading} onClick={onMockGrade}>
          {grading ? "Creating MOCK suggestion..." : "Mock Grade"}
        </button>
      ) : (
        <div className="grid gap-3 rounded border border-amber-800 bg-amber-950/20 p-3">
          <p className="font-semibold text-amber-200">MOCK suggestion — not real grading</p>
          <p className="text-sm">Score: {suggestion.score} / {suggestion.max_score}</p>
          <p className="text-sm">Confidence: {suggestion.confidence} · needs_review: {String(suggestion.needs_review)}</p>
          <p className="text-sm">Feedback: {suggestion.feedback}</p>
          <p className="text-sm">Flags: {(suggestion.raw_response_json.review_flags ?? []).join(", ")}</p>
          <div>
            <p className="text-sm font-medium">Rubric breakdown</p>
            <div className="mt-2 grid gap-2">
              {rubricBreakdown.map((criterion) => (
                <div key={criterion.criterion_id} className="rounded border border-slate-800 p-2 text-sm">
                  <p>{criterion.criterion}: {criterion.awarded_marks} / {criterion.max_marks}</p>
                  <p className="text-slate-400">{criterion.reason}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {suggestion ? (
        <div className="grid gap-3 rounded border border-slate-800 p-3">
          <p className="font-semibold">FinalGrade review</p>
          {finalGrade ? (
            <p className="text-sm text-emerald-300">Current final grade: {finalGrade.final_score} · {finalGrade.approval_status}</p>
          ) : null}
          <div className="grid gap-2 md:grid-cols-2">
            <input className={inputClass} aria-label="Final score" placeholder="Final score" value={draft.finalScore} onChange={(event) => onDraftChange({ finalScore: event.target.value })} />
            <input className={inputClass} aria-label="Teacher comment" placeholder="Teacher comment" value={draft.teacherComment} onChange={(event) => onDraftChange({ teacherComment: event.target.value })} />
          </div>
          <div className="flex flex-wrap gap-2">
            <button className={buttonClass} type="button" disabled={finalizing} onClick={() => onFinalize("approved")}>Finalize as approved</button>
            <button className={buttonClass} type="button" disabled={finalizing} onClick={() => onFinalize("edited")}>Finalize as edited</button>
            <button className={buttonClass} type="button" disabled={finalizing} onClick={() => onFinalize("rejected")}>Finalize as rejected</button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function defaultFinalizeDraft(item: ReviewQueueItem): FinalizeDraft {
  return {
    finalScore: String(item.final_grade?.final_score ?? item.latest_grade_suggestion?.score ?? "0.00"),
    teacherComment: item.final_grade?.teacher_comment ?? "",
  };
}

function draftQuestionToEdit(draft: DraftQuestion): DraftQuestionEdit {
  return {
    selected: true,
    question_no: draft.question_no,
    question_text: draft.question_text,
    model_answer: draft.model_answer ?? "",
    total_marks: String(draft.total_marks ?? "1.00"),
  };
}

function emptyDraftQuestionEdit(): DraftQuestionEdit {
  return {
    selected: false,
    question_no: "",
    question_text: "",
    model_answer: "",
    total_marks: "1.00",
  };
}

function createDraftQuestionEdits(drafts: DraftQuestion[]): Record<string, DraftQuestionEdit> {
  return Object.fromEntries(drafts.map((draft) => [draft.draft_id, draftQuestionToEdit(draft)]));
}

function mergeFinalizeDrafts(
  current: Record<number, FinalizeDraft>,
  items: ReviewQueueItem[],
): Record<number, FinalizeDraft> {
  const next = { ...current };
  for (const item of items) {
    if (!next[item.answer_region.id]) {
      next[item.answer_region.id] = defaultFinalizeDraft(item);
    }
  }
  return next;
}
