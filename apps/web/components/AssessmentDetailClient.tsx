"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import {
  createAnswerRegion,
  createQuestion,
  getAnswerRegionImageUrl,
  getAssessment,
  getSubmissionPageImageUrl,
  listAssessmentAnswerRegions,
  listQuestions,
  listSubmissions,
  uploadSubmission,
  type AnswerRegion,
  type Assessment,
  type Question,
  type Submission,
} from "../lib/api";

export function AssessmentDetailClient({ assessmentId }: Readonly<{ assessmentId: number }>) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [answerRegions, setAnswerRegions] = useState<AnswerRegion[]>([]);
  const [questionNo, setQuestionNo] = useState("");
  const [questionText, setQuestionText] = useState("");
  const [modelAnswer, setModelAnswer] = useState("");
  const [totalMarks, setTotalMarks] = useState("10.00");
  const [studentIdentifier, setStudentIdentifier] = useState("");
  const [studentName, setStudentName] = useState("");
  const [submissionFile, setSubmissionFile] = useState<File | null>(null);
  const [selectedPageId, setSelectedPageId] = useState("");
  const [selectedQuestionId, setSelectedQuestionId] = useState("");
  const [regionX, setRegionX] = useState("0");
  const [regionY, setRegionY] = useState("0");
  const [regionWidth, setRegionWidth] = useState("100");
  const [regionHeight, setRegionHeight] = useState("100");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [creatingRegion, setCreatingRegion] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pages = submissions.flatMap((submission) => submission.pages);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [assessmentData, questionData, submissionData, answerRegionData] = await Promise.all([
        getAssessment(assessmentId),
        listQuestions(assessmentId),
        listSubmissions(assessmentId),
        listAssessmentAnswerRegions(assessmentId),
      ]);
      setAssessment(assessmentData);
      setQuestions(questionData);
      setSubmissions(submissionData);
      setAnswerRegions(answerRegionData);
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

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!submissionFile) {
      setError("Choose a PDF or image file before uploading");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      await uploadSubmission(assessmentId, {
        student_identifier: studentIdentifier,
        student_name: studentName,
        file: submissionFile,
      });
      setStudentIdentifier("");
      setStudentName("");
      setSubmissionFile(null);
      event.currentTarget.reset();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload submission");
    } finally {
      setUploading(false);
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

  return (
    <div className="space-y-6">
      {loading ? <LoadingState /> : null}
      {error && <ErrorState message={error} />}
      {assessment ? (
        <section className="rounded border border-slate-800 bg-slate-900 p-5">
          <p className="text-sm text-slate-400">Assessment #{assessment.id}</p>
          <h1 className="text-3xl font-semibold">{assessment.title}</h1>
          <p className="mt-2 text-slate-400">{assessment.assessment_type} · {assessment.total_marks} marks · {assessment.status}</p>
        </section>
      ) : null}

      <form onSubmit={handleUpload} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Upload submission</h2>
          <p className="text-sm text-slate-400">Accepts PDF, PNG, JPG, or JPEG. This only stores pages; it does not grade or OCR.</p>
        </div>
        <input className={inputClass} name="student_identifier" placeholder="student_identifier" value={studentIdentifier} onChange={(event) => setStudentIdentifier(event.target.value)} required />
        <input className={inputClass} placeholder="Student name (optional)" value={studentName} onChange={(event) => setStudentName(event.target.value)} />
        <input className={inputClass} type="file" accept="application/pdf,image/png,image/jpeg" onChange={(event) => setSubmissionFile(event.target.files?.[0] ?? null)} required />
        <button className={buttonClass} disabled={uploading} type="submit">
          {uploading ? "Uploading..." : "Upload submission"}
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
          <p className="text-sm text-slate-400">Manually map a question to a rectangular crop on an uploaded page. No OCR or grading is run.</p>
        </div>
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

      <form onSubmit={handleSubmit} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Questions</h2>
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
