"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import {
  approveGradeSuggestion,
  editGradeSuggestion,
  getAnswerRegionImageUrl,
  getAssessment,
  getAssessmentFinalGradesExportUrl,
  getAssessmentReviewQueue,
  getAssessmentSummary,
  getCurrentUser,
  rejectGradeSuggestion,
  type Assessment,
  type AssessmentSummary,
  type FinalGrade,
  type ReviewQueueItem,
  type User,
} from "../lib/api";

type ReviewDraft = {
  finalScore: string;
  teacherComment: string;
};

export function AssessmentReviewClient({ assessmentId }: Readonly<{ assessmentId: number }>) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [summary, setSummary] = useState<AssessmentSummary | null>(null);
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [drafts, setDrafts] = useState<Record<number, ReviewDraft>>({});
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingRegionId, setSavingRegionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [assessmentData, queueData, summaryData, userData] = await Promise.all([
        getAssessment(assessmentId),
        getAssessmentReviewQueue(assessmentId),
        getAssessmentSummary(assessmentId),
        getCurrentUser().catch(() => null),
      ]);
      setAssessment(assessmentData);
      setItems(queueData);
      setSummary(summaryData);
      setCurrentUser(userData);
      setDrafts((current) => mergeDrafts(current, queueData));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load teacher review queue");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [assessmentId]);

  function updateDraft(answerRegionId: number, patch: Partial<ReviewDraft>) {
    setDrafts((current) => ({
      ...current,
      [answerRegionId]: {
        ...(current[answerRegionId] ?? { finalScore: "0.00", teacherComment: "" }),
        ...patch,
      },
    }));
  }

  async function handleApprove(item: ReviewQueueItem) {
    if (!item.latest_grade_suggestion) {
      setError("No AI GradeSuggestion is available to approve");
      return;
    }
    if (!currentUser) {
      setError("Login to approve or edit final grades.");
      return;
    }
    const draft = drafts[item.answer_region.id] ?? defaultDraft(item);
    setSavingRegionId(item.answer_region.id);
    setError(null);
    try {
      await approveGradeSuggestion(item.latest_grade_suggestion.id, {
        teacher_comment: draft.teacherComment || null,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve suggestion");
    } finally {
      setSavingRegionId(null);
    }
  }

  async function handleEdit(item: ReviewQueueItem) {
    if (!item.latest_grade_suggestion) {
      setError("No AI GradeSuggestion is available to edit");
      return;
    }
    if (!currentUser) {
      setError("Login to approve or edit final grades.");
      return;
    }
    const draft = drafts[item.answer_region.id] ?? defaultDraft(item);
    setSavingRegionId(item.answer_region.id);
    setError(null);
    try {
      await editGradeSuggestion(item.latest_grade_suggestion.id, {
        final_score: draft.finalScore,
        teacher_comment: draft.teacherComment || null,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save edited final grade");
    } finally {
      setSavingRegionId(null);
    }
  }

  async function handleReject(item: ReviewQueueItem) {
    if (!item.latest_grade_suggestion) {
      setError("No AI GradeSuggestion is available to reject");
      return;
    }
    if (!currentUser) {
      setError("Login to approve or edit final grades.");
      return;
    }
    const draft = drafts[item.answer_region.id] ?? defaultDraft(item);
    setSavingRegionId(item.answer_region.id);
    setError(null);
    try {
      await rejectGradeSuggestion(item.latest_grade_suggestion.id, {
        teacher_comment: draft.teacherComment || null,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject suggestion");
    } finally {
      setSavingRegionId(null);
    }
  }

  return (
    <div className="space-y-6">
      {loading ? <LoadingState /> : null}
      {error && <ErrorState message={error} />}
      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <Link className="text-sm text-cyan-300 underline" href={`/assessments/${assessmentId}`}>
          Back to assessment setup
        </Link>
        <h1 className="mt-3 text-3xl font-semibold">Teacher review and final grade approval</h1>
        <p className="mt-2 text-sm text-amber-200">
          AI GradeSuggestions are suggestions only. Teacher review is required before any FinalGrade is used.
        </p>
        <p className="mt-2 text-sm text-slate-300">
          Codex CLI provider is integrated in backend, but this demo button uses mock grading for safe local testing.
        </p>
        {assessment ? (
          <p className="mt-2 text-slate-400">
            {assessment.title} · {assessment.total_marks} marks · {assessment.status}
          </p>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-3">
          <a className={buttonClass} href={getAssessmentFinalGradesExportUrl(assessmentId)}>
            Export final grades (.xlsx)
          </a>
        </div>
      </section>

      {currentUser ? (
        <p className="rounded border border-emerald-800 bg-emerald-950/20 p-3 text-sm text-emerald-200">
          Logged-in teacher is used for approve/edit/reject. {currentUser.name} ({currentUser.email})
        </p>
      ) : (
        <p className="rounded border border-amber-800 bg-amber-950/20 p-3 text-sm text-amber-200">
          Login to approve or edit final grades. <Link className="underline" href="/login">Go to login</Link>
        </p>
      )}

      {summary ? <SummaryPanel summary={summary} assessmentId={assessmentId} /> : null}

      {!loading && items.length === 0 ? <EmptyState message="No answer regions are ready for review." /> : null}
      <div className="grid gap-4">
        {items.map((item) => (
          <ReviewCard
            key={item.answer_region.id}
            item={item}
            draft={drafts[item.answer_region.id] ?? defaultDraft(item)}
            saving={savingRegionId === item.answer_region.id}
            onDraftChange={(patch) => updateDraft(item.answer_region.id, patch)}
            onApprove={() => void handleApprove(item)}
            onEdit={() => void handleEdit(item)}
            onReject={() => void handleReject(item)}
          />
        ))}
      </div>
    </div>
  );
}

function SummaryPanel({ summary, assessmentId }: Readonly<{ summary: AssessmentSummary; assessmentId: number }>) {
  return (
    <section className="rounded border border-slate-800 bg-slate-900 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Assessment summary</h2>
          {summary.total_final_grades === 0 ? (
            <p className="mt-2 text-sm text-slate-400">Approve or edit at least one grade before export is useful.</p>
          ) : null}
        </div>
        <a className={buttonClass} href={getAssessmentFinalGradesExportUrl(assessmentId)}>
          Download final grades (.xlsx)
        </a>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <SummaryMetric label="Submissions" value={summary.total_submissions} />
        <SummaryMetric label="Answer regions" value={summary.total_answer_regions} />
        <SummaryMetric label="Reviewed" value={summary.total_final_grades} />
        <SummaryMetric label="Pending review" value={summary.pending_review_count} />
        <SummaryMetric label="Approved" value={summary.approved_count} />
        <SummaryMetric label="Edited" value={summary.edited_count} />
        <SummaryMetric label="Rejected" value={summary.rejected_count} />
        <SummaryMetric label="Average final score" value={summary.average_final_score ?? "—"} />
      </div>
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

function ReviewCard({
  item,
  draft,
  saving,
  onDraftChange,
  onApprove,
  onEdit,
  onReject,
}: Readonly<{
  item: ReviewQueueItem;
  draft: ReviewDraft;
  saving: boolean;
  onDraftChange: (patch: Partial<ReviewDraft>) => void;
  onApprove: () => void;
  onEdit: () => void;
  onReject: () => void;
}>) {
  const suggestion = item.latest_grade_suggestion;
  const finalGrade: FinalGrade | null = item.final_grade;
  const rubricBreakdown = suggestion?.raw_response_json.rubric_breakdown ?? [];
  return (
    <article className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">
            Submission {item.submission.student_identifier} · Question {item.question.question_no}
          </h2>
          <p className="text-sm text-slate-400">{item.submission.student_name || "Unnamed student"}</p>
          <p className="text-sm text-slate-400">Review status: {item.review_status}</p>
        </div>
        <a className="text-sm text-cyan-300 underline" href={getAnswerRegionImageUrl(item.answer_region.id)} target="_blank" rel="noreferrer">
          Open answer region image
        </a>
      </div>

      <img className="max-h-80 rounded border border-slate-700 object-contain" src={getAnswerRegionImageUrl(item.answer_region.id)} alt={`Answer region ${item.answer_region.id}`} />
      <p className="text-sm text-slate-300">Question text: {item.question.question_text}</p>

      {suggestion ? (
        <section className="grid gap-3 rounded border border-amber-800 bg-amber-950/20 p-3">
          <h3 className="font-semibold text-amber-200">AI suggested score — not final</h3>
          <p className="text-sm">AI suggested score/max_score: {suggestion.score} / {suggestion.max_score}</p>
          <p className="text-sm">confidence: {suggestion.confidence} · needs_review: {String(suggestion.needs_review)}</p>
          <p className="text-sm">feedback: {suggestion.feedback}</p>
          <p className="text-sm">review_flags: {(suggestion.raw_response_json.review_flags ?? []).join(", ")}</p>
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
        </section>
      ) : (
        <p className="rounded border border-slate-700 p-3 text-sm text-slate-400">No GradeSuggestion yet.</p>
      )}

      {finalGrade ? (
        <p className="rounded border border-emerald-800 bg-emerald-950/20 p-3 text-sm text-emerald-300">
          Current FinalGrade: {finalGrade.final_score} · {finalGrade.approval_status} · {finalGrade.teacher_comment || "no comment"}
        </p>
      ) : null}

      {suggestion ? (
        <section className="grid gap-3 rounded border border-slate-700 p-3">
          <h3 className="font-semibold">Teacher final grade action</h3>
          <div className="grid gap-2 md:grid-cols-2">
            <input className={inputClass} aria-label="Final score" placeholder="Final score" value={draft.finalScore} onChange={(event) => onDraftChange({ finalScore: event.target.value })} />
            <input className={inputClass} aria-label="Teacher comment" placeholder="Teacher comment" value={draft.teacherComment} onChange={(event) => onDraftChange({ teacherComment: event.target.value })} />
          </div>
          <div className="flex flex-wrap gap-2">
            <button className={buttonClass} type="button" disabled={saving} onClick={onApprove}>Approve AI suggestion</button>
            <button className={buttonClass} type="button" disabled={saving} onClick={onEdit}>Edit score and save final grade</button>
            <button className={buttonClass} type="button" disabled={saving} onClick={onReject}>Reject suggestion</button>
          </div>
        </section>
      ) : null}
    </article>
  );
}

function defaultDraft(item: ReviewQueueItem): ReviewDraft {
  return {
    finalScore: String(item.final_grade?.final_score ?? item.latest_grade_suggestion?.score ?? "0.00"),
    teacherComment: item.final_grade?.teacher_comment ?? "",
  };
}

function mergeDrafts(current: Record<number, ReviewDraft>, items: ReviewQueueItem[]) {
  const next = { ...current };
  for (const item of items) {
    if (!next[item.answer_region.id]) {
      next[item.answer_region.id] = defaultDraft(item);
    }
  }
  return next;
}
