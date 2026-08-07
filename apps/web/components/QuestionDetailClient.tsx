"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import { createRubric, getQuestion, listRubrics, type Question, type Rubric } from "../lib/api";

type CriterionDraft = {
  id: string;
  name: string;
  description: string;
  max_marks: string;
  depends_on: string;
  allow_follow_through: boolean;
};

const defaultCriteria: CriterionDraft[] = [
  {
    id: "concept",
    name: "Core concept",
    description: "Identifies the correct principle or idea.",
    max_marks: "2",
    depends_on: "",
    allow_follow_through: false,
  },
  {
    id: "method",
    name: "Method and reasoning",
    description: "Shows correct step-by-step reasoning.",
    max_marks: "3",
    depends_on: "",
    allow_follow_through: false,
  },
];

function buildRubricJson(totalMarks: string, criteria: CriterionDraft[]) {
  return {
    total_marks: Number(totalMarks),
    criteria: criteria.map((criterion) => ({
      id: criterion.id,
      name: criterion.name,
      description: criterion.description,
      max_marks: Number(criterion.max_marks),
      depends_on: criterion.depends_on
        .split(",")
        .map((criterionId) => criterionId.trim())
        .filter(Boolean),
      allow_follow_through: criterion.allow_follow_through,
    })),
  };
}

function criterionMarksSum(criteria: CriterionDraft[]) {
  return criteria.reduce((sum, criterion) => sum + (Number(criterion.max_marks) || 0), 0);
}

export function QuestionDetailClient({ questionId }: Readonly<{ questionId: number }>) {
  const [question, setQuestion] = useState<Question | null>(null);
  const [rubrics, setRubrics] = useState<Rubric[]>([]);
  const [version, setVersion] = useState("1");
  const [totalMarks, setTotalMarks] = useState("5");
  const [criteria, setCriteria] = useState<CriterionDraft[]>(defaultCriteria);
  const [isActive, setIsActive] = useState(true);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rubricJson = useMemo(() => buildRubricJson(totalMarks, criteria), [totalMarks, criteria]);
  const marksSum = useMemo(() => criterionMarksSum(criteria), [criteria]);

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
      setTotalMarks(String(questionData.total_marks));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load question");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [questionId]);

  function updateCriterion<Field extends keyof CriterionDraft>(
    index: number,
    field: Field,
    value: CriterionDraft[Field],
  ) {
    setCriteria((current) =>
      current.map((criterion, criterionIndex) =>
        criterionIndex === index ? { ...criterion, [field]: value } : criterion,
      ),
    );
  }

  function addCriterion() {
    setCriteria((current) => [
      ...current,
      {
        id: `criterion-${current.length + 1}`,
        name: "",
        description: "",
        max_marks: "1",
        depends_on: "",
        allow_follow_through: false,
      },
    ]);
  }

  function removeCriterion(index: number) {
    setCriteria((current) => current.filter((_, criterionIndex) => criterionIndex !== index));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createRubric(questionId, {
        version: Number(version),
        rubric_json: rubricJson,
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
        <h2 className="text-xl font-semibold">Rubric editor</h2>
        <p className="text-sm text-slate-400">
          Use prerequisite IDs when a later mark is valid only after an earlier criterion is
          fully met. Enable follow-through only when your marking policy explicitly allows it.
        </p>
        <input className={inputClass} placeholder="Version" type="number" min="1" value={version} onChange={(event) => setVersion(event.target.value)} required />
        <label className="grid gap-1 text-sm text-slate-300">
          Total marks
          <input className={inputClass} type="number" min="0.01" step="0.01" value={totalMarks} onChange={(event) => setTotalMarks(event.target.value)} required />
        </label>
        <div className="rounded border border-slate-800 p-3 text-sm text-slate-300">
          Criteria marks sum: <span className={marksSum === Number(totalMarks) ? "text-cyan-300" : "text-amber-300"}>{marksSum}</span>
        </div>

        <div className="grid gap-3">
          {criteria.map((criterion, index) => (
            <fieldset key={`${criterion.id}-${index}`} className="grid gap-2 rounded border border-slate-800 p-3">
              <div className="flex items-center justify-between gap-3">
                <legend className="text-sm font-semibold text-slate-200">Criterion {index + 1}</legend>
                <button className="text-sm text-red-300" type="button" onClick={() => removeCriterion(index)} disabled={criteria.length === 1}>
                  Remove criterion
                </button>
              </div>
              <input className={inputClass} placeholder="Criterion ID" value={criterion.id} onChange={(event) => updateCriterion(index, "id", event.target.value)} required />
              <input className={inputClass} placeholder="Criterion name" value={criterion.name} onChange={(event) => updateCriterion(index, "name", event.target.value)} required />
              <textarea className={inputClass} placeholder="Criterion description" value={criterion.description} onChange={(event) => updateCriterion(index, "description", event.target.value)} required />
              <input className={inputClass} placeholder="Criterion max marks" type="number" min="0.01" step="0.01" value={criterion.max_marks} onChange={(event) => updateCriterion(index, "max_marks", event.target.value)} required />
              <input
                className={inputClass}
                placeholder="Prerequisite criterion IDs, comma-separated"
                value={criterion.depends_on}
                onChange={(event) => updateCriterion(index, "depends_on", event.target.value)}
              />
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  checked={criterion.allow_follow_through}
                  onChange={(event) =>
                    updateCriterion(index, "allow_follow_through", event.target.checked)
                  }
                  type="checkbox"
                />
                Allow follow-through credit when a prerequisite is not fully met
              </label>
            </fieldset>
          ))}
        </div>
        <button className="rounded border border-cyan-700 px-3 py-2 text-sm text-cyan-200" type="button" onClick={addCriterion}>
          Add criterion
        </button>
        <details className="rounded border border-slate-800 p-3">
          <summary className="cursor-pointer text-sm text-slate-300">Raw JSON preview</summary>
          <pre className="mt-3 overflow-auto rounded bg-slate-950 p-3 text-sm text-slate-300">
            {JSON.stringify(rubricJson, null, 2)}
          </pre>
        </details>
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
