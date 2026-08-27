"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import { AuthenticatedAnswerRegionImage } from "./AuthenticatedAnswerRegionImage";
import {
  approveGradeSuggestion,
  approveSelectedFinalGrades,
  editGradeSuggestion,
  getAssessment,
  getAssessmentFinalGradesExportUrl,
  getAssessmentReviewQueue,
  getAssessmentSummary,
  getCurrentUser,
  rejectGradeSuggestion,
  type Assessment,
  type AssessmentSummary,
  type BatchApproveFinalGradesResponse,
  type FinalGrade,
  type ReviewQueueItem,
  type User,
} from "../lib/api";

type ReviewDraft = {
  finalScore: string;
  teacherComment: string;
};

type ReviewStatusFilter = "all" | "ungraded" | "suggested" | "finalized" | "approved" | "edited" | "rejected";
const CURRENT_REAL_GRADING_PROMPT_VERSION = "real-grading-v3";

export function AssessmentReviewClient({ assessmentId }: Readonly<{ assessmentId: number }>) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [summary, setSummary] = useState<AssessmentSummary | null>(null);
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [drafts, setDrafts] = useState<Record<number, ReviewDraft>>({});
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [statusFilter, setStatusFilter] = useState<ReviewStatusFilter>("all");
  const [selectedSuggestionIds, setSelectedSuggestionIds] = useState<number[]>([]);
  const [batchApproveResult, setBatchApproveResult] = useState<BatchApproveFinalGradesResponse | null>(null);
  const [batchApproving, setBatchApproving] = useState(false);
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
      setSelectedSuggestionIds((current) => {
        const approvableIds = new Set(queueData.filter(isSelectableForBatchApprove).map((item) => item.latest_grade_suggestion!.id));
        return current.filter((id) => approvableIds.has(id));
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load teacher review queue");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [assessmentId]);

  const statusCounts = getStatusCounts(items);
  const filteredItems = items.filter((item) => itemMatchesStatusFilter(item, statusFilter));
  const visibleSelectableItems = filteredItems.filter(isSelectableForBatchApprove);
  const visibleSelectableIds = visibleSelectableItems.map((item) => item.latest_grade_suggestion!.id);
  const selectedCount = selectedSuggestionIds.length; // selected count
  const hasVisibleSelectableItems = visibleSelectableIds.length > 0;

  function updateDraft(answerRegionId: number, patch: Partial<ReviewDraft>) {
    setDrafts((current) => ({
      ...current,
      [answerRegionId]: {
        ...(current[answerRegionId] ?? { finalScore: "0.00", teacherComment: "" }),
        ...patch,
      },
    }));
  }

  function toggleSelectedSuggestion(suggestionId: number, checked: boolean) {
    setSelectedSuggestionIds((current) => {
      if (checked) {
        return current.includes(suggestionId) ? current : [...current, suggestionId];
      }
      return current.filter((id) => id !== suggestionId);
    });
  }

  function selectAllVisibleSuggestedItems() {
    setSelectedSuggestionIds((current) => Array.from(new Set([...current, ...visibleSelectableIds])));
  }

  function clearSelection() {
    setSelectedSuggestionIds([]);
  }

  async function handleApproveSelected() {
    if (selectedSuggestionIds.length === 0) {
      setError("Select at least one suggested item to approve.");
      return;
    }
    if (!currentUser) {
      setError("Login to approve or edit final grades.");
      return;
    }
    setBatchApproving(true);
    setBatchApproveResult(null);
    setError(null);
    try {
      const result = await approveSelectedFinalGrades(assessmentId, {
        grade_suggestion_ids: selectedSuggestionIds,
      });
      setBatchApproveResult(result);
      setSelectedSuggestionIds([]);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve selected suggestions");
    } finally {
      setBatchApproving(false);
    }
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
      <section className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
        <Link className="text-sm text-cyan-300 underline" href={`/assessments/${assessmentId}`}>
          Back to assessment setup
        </Link>
        <h1 className="mt-3 text-3xl font-semibold">Review local Qwen draft grades</h1>
        <p className="mt-2 text-sm text-amber-200">
          Every score here is a review-required draft. Approve, edit, or reject each one before it can appear in the final export.
        </p>
        {assessment ? (
          <p className="mt-2 text-slate-400">
            {assessment.title} · {assessment.total_marks} marks · {assessment.status}
          </p>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-3">
          <a className={buttonClass} href={getAssessmentFinalGradesExportUrl(assessmentId)}>
            Export approved grades (.xlsx)
          </a>
        </div>
        <p className="mt-3 text-xs text-slate-400">Pending suggestions and rejected drafts are excluded from the workbook.</p>
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

      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <label className="grid gap-2 text-sm md:max-w-xs">
            Review queue filter
            <select data-testid="review-queue-filter" className={inputClass} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as ReviewStatusFilter)}>
              <option value="all">All statuses ({statusCounts.all})</option>
              <option value="ungraded">ungraded ({statusCounts.ungraded})</option>
              <option value="suggested">suggested ({statusCounts.suggested})</option>
              <option value="finalized">finalized ({statusCounts.finalized})</option>
              <option value="approved">approved ({statusCounts.approved})</option>
              <option value="edited">edited ({statusCounts.edited})</option>
              <option value="rejected">rejected ({statusCounts.rejected})</option>
            </select>
          </label>
          {filteredItems[0] ? (
            <a className={buttonClass} href={`#review-item-${filteredItems[0].answer_region.id}`}>
              Next item to review
            </a>
          ) : null}
        </div>
        <p className="mt-3 text-sm text-slate-400">
          Review the answer image, criterion marks, evidence, and flags before taking an action.
        </p>
        <div className="mt-4 grid gap-3 rounded border border-slate-800 p-3 text-sm">
          <div className="flex flex-wrap items-center gap-3">
            <button data-testid="select-all-visible-suggested-items-button" className={buttonClass} type="button" disabled={!hasVisibleSelectableItems} onClick={selectAllVisibleSuggestedItems}>
              Select all visible suggested items
            </button>
            <button className={buttonClass} type="button" disabled={selectedCount === 0} onClick={clearSelection}>
              Clear selection
            </button>
            <button data-testid="approve-selected-button" className={buttonClass} type="button" disabled={batchApproving || selectedCount === 0} onClick={() => void handleApproveSelected()}>
              {batchApproving ? "Approving selected..." : "Approve selected"}
            </button>
            <span className="text-slate-300">{selectedCount} selected count</span>
          </div>
          {!hasVisibleSelectableItems ? (
            <p className="text-slate-400">No visible suggested items can be selected in this filter.</p>
          ) : null}
          {selectedCount === 0 ? (
            <p className="text-slate-400">Select at least one suggested item to approve.</p>
          ) : null}
        </div>
      </section>

      {batchApproveResult ? <BatchApproveResultPanel result={batchApproveResult} /> : null}
      {!loading && filteredItems.length === 0 ? <EmptyState message="No items in this filter" /> : null}
      <div className="grid gap-4">
        {filteredItems.map((item) => (
          <ReviewCard
            key={item.answer_region.id}
            item={item}
            draft={drafts[item.answer_region.id] ?? defaultDraft(item)}
            saving={savingRegionId === item.answer_region.id}
            onDraftChange={(patch) => updateDraft(item.answer_region.id, patch)}
            onApprove={() => void handleApprove(item)}
            onEdit={() => void handleEdit(item)}
            onReject={() => void handleReject(item)}
            selected={Boolean(item.latest_grade_suggestion && selectedSuggestionIds.includes(item.latest_grade_suggestion.id))}
            onSelectionChange={(checked) => {
              if (item.latest_grade_suggestion) {
                toggleSelectedSuggestion(item.latest_grade_suggestion.id, checked);
              }
            }}
          />
        ))}
      </div>
    </div>
  );
}

function formatReviewQuestion(question: ReviewQueueItem["question"]): string {
  return `${question.question_no} · out of ${question.total_marks}`;
}

function BatchApproveResultPanel({ result }: Readonly<{ result: BatchApproveFinalGradesResponse }>) {
  return (
    <section className="rounded border border-emerald-800 bg-emerald-950/20 p-5 text-sm text-emerald-100">
      <h2 className="text-lg font-semibold">Batch final-grade approval result</h2>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <SummaryMetric label="requested_count" value={result.requested_count} />
        <SummaryMetric label="approved_count" value={result.approved_count} />
        <SummaryMetric label="skipped_count" value={result.skipped_count} />
        <SummaryMetric label="failed_count" value={result.failed_count} />
      </div>
      <p className="mt-3 text-emerald-200">FinalGrade IDs: {result.final_grade_ids.join(", ") || "none"}</p>
      {result.errors.length > 0 ? (
        <ul className="mt-3 list-disc pl-5 text-red-200">
          {result.errors.map((error) => <li key={error}>{error}</li>)}
        </ul>
      ) : null}
    </section>
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
      <div className="mt-5 overflow-x-auto">
        <h3 className="text-lg font-semibold">Submission totals</h3>
        <p className="mt-1 text-sm text-slate-400">
          Totals use teacher-approved grades only. Incomplete totals stay visibly blocked instead of treating an unreviewed answer as zero.
        </p>
        <table className="mt-3 min-w-full border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-slate-700 text-slate-300">
              <th className="px-3 py-2">Submission</th>
              <th className="px-3 py-2">Student</th>
              <th className="px-3 py-2">Approved total</th>
              <th className="px-3 py-2">Coverage</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {summary.submission_totals.map((total) => (
              <tr key={total.submission_id} className="border-b border-slate-800">
                <td className="px-3 py-3">#{total.submission_id}</td>
                <td className="px-3 py-3">
                  <span className="block font-medium">{total.student_identifier}</span>
                  {total.student_name ? <span className="text-xs text-slate-400">{total.student_name}</span> : null}
                </td>
                <td className="px-3 py-3 font-semibold">
                  {total.approved_score} / {total.assessment_max_score}
                  {!total.is_complete ? (
                    <span className="block text-xs font-normal text-slate-400">
                      Approved questions currently cover {total.approved_max_score} marks.
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-3">
                  {total.approved_question_count} / {total.expected_question_count} questions
                </td>
                <td className="px-3 py-3">
                  <span className={total.is_complete ? "text-emerald-300" : "text-amber-300"}>
                    {total.is_complete ? "Complete" : "Incomplete"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
  selected,
  onSelectionChange,
}: Readonly<{
  item: ReviewQueueItem;
  draft: ReviewDraft;
  saving: boolean;
  onDraftChange: (patch: Partial<ReviewDraft>) => void;
  onApprove: () => void;
  onEdit: () => void;
  onReject: () => void;
  selected: boolean;
  onSelectionChange: (checked: boolean) => void;
}>) {
  const suggestion = item.latest_grade_suggestion;
  const finalGrade: FinalGrade | null = item.final_grade;
  const rubricBreakdown = suggestion?.raw_response_json.rubric_breakdown ?? [];
  const status = getDisplayStatus(item);
  const scoreText = suggestion ? `${suggestion.score ?? "—"} / ${suggestion.max_score}` : "—";
  const finalScoreText = finalGrade ? String(finalGrade.final_score) : "—";
  const selectable = isSelectableForBatchApprove(item);
  return (
    <article data-testid="review-card" id={`review-item-${item.answer_region.id}`} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Review item overview</p>
          <h2 className="mt-1 text-xl font-semibold">
            Submission {item.submission.student_identifier} · {formatReviewQuestion(item.question)}
          </h2>
          <p className="text-sm text-slate-400">{item.submission.student_name || "Unnamed student"}</p>
        </div>
        <div>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={selected}
              disabled={!selectable}
              onChange={(event) => onSelectionChange(event.target.checked)}
            />
            Select suggested item for batch approval
          </label>
          <p className="text-xs text-slate-500">Only suggested, not-finalized GradeSuggestion items are selectable.</p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${status.className}`}>
          Status label: {status.label}
        </span>
      </div>

      <div className="grid gap-3 rounded border border-slate-800 p-3 text-sm md:grid-cols-5">
        <SummaryMetric label="student_identifier" value={item.submission.student_identifier} />
        <SummaryMetric label="grading unit" value={formatReviewQuestion(item.question)} />
        <SummaryMetric label="grading unit max marks" value={item.question.total_marks} />
        <SummaryMetric label="review status" value={status.label} />
        <SummaryMetric label="Local Qwen draft" value={scoreText} />
        <SummaryMetric label="Final score if finalized" value={finalScoreText} />
      </div>

      <div className="text-sm text-slate-400">Answer region #{item.answer_region.id}</div>
      <AuthenticatedAnswerRegionImage
        answerRegionId={item.answer_region.id}
        alt={`Answer region ${item.answer_region.id}`}
      />
      <p className="text-sm text-slate-300">Question text: {item.question.question_text}</p>

      {suggestion ? (
        <section className="grid gap-3 rounded border border-amber-800 bg-amber-950/20 p-3">
          <h3 className="font-semibold text-amber-200">Local Qwen suggested score — not final</h3>
          {suggestion.prompt_version !== CURRENT_REAL_GRADING_PROMPT_VERSION ? (
            <p className="rounded border border-red-700 bg-red-950/40 p-3 text-sm text-red-200">
              This draft used an older grading policy ({suggestion.prompt_version}). It may
              over-penalize equivalent student-defined notation. Do not approve it unchanged;
              verify the mathematics and use “Edit score and save final grade” when needed.
            </p>
          ) : null}
          <p className="text-sm">Draft score: {suggestion.score} / {suggestion.max_score}</p>
          <p className="text-sm">Confidence: {suggestion.confidence} · teacher review required</p>
          <p className="text-sm">Marking policy used: {suggestion.marking_policy}</p>
          <p className="text-sm">Grading prompt: {suggestion.prompt_version}</p>
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
          <h3 className="font-semibold">Quick actions</h3>
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

function isSelectableForBatchApprove(item: ReviewQueueItem) {
  return Boolean(item.latest_grade_suggestion && !item.final_grade && item.review_status === "suggested");
}

function itemMatchesStatusFilter(item: ReviewQueueItem, statusFilter: ReviewStatusFilter) {
  if (statusFilter === "all") {
    return true;
  }
  if (statusFilter === "approved" || statusFilter === "edited" || statusFilter === "rejected") {
    return item.final_grade?.approval_status === statusFilter;
  }
  return item.review_status === statusFilter;
}

function getDisplayStatus(item: ReviewQueueItem) {
  if (item.final_grade?.approval_status === "approved") {
    return { label: "Approved", className: "border-emerald-700 bg-emerald-950/40 text-emerald-200" };
  }
  if (item.final_grade?.approval_status === "edited") {
    return { label: "Edited", className: "border-blue-700 bg-blue-950/40 text-blue-200" };
  }
  if (item.final_grade?.approval_status === "rejected") {
    return { label: "Rejected", className: "border-red-700 bg-red-950/40 text-red-200" };
  }
  if (item.review_status === "suggested") {
    return { label: "Suggested", className: "border-amber-700 bg-amber-950/40 text-amber-200" };
  }
  if (item.review_status === "finalized") {
    return { label: "Finalized", className: "border-emerald-700 bg-emerald-950/40 text-emerald-200" };
  }
  return { label: "Ungraded", className: "border-slate-700 bg-slate-950/40 text-slate-300" };
}

function getStatusCounts(items: ReviewQueueItem[]) {
  return items.reduce(
    (counts, item) => {
      counts.all += 1;
      counts[item.review_status] += 1;
      if (item.final_grade?.approval_status === "approved") {
        counts.approved += 1;
      } else if (item.final_grade?.approval_status === "edited") {
        counts.edited += 1;
      } else if (item.final_grade?.approval_status === "rejected") {
        counts.rejected += 1;
      }
      return counts;
    },
    { all: 0, ungraded: 0, suggested: 0, finalized: 0, approved: 0, edited: 0, rejected: 0 },
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
