"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import { createCourse, listCourses, type Course } from "../lib/api";

export function CoursesClient() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [teacherId, setTeacherId] = useState("");
  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [department, setDepartment] = useState("");
  const [semester, setSemester] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadCourses() {
    setLoading(true);
    setError(null);
    try {
      setCourses(await listCourses());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load courses");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCourses();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createCourse({
        teacher_id: Number(teacherId),
        code,
        title,
        department: department || null,
        semester: semester || null,
      });
      setCode("");
      setTitle("");
      await loadCourses();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create course");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Courses</h1>
        <p className="mt-2 text-slate-400">Create courses using a dev teacher_id from Users.</p>
      </div>

      <form onSubmit={handleSubmit} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5 md:grid-cols-2">
        <input className={inputClass} placeholder="teacher_id" type="number" value={teacherId} onChange={(event) => setTeacherId(event.target.value)} required />
        <input className={inputClass} placeholder="Course code" value={code} onChange={(event) => setCode(event.target.value)} required />
        <input className={inputClass} placeholder="Course title" value={title} onChange={(event) => setTitle(event.target.value)} required />
        <input className={inputClass} placeholder="Department" value={department} onChange={(event) => setDepartment(event.target.value)} />
        <input className={inputClass} placeholder="Semester" value={semester} onChange={(event) => setSemester(event.target.value)} />
        <button className={buttonClass} disabled={submitting} type="submit">
          {submitting ? "Creating..." : "Create course"}
        </button>
      </form>

      {error && <ErrorState message={error} />}
      {loading ? <LoadingState /> : null}
      {!loading && courses.length === 0 ? <EmptyState message="No courses yet." /> : null}
      <div className="grid gap-3 md:grid-cols-2">
        {courses.map((course) => (
          <Link key={course.id} href={`/courses/${course.id}`} className="rounded border border-slate-800 bg-slate-900 p-4 hover:border-cyan-700">
            <h2 className="text-lg font-semibold">{course.code}: {course.title}</h2>
            <p className="text-sm text-slate-400">teacher_id: {course.teacher_id}</p>
            <p className="text-sm text-slate-400">{course.department ?? "No department"} · {course.semester ?? "No semester"}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
