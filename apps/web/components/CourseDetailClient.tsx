"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import { createAssessment, getCourse, listAssessments, type Assessment, type Course } from "../lib/api";

export function CourseDetailClient({ courseId }: Readonly<{ courseId: number }>) {
  const [course, setCourse] = useState<Course | null>(null);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [title, setTitle] = useState("");
  const [assessmentType, setAssessmentType] = useState("exam");
  const [totalMarks, setTotalMarks] = useState("100.00");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [courseData, assessmentData] = await Promise.all([
        getCourse(courseId),
        listAssessments(courseId),
      ]);
      setCourse(courseData);
      setAssessments(assessmentData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load course");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [courseId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createAssessment(courseId, {
        title,
        assessment_type: assessmentType,
        total_marks: totalMarks,
        status: "draft",
      });
      setTitle("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create assessment");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      {loading ? <LoadingState /> : null}
      {error && <ErrorState message={error} />}
      {course ? (
        <section className="rounded border border-slate-800 bg-slate-900 p-5">
          <p className="text-sm text-slate-400">Course #{course.id}</p>
          <h1 className="text-3xl font-semibold">{course.code}: {course.title}</h1>
          <p className="mt-2 text-slate-400">teacher_id: {course.teacher_id}</p>
        </section>
      ) : null}

      <form onSubmit={handleSubmit} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5 md:grid-cols-2">
        <input className={inputClass} placeholder="Assessment title" value={title} onChange={(event) => setTitle(event.target.value)} required />
        <input className={inputClass} placeholder="Type" value={assessmentType} onChange={(event) => setAssessmentType(event.target.value)} required />
        <input className={inputClass} placeholder="Total marks" value={totalMarks} onChange={(event) => setTotalMarks(event.target.value)} required />
        <button className={buttonClass} disabled={submitting} type="submit">
          {submitting ? "Creating..." : "Create assessment"}
        </button>
      </form>

      {!loading && assessments.length === 0 ? <EmptyState message="No assessments yet." /> : null}
      <div className="grid gap-3">
        {assessments.map((assessment) => (
          <Link key={assessment.id} href={`/assessments/${assessment.id}`} className="rounded border border-slate-800 bg-slate-900 p-4 hover:border-cyan-700">
            <h2 className="text-lg font-semibold">{assessment.title}</h2>
            <p className="text-sm text-slate-400">{assessment.assessment_type} · {assessment.total_marks} marks · {assessment.status}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
