"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  classifyTranscriptPage,
  correctTranscriptBlock,
  fetchAnswerEvidence,
  fetchScriptTranscript,
  fetchTranscriptBlockRevisions,
  overrideTranscriptBlockAssignment,
  reconcileTranscriptPage,
  rederiveAnswerEvidence,
  type AnswerEvidence,
  type AnswerEvidenceState,
  type ScriptTranscript,
  type ScriptTranscriptBlock,
  type ScriptTranscriptBlockRevision,
  type SubmissionAnswerEvidence,
} from "../lib/api";
import { AuthenticatedSubmissionPageImage } from "./AuthenticatedSubmissionPageImage";

// Every state is named for the teacher rather than shown as a raw enum, and
// each one says what it does NOT mean. "No answer found" is the only state that
// is a claim about the student; the rest are claims about the read.
const STATE_LABEL: Record<AnswerEvidenceState, string> = {
  answer_present: "Answer found",
  no_answer_found: "No answer written",
  unreadable: "Could not be read",
  ambiguous: "Needs a decision",
  missing_page: "A page is missing",
  processing_failed: "Reading failed",
};

const STATE_HELP: Record<AnswerEvidenceState, string> = {
  answer_present: "Evidence was found and attached to this question.",
  no_answer_found:
    "The whole script was read successfully and nothing answers this question. This is the only state that means the student left it blank.",
  unreadable: "Evidence exists but could not be transcribed faithfully. This is not a blank answer.",
  ambiguous:
    "Writing could not be placed against a question, or ownership was inferred rather than read. This is not a blank answer.",
  missing_page: "A source page of this script is missing, so absence cannot be established.",
  processing_failed:
    "At least one page could not be read, so absence cannot be established. This is not a blank answer.",
};

const BASIS_LABEL: Record<string, string> = {
  explicit_label: "heading read on the page",
  same_page_reading_order: "follows the answer above it on the same page",
  declared_continuation: "marked as continuing from the previous page",
};

type Props = { submissionId: number };

export default function ScriptTranscriptReviewClient({ submissionId }: Props) {
  const [transcript, setTranscript] = useState<ScriptTranscript | null>(null);
  const [evidence, setEvidence] = useState<SubmissionAnswerEvidence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editingBlockId, setEditingBlockId] = useState<number | null>(null);
  const [draftText, setDraftText] = useState("");
  const [draftReason, setDraftReason] = useState("");
  const [revisions, setRevisions] = useState<Record<number, ScriptTranscriptBlockRevision[]>>({});
  const [reconcileNote, setReconcileNote] = useState("");
  const [assignmentDrafts, setAssignmentDrafts] = useState<
    Record<number, { label: string; continues: boolean }>
  >({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextTranscript = await fetchScriptTranscript(submissionId);
      setTranscript(nextTranscript);
      try {
        setEvidence(await fetchAnswerEvidence(submissionId));
      } catch {
        // A transcript can exist before any assignment has been derived.
        setEvidence(null);
      }
    } catch (caught) {
      setTranscript(null);
      setEvidence(null);
      const message = caught instanceof Error ? caught.message : "Could not load the transcript.";
      // "Nothing has been transcribed yet" is a state, not a failure. Showing
      // the backend's 404 text here made an ordinary empty script read like
      // something had gone wrong.
      setError(message.includes("no source transcript") ? null : message);
    } finally {
      setLoading(false);
    }
  }, [submissionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const blocksById = useMemo(() => {
    const map = new Map<number, ScriptTranscriptBlock>();
    transcript?.pages.forEach((page) =>
      page.blocks.forEach((block) => map.set(block.id, block)),
    );
    return map;
  }, [transcript]);

  async function saveCorrection(block: ScriptTranscriptBlock) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await correctTranscriptBlock(block.id, {
        edited_text: draftText,
        reason: draftReason.trim() ? draftReason.trim() : null,
      });
      setEditingBlockId(null);
      setDraftReason("");
      setNotice(
        "Correction saved. The model's own text is kept beside it, and any draft grade made from the earlier text is now marked out of date.",
      );
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save the correction.");
    } finally {
      setBusy(false);
    }
  }

  async function showRevisions(blockId: number) {
    try {
      const history = await fetchTranscriptBlockRevisions(blockId);
      setRevisions((current) => ({ ...current, [blockId]: history }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load the revision history.");
    }
  }

  async function reconcile(pageTranscriptId: number, resolution: "failed" | "missing_page") {
    if (!reconcileNote.trim()) {
      setError("Record what you checked before settling an unknown outcome.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await reconcileTranscriptPage(pageTranscriptId, {
        resolution,
        note: reconcileNote.trim(),
      });
      setReconcileNote("");
      setNotice("Outcome recorded. The page can be read again only because you said so.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not record the outcome.");
    } finally {
      setBusy(false);
    }
  }

  async function rederive() {
    setBusy(true);
    setError(null);
    try {
      setEvidence(await rederiveAnswerEvidence(submissionId));
      setNotice("Question assignment re-derived from the stored transcript. No page was read again.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not re-derive the assignment.");
    } finally {
      setBusy(false);
    }
  }

  async function saveAssignment(block: ScriptTranscriptBlock) {
    const draft = assignmentDrafts[block.id] ?? {
      label: block.effective_question_label ?? "",
      continues: block.effective_continues_from_previous,
    };
    setBusy(true);
    setError(null);
    try {
      await overrideTranscriptBlockAssignment(block.id, {
        question_label: draft.label || null,
        continues_from_previous: draft.continues,
      });
      await rederiveAnswerEvidence(submissionId);
      setNotice("Evidence ownership updated from the saved transcript. No page was read again.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update evidence ownership.");
    } finally {
      setBusy(false);
    }
  }

  async function classifyPage(
    pageId: number,
    classification: "answer_content" | "non_answer" | null,
  ) {
    setBusy(true);
    setError(null);
    try {
      await classifyTranscriptPage(pageId, { classification });
      await rederiveAnswerEvidence(submissionId);
      setNotice(
        classification === "non_answer"
          ? "Page kept in the transcript and excluded from answer evidence."
          : "Page classification updated and evidence re-derived without another model call.",
      );
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not classify the page.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-slate-600">Loading the script transcript…</p>;
  }

  if (!transcript) {
    return (
      <section className="rounded border border-slate-200 p-4">
        <h2 className="text-lg font-semibold">Script transcript</h2>
        <p className="mt-2 text-sm text-slate-600">
          {error ?? "This script has not been transcribed yet."}
        </p>
      </section>
    );
  }

  const needsReconciliation = transcript.pages_needing_reconciliation.length > 0;

  return (
    <div className="space-y-6">
      {error ? (
        <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900">
          {notice}
        </p>
      ) : null}

      <section className="rounded border border-slate-200 p-4" data-testid="transcript-provenance">
        <h2 className="text-lg font-semibold">Script transcript</h2>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-4">
          <div>
            <dt className="text-slate-500">Pages read</dt>
            <dd data-testid="pages-read">
              {transcript.pages_read} of {transcript.page_count}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">Requests actually made</dt>
            {/* Measured, not inferred from the page count: a reused page costs nothing. */}
            <dd data-testid="provider-request-count">{transcript.provider_request_count}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Read by</dt>
            <dd data-testid="transcript-model">
              {transcript.provider} · {transcript.model_name}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">Coverage</dt>
            <dd data-testid="coverage-complete">
              {transcript.coverage_complete ? "Every page read" : "Incomplete"}
            </dd>
          </div>
        </dl>
        {!transcript.coverage_complete ? (
          <p className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            Not every page was read successfully. While that is true, no question on this script can
            be reported as unanswered.
          </p>
        ) : null}
      </section>

      {needsReconciliation ? (
        <section
          className="rounded border border-amber-400 bg-amber-50 p-4"
          data-testid="reconciliation-panel"
        >
          <h2 className="text-lg font-semibold text-amber-900">Unresolved read outcome</h2>
          <p className="mt-2 text-sm text-amber-900">
            {`Page ${transcript.pages_needing_reconciliation.join(", ")} was sent but never reported back. It may already have been produced and charged for, so nothing will read it again automatically. Check what happened, then record it.`}
          </p>
          <label className="mt-3 block text-sm">
            What did you check?
            <textarea
              className="mt-1 w-full rounded border border-amber-300 p-2"
              value={reconcileNote}
              onChange={(event) => setReconcileNote(event.target.value)}
              data-testid="reconcile-note"
            />
          </label>
          <div className="mt-2 flex gap-2">
            {transcript.pages
              .filter((page) => page.needs_reconciliation)
              .map((page) => (
                <span key={page.id} className="flex gap-2">
                  <button
                    type="button"
                    className="rounded bg-amber-700 px-3 py-1 text-sm text-white disabled:opacity-50"
                    disabled={busy}
                    onClick={() => void reconcile(page.id, "failed")}
                    data-testid={`reconcile-failed-${page.page_no}`}
                  >
                    Nothing was produced
                  </button>
                  <button
                    type="button"
                    className="rounded border border-amber-700 px-3 py-1 text-sm text-amber-900 disabled:opacity-50"
                    disabled={busy}
                    onClick={() => void reconcile(page.id, "missing_page")}
                    data-testid={`reconcile-missing-${page.page_no}`}
                  >
                    The page itself is missing
                  </button>
                </span>
              ))}
          </div>
        </section>
      ) : null}

      <section className="rounded border border-slate-200 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Question evidence</h2>
          <button
            type="button"
            className="rounded border border-slate-400 px-3 py-1 text-sm disabled:opacity-50"
            disabled={busy || !evidence}
            onClick={() => void rederive()}
            data-testid="rederive-evidence"
          >
            Re-derive from transcript (no page is read again)
          </button>
        </div>
        {evidence ? (
          <ul className="mt-4 space-y-4" data-testid="evidence-list">
            {evidence.evidence.map((item: AnswerEvidence) => (
              <li
                key={item.question_id}
                className="rounded border border-slate-200 p-3"
                data-testid={`evidence-${item.question_label ?? item.question_id}`}
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-medium">{item.question_label ?? "Unlabelled"}</span>
                  <span
                    className="rounded bg-slate-100 px-2 py-0.5 text-xs"
                    data-testid={`evidence-state-${item.question_label ?? item.question_id}`}
                  >
                    {STATE_LABEL[item.state]}
                  </span>
                  <span className="text-xs text-slate-500">
                    assignment v{item.assignment_version}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-600">{STATE_HELP[item.state]}</p>
                {item.state_reason ? (
                  <p className="mt-1 text-xs text-slate-700">{item.state_reason}</p>
                ) : null}
                {item.spans.length > 0 ? (
                  <ol className="mt-2 space-y-1 text-sm">
                    {item.spans.map((span) => (
                      <li key={span.order_index} className="rounded bg-slate-50 p-2">
                        <span className="text-xs text-slate-500">
                          {`page ${span.page_no} · ${BASIS_LABEL[span.assignment_basis] ?? span.assignment_basis}`}
                        </span>
                        <p className="whitespace-pre-wrap">{span.text}</p>
                        {span.unresolved ? (
                          <p className="text-xs text-amber-800">
                            {`Unresolved: ${span.unresolved_reason ?? "needs review"}`}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="mt-2 text-sm text-slate-500">No evidence attached.</p>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-slate-600">
            No question assignment has been derived from this transcript yet.
          </p>
        )}

        {evidence && evidence.unassigned_blocks.length > 0 ? (
          <div className="mt-4 rounded border border-amber-300 bg-amber-50 p-3" data-testid="unassigned-blocks">
            <h3 className="text-sm font-semibold text-amber-900">
              Writing that belongs to no question
            </h3>
            <p className="text-xs text-amber-900">
              Left visible on purpose rather than attached to whichever question was nearest.
            </p>
            <ul className="mt-2 space-y-1 text-sm">
              {evidence.unassigned_blocks.map((block) => (
                <li key={block.id} className="whitespace-pre-wrap">
                  {block.effective_text}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="rounded border border-slate-200 p-4">
        <h2 className="text-lg font-semibold">Source pages</h2>
        <p className="text-xs text-slate-600">
          The transcript as it was read, page by page. Correcting a line here keeps the model&apos;s
          own text beside yours.
        </p>
        {transcript.pages.map((page) => (
          <article key={page.id} className="mt-6" data-testid={`page-${page.page_no}`}>
            <h3 className="text-sm font-semibold">
              {`Page ${page.page_no}`}{" "}
              <span className="font-normal text-slate-500">
                {`· ${page.state}${page.is_blank_page ? " · blank" : ""} · ${page.provider_request_count} request(s)`}
              </span>
            </h3>
            {page.error ? (
              <p className="mt-1 text-xs text-red-800" data-testid={`page-error-${page.page_no}`}>
                {page.error}
              </p>
            ) : null}
            {page.state === "succeeded" ? (
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span className="text-slate-600">Page role:</span>
                <button
                  type="button"
                  disabled={busy}
                  className={`rounded border px-2 py-1 ${page.teacher_classification === "answer_content" ? "border-emerald-700 bg-emerald-50" : "border-slate-300"}`}
                  onClick={() => void classifyPage(page.id, "answer_content")}
                >
                  Contains answer work
                </button>
                <button
                  type="button"
                  disabled={busy}
                  className={`rounded border px-2 py-1 ${page.teacher_classification === "non_answer" ? "border-amber-700 bg-amber-50" : "border-slate-300"}`}
                  onClick={() => void classifyPage(page.id, "non_answer")}
                  data-testid={`page-non-answer-${page.page_no}`}
                >
                  Cover / instructions / non-answer
                </button>
                {page.teacher_classification ? (
                  <button type="button" disabled={busy} className="underline" onClick={() => void classifyPage(page.id, null)}>
                    Clear decision
                  </button>
                ) : null}
              </div>
            ) : null}
            <div className="mt-3 grid gap-4 lg:grid-cols-2">
              <AuthenticatedSubmissionPageImage
                pageId={page.submission_page_id}
                label={`Complete source page ${page.page_no}`}
              />
              <ul className="space-y-2">
              {page.blocks.map((block) => (
                <li key={block.id} className="rounded border border-slate-200 p-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>{block.question_label_raw ?? "no heading read"}</span>
                    <span>· {block.label_source}</span>
                    {block.assignment_override_active ? (
                      <span className="font-medium text-indigo-700">
                        {`· teacher: ${block.effective_question_label ?? "unassigned"}`}
                      </span>
                    ) : null}
                    {block.revision > 0 ? (
                      <span data-testid={`block-revision-${block.id}`}>
                        · corrected (v{block.revision})
                      </span>
                    ) : null}
                    {block.unresolved ? (
                      <span className="text-amber-800">· {block.unresolved_reason}</span>
                    ) : null}
                  </div>
                  {editingBlockId === block.id ? (
                    <div className="mt-2 space-y-2">
                      <textarea
                        className="w-full rounded border border-slate-300 p-2 text-sm"
                        value={draftText}
                        onChange={(event) => setDraftText(event.target.value)}
                        data-testid={`block-editor-${block.id}`}
                      />
                      <input
                        className="w-full rounded border border-slate-300 p-2 text-sm"
                        placeholder="Why are you changing it? (optional)"
                        value={draftReason}
                        onChange={(event) => setDraftReason(event.target.value)}
                        data-testid={`block-reason-${block.id}`}
                      />
                      <div className="flex gap-2">
                        <button
                          type="button"
                          className="rounded bg-slate-800 px-3 py-1 text-sm text-white disabled:opacity-50"
                          disabled={busy}
                          onClick={() => void saveCorrection(block)}
                          data-testid={`block-save-${block.id}`}
                        >
                          Save correction
                        </button>
                        <button
                          type="button"
                          className="rounded border border-slate-400 px-3 py-1 text-sm"
                          onClick={() => setEditingBlockId(null)}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="mt-1 whitespace-pre-wrap text-sm">{block.effective_text}</p>
                      {block.edited_text !== null ? (
                        <details className="mt-1 text-xs text-slate-600">
                          <summary>What the model read</summary>
                          <p className="whitespace-pre-wrap">{block.text}</p>
                        </details>
                      ) : null}
                      <div className="mt-1 flex gap-3 text-xs">
                        <button
                          type="button"
                          className="underline"
                          onClick={() => {
                            setEditingBlockId(block.id);
                            setDraftText(block.effective_text);
                            setDraftReason("");
                          }}
                          data-testid={`block-edit-${block.id}`}
                        >
                          Correct this
                        </button>
                        {block.revision > 0 ? (
                          <button
                            type="button"
                            className="underline"
                            onClick={() => void showRevisions(block.id)}
                            data-testid={`block-history-${block.id}`}
                          >
                            Revision history
                          </button>
                        ) : null}
                      </div>
                      <div className="mt-3 grid gap-2 rounded bg-slate-50 p-2 text-xs sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
                        <label>
                          Evidence owner
                          <select
                            className="mt-1 w-full rounded border border-slate-300 bg-white p-1"
                            value={(assignmentDrafts[block.id]?.label ?? block.effective_question_label) || ""}
                            onChange={(event) =>
                              setAssignmentDrafts((current) => ({
                                ...current,
                                [block.id]: {
                                  label: event.target.value,
                                  continues: current[block.id]?.continues ?? block.effective_continues_from_previous,
                                },
                              }))
                            }
                          >
                            <option value="">Leave unassigned</option>
                            {evidence?.evidence.map((item) =>
                              item.question_label ? <option key={item.question_id} value={item.question_label}>{item.question_label}</option> : null,
                            )}
                          </select>
                        </label>
                        <label className="flex items-center gap-1">
                          <input
                            type="checkbox"
                            checked={assignmentDrafts[block.id]?.continues ?? block.effective_continues_from_previous}
                            onChange={(event) =>
                              setAssignmentDrafts((current) => ({
                                ...current,
                                [block.id]: {
                                  label: current[block.id]?.label ?? block.effective_question_label ?? "",
                                  continues: event.target.checked,
                                },
                              }))
                            }
                          />
                          Continues from previous page
                        </label>
                        <button
                          type="button"
                          disabled={busy}
                          className="rounded border border-slate-400 px-2 py-1"
                          onClick={() => void saveAssignment(block)}
                          data-testid={`block-assign-${block.id}`}
                        >
                          Save owner
                        </button>
                      </div>
                      {revisions[block.id] ? (
                        <ol className="mt-1 space-y-1 text-xs text-slate-600">
                          {revisions[block.id].map((revision) => (
                            <li key={revision.revision}>
                              {`v${revision.revision}: ${revision.previous_text} → ${revision.new_text}`}
                              {revision.reason ? ` (${revision.reason})` : ""}
                            </li>
                          ))}
                        </ol>
                      ) : null}
                    </>
                  )}
                </li>
              ))}
              </ul>
            </div>
          </article>
        ))}
      </section>

      <p className="text-xs text-slate-500">
        Nothing on this page grades, approves or exports anything. Every draft grade stays a draft
        until a teacher approves it, and a draft made from evidence that has since changed cannot be
        approved at all.
      </p>
      <span className="hidden" data-testid="blocks-loaded">
        {blocksById.size}
      </span>
    </div>
  );
}
