"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import { createQuestion, getAssessment, listQuestions, type Assessment, type Question } from "../lib/api";

export function AssessmentDetailClient({ assessmentId }: Readonly<{ assessmentId: number }>) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [questionNo, setQuestionNo] = useState("");
  const [questionText, setQuestionText] = useState("");
  const [modelAnswer, setModelAnswer] = useState("");
  const [totalMarks, setTotalMarks] = useState("10.00");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [assessmentData, questionData] = await Promise.all([
        getAssessment(assessmentId),
        listQuestions(assessmentId),
      ]);
      setAssessment(assessmentData);
      setQuestions(questionData);
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

      <form onSubmit={handleSubmit} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
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
