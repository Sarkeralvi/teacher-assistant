"use client";

import { FormEvent, useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import { createRubric, getQuestion, listRubrics, type Question, type Rubric } from "../lib/api";

const defaultRubricJson = JSON.stringify({ criteria: [] }, null, 2);

export function QuestionDetailClient({ questionId }: Readonly<{ questionId: number }>) {
  const [question, setQuestion] = useState<Question | null>(null);
  const [rubrics, setRubrics] = useState<Rubric[]>([]);
  const [version, setVersion] = useState("1");
  const [rubricJson, setRubricJson] = useState(defaultRubricJson);
  const [isActive, setIsActive] = useState(true);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [questionData, rubricData] = await Promise.all([
        getQuestion(questionId),
        listRubrics(questionId),
      ]);
      setQuestion(questionData);
      setRubrics(rubricData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load question");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [questionId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const parsed = JSON.parse(rubricJson) as unknown;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("Rubric JSON must be an object");
      }
      await createRubric(questionId, {
        version: Number(version),
        rubric_json: parsed as Record<string, unknown>,
        is_active: isActive,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create rubric");
    } finally {
      setSubmitting(false);
    }
  }

  const activeRubric = rubrics.find((rubric) => rubric.is_active);

  return (
    <div className="space-y-6">
      {loading ? <LoadingState /> : null}
      {error && <ErrorState message={error} />}
      {question ? (
        <section className="rounded border border-slate-800 bg-slate-900 p-5">
          <p className="text-sm text-slate-400">Question #{question.id}</p>
          <h1 className="text-3xl font-semibold">Question {question.question_no}</h1>
          <p className="mt-2 text-slate-300">{question.question_text}</p>
          <p className="mt-2 text-sm text-slate-400">{question.total_marks} marks</p>
          <p className="mt-3 text-sm text-cyan-300">
            Active rubric: {activeRubric ? `version ${activeRubric.version}` : "none"}
          </p>
        </section>
      ) : null}

      <form onSubmit={handleSubmit} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <input className={inputClass} placeholder="Version" type="number" min="1" value={version} onChange={(event) => setVersion(event.target.value)} required />
        <textarea className={`${inputClass} min-h-40 font-mono`} value={rubricJson} onChange={(event) => setRubricJson(event.target.value)} required />
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input checked={isActive} onChange={(event) => setIsActive(event.target.checked)} type="checkbox" />
          Active rubric
        </label>
        <button className={buttonClass} disabled={submitting} type="submit">
          {submitting ? "Creating..." : "Create rubric"}
        </button>
      </form>

      {!loading && rubrics.length === 0 ? <EmptyState message="No rubrics yet." /> : null}
      <div className="grid gap-3">
        {rubrics.map((rubric) => (
          <article key={rubric.id} className="rounded border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Rubric v{rubric.version}</h2>
              <span className={rubric.is_active ? "text-cyan-300" : "text-slate-500"}>
                {rubric.is_active ? "active" : "inactive"}
              </span>
            </div>
            <pre className="mt-3 overflow-auto rounded bg-slate-950 p-3 text-sm text-slate-300">
              {JSON.stringify(rubric.rubric_json, null, 2)}
            </pre>
          </article>
        ))}
      </div>
    </div>
  );
}
