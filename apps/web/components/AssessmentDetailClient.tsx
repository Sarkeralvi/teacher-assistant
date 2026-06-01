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
  suggestAnswerRegions,
  uploadSubmission,
  uploadSubmissionZip,
  type AnswerRegion,
  type Assessment,
  type DraftAnswerRegionSuggestion,
  type DraftQuestion,
  type FinalGrade,
  type Question,
  type QuestionImportJob,
  type ReviewQueueItem,
  type Submission,
  type SubmissionZipUploadResponse,
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
  const [zipUploadFile, setZipUploadFile] = useState<File | null>(null);
  const [zipIdentifierStrategy, setZipIdentifierStrategy] = useState<"basename" | "sequential">("basename");
  const [zipStudentNamePrefix, setZipStudentNamePrefix] = useState("");
  const [zipUploadResult, setZipUploadResult] = useState<SubmissionZipUploadResponse | null>(null);
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
  const [regionSuggestions, setRegionSuggestions] = useState<DraftAnswerRegionSuggestion[]>([]);
  const [regionSuggestionMessage, setRegionSuggestionMessage] = useState<string | null>(null);
  const [suggestingRegions, setSuggestingRegions] = useState(false);
  const [suggestionPageId, setSuggestionPageId] = useState<number | null>(null);
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
  const selectedZipUploadFileName = zipUploadFile?.name ?? "";
  const selectedQuestionImportFileName = questionImportFile?.name ?? "";
  const draftQuestions = questionImportJob?.draft_questions ?? [];
  const selectedDraftCount = Object.values(draftQuestionEdits).filter((draft) => draft.selected).length;

  const pageCountBySubmissionId = new Map<number, number>();
  const answerRegionsByPageId = new Map<number, AnswerRegion[]>();
  const answerRegionsByQuestionId = new Map<number, AnswerRegion[]>();
  const answerRegionsBySubmissionId = new Map<number, AnswerRegion[]>();
  for (const submission of submissions) {
    pageCountBySubmissionId.set(submission.id, submission.pages.length);
  }
  for (const region of answerRegions) {
    const pageRegions = answerRegionsByPageId.get(region.page_id) ?? [];
    pageRegions.push(region);
    answerRegionsByPageId.set(region.page_id, pageRegions);

    const questionRegions = answerRegionsByQuestionId.get(region.question_id) ?? [];
    questionRegions.push(region);
    answerRegionsByQuestionId.set(region.question_id, questionRegions);

    const submissionRegions = answerRegionsBySubmissionId.get(region.submission_id) ?? [];
    submissionRegions.push(region);
    answerRegionsBySubmissionId.set(region.submission_id, submissionRegions);
  }

  const finalizedRegionIds = new Set(reviewQueue.filter((item) => item.final_grade).map((item) => item.answer_region.id));
  const gradedRegionIds = new Set(
    reviewQueue.filter((item) => item.latest_grade_suggestion && !item.final_grade).map((item) => item.answer_region.id),
  );
  const mappedQuestionCount = answerRegionsByQuestionId.size;
  const mappedPageCount = answerRegionsByPageId.size;
  const mappedSubmissionCount = answerRegionsBySubmissionId.size;
  const unmappedQuestionCount = Math.max(questions.length - mappedQuestionCount, 0);
  const unmappedPageCount = Math.max(pages.length - mappedPageCount, 0);
  const unmappedSubmissionCount = Math.max(submissions.length - mappedSubmissionCount, 0);

  function statusForRegion(regionId: number): "finalized" | "graded" | "mapped" {
    if (finalizedRegionIds.has(regionId)) {
      return "finalized";
    }
    if (gradedRegionIds.has(regionId)) {
      return "graded";
    }
    return "mapped";
  }

  function statusForQuestion(questionId: number): string {
    const regions = answerRegionsByQuestionId.get(questionId) ?? [];
    if (regions.length === 0) {
      return "no regions";
    }
    if (regions.some((region) => finalizedRegionIds.has(region.id))) {
      return "finalized";
    }
    if (regions.some((region) => gradedRegionIds.has(region.id))) {
      return "graded";
    }
    return "mapped";
  }

  function statusForPage(pageId: number): string {
    const regions = answerRegionsByPageId.get(pageId) ?? [];
    if (regions.length === 0) {
      return "no regions";
    }
    if (regions.some((region) => finalizedRegionIds.has(region.id))) {
      return "finalized";
    }
    if (regions.some((region) => gradedRegionIds.has(region.id))) {
      return "graded";
    }
    return "mapped";
  }

  function formatPageLabel(submission: Submission, page: Submission["pages"][number]) {
    return `Submission #${submission.id} · ${submission.student_identifier} · page ${page.page_no}`;
  }

  function selectedPageContext() {
    const pageId = Number(selectedPageId);
    if (!pageId) {
      return null;
    }
    for (const submission of submissions) {
      const page = submission.pages.find((current) => current.id === pageId);
      if (page) {
        return { submission, page };
      }
    }
    return null;
  }

  const selectedPage = selectedPageContext();
  const selectedQuestion = questions.find((question) => question.id === Number(selectedQuestionId)) ?? null;

  function formatSuggestionLabel(suggestion: DraftAnswerRegionSuggestion) {
    return `Draft ${suggestion.draft_id} · ${suggestion.reason}`;
  }

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

  function handleZipUploadFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setZipUploadFile(file);
    if (file || error === "Choose a ZIP file before uploading scripts") {
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

  async function handleZipUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedFile =
      zipUploadFile ??
      ((new FormData(event.currentTarget).get("file") as File | null) ?? null);
    if (!selectedFile || selectedFile.size === 0) {
      setError("Choose a ZIP file before uploading scripts");
      return;
    }
    setUploading(true);
    setError(null);
    setZipUploadResult(null);
    try {
      const result = await uploadSubmissionZip(assessmentId, {
        file: selectedFile,
        student_identifier_strategy: zipIdentifierStrategy,
        student_name_prefix: zipStudentNamePrefix.trim(),
      });
      setZipUploadResult(result);
      setZipUploadFile(null);
      await load();
      event.currentTarget.reset();
    } catch (err) {
      setError(err instanceof Error ? `ZIP upload failed: ${err.message}` : "ZIP upload failed");
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

  async function handleSuggestAnswerRegions() {
    if (!selectedPage) {
      setError("Select a page before suggesting answer regions");
      return;
    }
    setSuggestingRegions(true);
    setError(null);
    setRegionSuggestionMessage(null);
    try {
      const response = await suggestAnswerRegions(selectedPage.page.id);
      setSuggestionPageId(selectedPage.page.id);
      setRegionSuggestions(response.suggestions);
      setRegionSuggestionMessage(response.message);
      if (response.suggestions[0]) {
        const first = response.suggestions[0];
        setRegionX(String(first.x));
        setRegionY(String(first.y));
        setRegionWidth(String(first.width));
        setRegionHeight(String(first.height));
      }
    } catch (err) {
      setRegionSuggestions([]);
      setRegionSuggestionMessage(null);
      setError(err instanceof Error ? err.message : "Failed to suggest answer regions");
    } finally {
      setSuggestingRegions(false);
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

      <form onSubmit={handleZipUpload} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Upload script ZIP</h2>
          <p className="text-sm text-slate-400">PDF, PNG, JPG, JPEG only. Unsupported files are reported and skipped; no grading or answer-region detection is run.</p>
        </div>
        <label className="grid gap-2 text-sm">
          Student identifier strategy
          <select className={inputClass} value={zipIdentifierStrategy} onChange={(event) => setZipIdentifierStrategy(event.target.value as "basename" | "sequential")}>
            <option value="basename">Use file basename</option>
            <option value="sequential">Generated sequential IDs</option>
          </select>
        </label>
        <input className={inputClass} placeholder="Student name prefix (optional)" value={zipStudentNamePrefix} onChange={(event) => setZipStudentNamePrefix(event.target.value)} />
        <input className={inputClass} name="file" type="file" accept=".zip,application/zip,application/x-zip-compressed" onChange={handleZipUploadFileChange} />
        {selectedZipUploadFileName ? (
          <p className="text-sm text-emerald-300">Selected ZIP file: {selectedZipUploadFileName}</p>
        ) : null}
        <button className={buttonClass} disabled={uploading || !zipUploadFile} type="submit">
          {uploading ? "Uploading script ZIP..." : "Upload script ZIP"}
        </button>
        {zipUploadResult ? (
          <div className="rounded border border-slate-800 p-3 text-sm">
            <p className="font-semibold">ZIP import summary</p>
            <p>imported_count: {zipUploadResult.imported_count}</p>
            <p>skipped_count: {zipUploadResult.skipped_count}</p>
            <p>failed_count: {zipUploadResult.failed_count}</p>
            {zipUploadResult.warnings.length > 0 ? <p>warnings: {zipUploadResult.warnings.join("; ")}</p> : null}
            {zipUploadResult.errors.length > 0 ? <p>errors: {zipUploadResult.errors.join("; ")}</p> : null}
          </div>
        ) : null}
      </form>

      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Submissions</h2>
        <p className="mt-1 text-sm text-slate-400">
          Total submissions: {submissions.length} · total pages: {pages.length} · mapped pages: {mappedPageCount} · unmapped pages: {unmappedPageCount}
        </p>
        {!loading && submissions.length === 0 ? <EmptyState message="No submissions yet." /> : null}
        <div className="mt-4 grid gap-3">
          {submissions.map((submission) => (
            <article key={submission.id} className="rounded border border-slate-800 p-4">
              <h3 className="font-semibold">Submission #{submission.id} · {submission.student_identifier}</h3>
              <p className="text-sm text-slate-400">{submission.student_name || "Unnamed student"} · {submission.status}</p>
              <p className="mt-1 text-xs text-slate-500">
                Pages: {pageCountBySubmissionId.get(submission.id) ?? submission.pages.length} · mapped regions: {(answerRegionsBySubmissionId.get(submission.id) ?? []).length}
              </p>
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
                    <span className="flex items-center justify-between gap-2">
                      <span>Page {page.page_no}</span>
                      <span className="rounded-full border border-slate-600 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-300">
                        {statusForPage(page.id)}
                      </span>
                    </span>
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
          <p className="text-sm text-slate-400">Map each answer region to the correct question before grading. Manual mapping remains the source of truth.</p>
          <p className="mt-1 text-sm text-slate-400">
            Total answer regions: {answerRegions.length} · mapped questions: {mappedQuestionCount}/{questions.length} · unmapped questions: {unmappedQuestionCount} · mapped submissions: {mappedSubmissionCount}/{submissions.length}
          </p>
        </div>
        <div className="grid gap-3 rounded border border-slate-800 p-3 text-sm text-slate-300 md:grid-cols-2">
          <p>Question status: {questions.length === 0 ? "no questions" : `${mappedQuestionCount} mapped, ${unmappedQuestionCount} unmapped`}</p>
          <p>Submission/page status: {mappedSubmissionCount} submissions mapped · {unmappedSubmissionCount} unmapped submissions</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button className={buttonClass} disabled={suggestingRegions || !selectedPage} type="button" onClick={() => void handleSuggestAnswerRegions()}>
            {suggestingRegions ? "Suggesting..." : "Suggest answer regions"}
          </button>
          <p className="text-sm text-amber-200">Draft suggestions only. Teacher must confirm before grading.</p>
        </div>
        {suggestionPageId === selectedPage?.page.id && regionSuggestionMessage ? (
          <p className="rounded border border-slate-700 bg-slate-950/30 p-3 text-sm text-slate-300">{regionSuggestionMessage}</p>
        ) : null}
        {suggestionPageId === selectedPage?.page.id && regionSuggestions.length > 0 ? (
          <div className="grid gap-2 rounded border border-slate-800 p-3 text-sm text-slate-300 md:grid-cols-2">
            {regionSuggestions.map((suggestion) => (
              <article key={suggestion.draft_id} className="rounded border border-slate-700 p-3">
                <p className="font-medium">{formatSuggestionLabel(suggestion)}</p>
                <p className="text-xs text-slate-500">x {suggestion.x}, y {suggestion.y}, w {suggestion.width}, h {suggestion.height}</p>
                <p className="text-xs text-slate-500">Confidence {suggestion.confidence} · {suggestion.source} · teacher confirmation required</p>
                <button
                  className="mt-2 rounded border border-cyan-700 px-3 py-1 text-xs text-cyan-200 hover:border-cyan-500"
                  type="button"
                  onClick={() => {
                    setRegionX(String(suggestion.x));
                    setRegionY(String(suggestion.y));
                    setRegionWidth(String(suggestion.width));
                    setRegionHeight(String(suggestion.height));
                  }}
                >
                  Use suggestion
                </button>
              </article>
            ))}
          </div>
        ) : null}
        {suggestionPageId === selectedPage?.page.id && regionSuggestions.length === 0 && regionSuggestionMessage ? (
          <p className="text-sm text-slate-400">No draft suggestions to apply yet.</p>
        ) : null}
        {selectedPage && selectedQuestion ? (
          <p className="rounded border border-emerald-900 bg-emerald-950/20 p-3 text-sm text-emerald-200">
            Currently mapping {formatPageLabel(selectedPage.submission, selectedPage.page)} to Question {selectedQuestion.question_no} ({statusForQuestion(selectedQuestion.id)}).
          </p>
        ) : null}
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
                  {formatPageLabel(submission, page)} · {statusForPage(page.id)}
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
              <option key={question.id} value={question.id}>Question {question.question_no} · {statusForQuestion(question.id)}</option>
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
          {answerRegions.map((region) => {
            const linkedSubmission = submissions.find((submission) => submission.id === region.submission_id) ?? null;
            const linkedPage = linkedSubmission?.pages.find((page) => page.id === region.page_id) ?? null;
            const linkedQuestion = questions.find((question) => question.id === region.question_id) ?? null;
            const regionStatus = statusForRegion(region.id);
            return (
              <a key={region.id} href={getAnswerRegionImageUrl(region.id)} target="_blank" rel="noreferrer" className="rounded border border-slate-700 p-3 text-sm hover:border-cyan-700">
                <span className="flex items-center justify-between gap-2">
                  <span>Answer region #{region.id}</span>
                  <span className="rounded-full border border-slate-600 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-300">
                    {regionStatus}
                  </span>
                </span>
                <span className="mt-1 block text-xs text-slate-500">
                  Question {linkedQuestion?.question_no ?? region.question_id} · Submission #{linkedSubmission?.id ?? region.submission_id} · page {linkedPage?.page_no ?? region.page_id}
                </span>
                <span className="block text-xs text-slate-500">x {region.x}, y {region.y}, w {region.width}, h {region.height}</span>
                <span className="block text-xs text-cyan-300 underline">Open crop preview</span>
              </a>
            );
          })}
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
