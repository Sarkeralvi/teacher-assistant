"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { buttonClass, EmptyState, ErrorState, inputClass, LoadingState } from "./AppShell";
import {
  AuthenticatedAnswerRegionImage,
  AuthenticatedAnswerRegionSegmentImage,
  type EditingDecisionOverlay,
  type AnswerRegionImageLoadState,
} from "./AuthenticatedAnswerRegionImage";
import { AuthenticatedMappedSourcePage } from "./AuthenticatedMappedSourcePage";
import {
  acceptAnswerRegionMappingSuggestion,
  acceptQuestionImportDrafts,
  addAnswerRegionSegment,
  confirmAnswerRegionFullAnswer,
  confirmQuestionNodeMapping,
  createAnswerRegion,
  createVisualTranscriptionRun,
  createEvidencePrepRun,
  createGradingQueueRun,
  createQuestion,
  createRubric,
  deleteSubmission,
  editAnswerRegionSegment,
  getVisualTranscriptionRun,
  getAssessment,
  getAssessmentReviewQueue,
  getEvidencePrepSummary,
  getGradingEvidencePacket,
  getGradingQueueSummary,
  getLocalAiStatus,
  getSubmissionPageImageUrl,
  getStoredAuthToken,
  gradeAllApprovedAnswersWithLocalQwen38,
  gradeAnswerRegionWithLocalQwen38,
  importQuestionsFromPaper,
  listAssessmentAnswerRegions,
  listAssessmentGradingRuns,
  listAssessmentQuestionNodeMappings,
  listAnswerRegionTranscriptionRuns,
  listQuestionNodes,
  listQuestions,
  listRubricExtractionCriteria,
  listRubrics,
  listSubmissions,
  removeAnswerRegionSegment,
  confirmVisualTranscriptionRun,
  confirmVisualTranscriptionThinkingRepair,
  createVisualTranscriptionThinkingRepair,
  rejectVisualTranscriptionRun,
  rejectVisualTranscriptionThinkingRepair,
  reorderAnswerRegionSegments,
  runAssessmentQuestionNodeMappings,
  runSubmissionQuestionNodeMappings,
  suggestAnswerRegionMappings,
  updateQuestion,
  updateQuestionNode,
  updateQuestionNodeMapping,
  updateRubric,
  updateRubricExtractionCriterion,
  uploadSubmission,
  uploadSubmissionZip,
  type AnswerRegion,
  type AnswerRegionMapping,
  type AnswerRegionOcrRun,
  type Assessment,
  type DraftAnswerRegionSuggestionGroup,
  type DraftQuestion,
  type EvidencePrepRun,
  type FinalGrade,
  type GradingEvidencePacket,
  type GradingQueueRun,
  type GradingRun,
  type LocalAiStatus,
  type LocalQwenApprovedBatchGradeResponse,
  type Question,
  type QuestionImportJob,
  type QuestionImportProvider,
  type QuestionNode,
  type QuestionNodeMappingGroup,
  type Rubric,
  type RubricExtractionCriterion,
  type ReviewQueueItem,
  type Submission,
  type SubmissionZipUploadResponse,
} from "../lib/api";
import { type DemoTeacher } from "../lib/demoTeacher";
import { DemoTeacherSelector } from "./DemoTeacherSelector";

type DraftQuestionEdit = {
  selected: boolean;
  question_no: string;
  question_text: string;
  model_answer: string;
  total_marks: string;
};

type ManualSetupDraft = {
  question_text: string;
  model_answer: string;
  criteria_name: string;
  criteria_description: string;
  criteria_marks: string;
};

type ExtractedQuestionNodeDraft = {
  question_number: string;
  parent_question_number: string;
  label: string;
  text: string;
  marks: string;
  source_page: string;
  teacher_confirmed: boolean;
};

type ExtractedRubricCriterionDraft = {
  question_number: string;
  criterion_label: string;
  description: string;
  max_marks: string;
  blocker: string;
  teacher_confirmed: boolean;
};

function questionNodeDraftFor(node: QuestionNode): ExtractedQuestionNodeDraft {
  return {
    question_number: node.question_number,
    parent_question_number: node.parent_question_number ?? "",
    label: node.label,
    text: node.text,
    marks: node.marks == null ? "" : String(node.marks),
    source_page: node.source_page == null ? "" : String(node.source_page),
    teacher_confirmed: node.teacher_confirmed,
  };
}

function rubricCriterionDraftFor(
  criterion: RubricExtractionCriterion,
): ExtractedRubricCriterionDraft {
  return {
    question_number: criterion.question_number ?? "",
    criterion_label: criterion.criterion_label,
    description: criterion.description,
    max_marks: criterion.max_marks == null ? "" : String(criterion.max_marks),
    blocker: criterion.blocker ?? "",
    teacher_confirmed: criterion.teacher_confirmed,
  };
}

function manualSetupDraftFor(question: Question): ManualSetupDraft {
  return {
    question_text: question.question_text,
    model_answer: question.model_answer ?? "",
    criteria_name: "Complete answer",
    criteria_description: "Awards marks for a correct teacher-approved answer.",
    criteria_marks: String(question.total_marks),
  };
}

function buildSingleCriterionRubric(question: Question, draft: ManualSetupDraft) {
  return {
    total_marks: Number(question.total_marks),
    criteria: [
      {
        id: "manual-criterion-1",
        name: draft.criteria_name.trim(),
        description: draft.criteria_description.trim(),
        max_marks: Number(draft.criteria_marks),
      },
    ],
  };
}

function localMappingWarnings(mapping: AnswerRegionMapping): string[] {
  const value = mapping.source_reference?.warnings;
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

// Both local paths lead to the same three teacher confirmations: confirm the
// region, confirm the verbatim transcription, confirm it is the full answer.
// The evidence panel is therefore gated on "a local model prepared this", not on
// which one did — gating on the vision provider alone hid the panel for tiered
// mappings and left the teacher no way to confirm or grade them.
function isLocalPreparedMapping(mapping: AnswerRegionMapping): boolean {
  return mapping.provider === "local_paddle_qwen" || mapping.provider === "llama_cpp_qwen38";
}

const CURRENT_FINAL_INTENT_PROMPT_VERSION = "qwen38-visible-evidence-structured-v5";
const REPAIRABLE_FINAL_INTENT_PROMPT_VERSIONS = new Set([
  "qwen38-final-intent-structured-v2",
  "qwen38-final-intent-structured-v3",
  "qwen38-final-intent-structured-v4",
  CURRENT_FINAL_INTENT_PROMPT_VERSION,
]);
const CURRENT_THINKING_REPAIR_PROMPT_VERSION = "qwen38-final-intent-thinking-repair-v9";

type ThinkingRepairDecision = EditingDecisionOverlay & {
  page_index: number;
  position_hint: string;
  status: "cancelled" | "replacement" | "retained" | "uncertain_correction";
};

function thinkingRepairDecisions(run: AnswerRegionOcrRun | null): ThinkingRepairDecision[] {
  const analysis = run?.normalized_result?.editing_analysis;
  if (!analysis || typeof analysis !== "object" || Array.isArray(analysis)) return [];
  const marks = (analysis as Record<string, unknown>).editing_marks;
  if (!Array.isArray(marks)) return [];
  return marks.flatMap((raw, decisionIndex) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const value = raw as Record<string, unknown>;
    const status = value.status;
    const bbox = value.bbox;
    const pageIndex = value.page_index;
    const positionHint = value.position_hint;
    if (
      !["cancelled", "replacement", "retained", "uncertain_correction"].includes(String(status)) ||
      !Array.isArray(bbox) || bbox.length !== 4 || !bbox.every((item) => typeof item === "number") ||
      typeof pageIndex !== "number" || typeof positionHint !== "string"
    ) return [];
    return [{
      bbox: bbox as number[],
      status: status as ThinkingRepairDecision["status"],
      decisionIndex,
      page_index: pageIndex,
      position_hint: positionHint,
    }];
  });
}

function safeVisualTranscriptionError(error: string | null): string | null {
  if (!error) return null;
  if (
    error.includes("input_value=") ||
    error.includes("content starts:") ||
    error.includes("data:image/")
  ) {
    return "Qwen3.8 output did not match the safe transcription contract. No transcript was accepted.";
  }
  return error;
}

export function AssessmentDetailClient({ assessmentId }: Readonly<{ assessmentId: number }>) {
  const uploadFormRef = useRef<HTMLFormElement | null>(null);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [rubricsByQuestionId, setRubricsByQuestionId] = useState<Record<number, Rubric[]>>({});
  const [manualSetupDrafts, setManualSetupDrafts] = useState<Record<number, ManualSetupDraft>>({});
  const [questionNodes, setQuestionNodes] = useState<QuestionNode[]>([]);
  const [questionNodeDrafts, setQuestionNodeDrafts] = useState<Record<number, ExtractedQuestionNodeDraft>>({});
  const [rubricCriteria, setRubricCriteria] = useState<RubricExtractionCriterion[]>([]);
  const [rubricCriterionDrafts, setRubricCriterionDrafts] = useState<Record<number, ExtractedRubricCriterionDraft>>({});
  const [savingQuestionNodeId, setSavingQuestionNodeId] = useState<number | null>(null);
  const [savingRubricCriterionId, setSavingRubricCriterionId] = useState<number | null>(null);
  const [savingQuestionId, setSavingQuestionId] = useState<number | null>(null);
  const [savingModelAnswerId, setSavingModelAnswerId] = useState<number | null>(null);
  const [savingRubricQuestionId, setSavingRubricQuestionId] = useState<number | null>(null);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [answerRegions, setAnswerRegions] = useState<AnswerRegion[]>([]);
  const [ocrRunsByRegionId, setOcrRunsByRegionId] = useState<Record<number, AnswerRegionOcrRun[]>>({});
  const [runningOcrRegionId, setRunningOcrRegionId] = useState<number | null>(null);
  const [repairingOcrRegionId, setRepairingOcrRegionId] = useState<number | null>(null);
  const [reviewedRepairDecisions, setReviewedRepairDecisions] = useState<Record<number, number[]>>({});
  const [questionNodeMappings, setQuestionNodeMappings] = useState<QuestionNodeMappingGroup[]>([]);
  const [selectedMappingQuestionNodeId, setSelectedMappingQuestionNodeId] = useState("");
  const [mappingPageId, setMappingPageId] = useState("");
  const [mappingX, setMappingX] = useState("24");
  const [mappingY, setMappingY] = useState("24");
  const [mappingWidth, setMappingWidth] = useState("800");
  const [mappingHeight, setMappingHeight] = useState("300");
  const [mappingManualAnswerText, setMappingManualAnswerText] = useState("");
  const [runningMappings, setRunningMappings] = useState(false);
  const [scriptPreparationMessage, setScriptPreparationMessage] = useState<string | null>(null);
  const [gradingRegionId, setGradingRegionId] = useState<number | null>(null);
  const [gradingAllApproved, setGradingAllApproved] = useState(false);
  const [batchGradeResult, setBatchGradeResult] = useState<LocalQwenApprovedBatchGradeResponse | null>(null);
  const [confirmingMappingId, setConfirmingMappingId] = useState<number | null>(null);
  const [confirmingVisualRunId, setConfirmingVisualRunId] = useState<number | null>(null);
  const [answerRegionImageStates, setAnswerRegionImageStates] = useState<Record<number, AnswerRegionImageLoadState>>({});
  const [sourcePageImageStates, setSourcePageImageStates] = useState<Record<number, Record<number, AnswerRegionImageLoadState>>>({});
  const [segmentCropImageStates, setSegmentCropImageStates] = useState<Record<number, Record<number, AnswerRegionImageLoadState>>>({});
  const [sourceBoundaryReviewed, setSourceBoundaryReviewed] = useState<Record<number, boolean>>({});
  const [savingMappingId, setSavingMappingId] = useState<number | null>(null);
  const [evidencePackets, setEvidencePackets] = useState<Record<number, GradingEvidencePacket>>({});
  const [evidencePrepSummary, setEvidencePrepSummary] = useState<EvidencePrepRun | null>(null);
  const [gradingQueueSummary, setGradingQueueSummary] = useState<GradingQueueRun | null>(null);
  const [gradingRuns, setGradingRuns] = useState<GradingRun[]>([]);
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
  const [questionImportProvider, setQuestionImportProvider] = useState<QuestionImportProvider>("mock");
  const [questionImportJob, setQuestionImportJob] = useState<QuestionImportJob | null>(null);
  const [localAiStatus, setLocalAiStatus] = useState<LocalAiStatus | null>(null);
  const [draftQuestionEdits, setDraftQuestionEdits] = useState<Record<string, DraftQuestionEdit>>({});
  const [importingQuestions, setImportingQuestions] = useState(false);
  const [acceptingQuestions, setAcceptingQuestions] = useState(false);
  const [selectedPageId, setSelectedPageId] = useState("");
  const [selectedQuestionId, setSelectedQuestionId] = useState("");
  const [regionX, setRegionX] = useState("0");
  const [regionY, setRegionY] = useState("0");
  const [regionWidth, setRegionWidth] = useState("100");
  const [regionHeight, setRegionHeight] = useState("100");
  const [manualAnswerText, setManualAnswerText] = useState("");
  const [regionSuggestions, setRegionSuggestions] = useState<DraftAnswerRegionSuggestionGroup[]>([]);
  const [regionSuggestionMessage, setRegionSuggestionMessage] = useState<string | null>(null);
  const [regionSuggestionWarnings, setRegionSuggestionWarnings] = useState<string[]>([]);
  const [regionSuggestionProvider] = useState<"mock">("mock");
  const [suggestingRegions, setSuggestingRegions] = useState(false);
  const [acceptingSuggestionId, setAcceptingSuggestionId] = useState<string | null>(null);
  const [suggestionPageId, setSuggestionPageId] = useState<number | null>(null);
  const [selectedPreviewRegionId, setSelectedPreviewRegionId] = useState("");
  const [selectedTeacher, setSelectedTeacher] = useState<DemoTeacher | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [creatingRegion, setCreatingRegion] = useState(false);
  const [creatingEvidencePrepRun, setCreatingEvidencePrepRun] = useState(false);
  const [creatingGradingQueueRun, setCreatingGradingQueueRun] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAnswerRegionImageStateChange = useCallback((answerRegionId: number, state: AnswerRegionImageLoadState) => {
    setAnswerRegionImageStates((current) => current[answerRegionId] === state ? current : { ...current, [answerRegionId]: state });
  }, []);

  const handleSourcePageImageStateChange = useCallback((answerRegionId: number, segmentId: number, state: AnswerRegionImageLoadState) => {
    setSourcePageImageStates((current) => {
      const regionStates = current[answerRegionId] ?? {};
      if (regionStates[segmentId] === state) return current;
      return { ...current, [answerRegionId]: { ...regionStates, [segmentId]: state } };
    });
  }, []);

  const handleSegmentCropImageStateChange = useCallback((answerRegionId: number, segmentId: number, state: AnswerRegionImageLoadState) => {
    setSegmentCropImageStates((current) => {
      const regionStates = current[answerRegionId] ?? {};
      if (regionStates[segmentId] === state) return current;
      return { ...current, [answerRegionId]: { ...regionStates, [segmentId]: state } };
    });
  }, []);

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
  const questionNodeMappingByNodeId = new Map<number, QuestionNodeMappingGroup>();
  const flatMappings: AnswerRegionMapping[] = [];
  for (const group of questionNodeMappings) {
    questionNodeMappingByNodeId.set(group.question_node.id, group);
    flatMappings.push(...group.mappings);
  }
  const teacherConfirmedMappingCount = flatMappings.filter((mapping) => mapping.teacher_confirmed).length;
  const uncertainMappingCount = flatMappings.filter((mapping) => mapping.mapping_status === "uncertain").length;
  const blockedMappingCount = flatMappings.filter((mapping) => mapping.mapping_status === "blocked").length;
  const confirmedQuestionSubquestionNodes = questionNodes.filter(
    (node) => node.teacher_confirmed && (node.node_type === "question" || node.node_type === "subquestion"),
  );
  const expectedMappingCount = confirmedQuestionSubquestionNodes.length * submissions.length;
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
  const confirmedQuestionNodeCount = questionNodes.filter((node) => node.teacher_confirmed).length;
  const confirmedRubricCriterionCount = rubricCriteria.filter((criterion) => criterion.teacher_confirmed).length;
  const unresolvedRubricBlockerCount = rubricCriteria.filter((criterion) => criterion.blocker?.trim()).length;
  const selectedPreviewRegion =
    answerRegions.find((region) => String(region.id) === selectedPreviewRegionId) ?? answerRegions[0] ?? null;
  const referencesReady =
    questions.length > 0 &&
    questions.every(
      (question) => Boolean(question.model_answer?.trim()) && Boolean(activeRubricFor(question.id)),
    );
  const activeGradingRun = [...gradingRuns]
    .filter((run) => run.mode === "custom_controlled")
    .sort((left, right) => right.id - left.id)[0] ?? null;
  const localScriptPreparationAuthorized = Boolean(
    localAiStatus?.real_providers_allowed &&
    localAiStatus.local_script_preparation_enabled &&
    localAiStatus.qwen38.enabled &&
    localAiStatus.qwen38.visual_preparation_enabled,
  );
  const localVisualMappingAuthorized = Boolean(
    localAiStatus?.real_providers_allowed &&
    localAiStatus.qwen38.enabled &&
    localAiStatus.qwen38.visual_preparation_enabled,
  );
  const unresolvedMappingSubmissionIds = Array.from(
    new Set(
      flatMappings
        .filter((mapping) => !mapping.teacher_confirmed)
        .map((mapping) => mapping.submission_id),
    ),
  ).sort((left, right) => left - right);
  const preparedSubmissionIds = new Set(flatMappings.map((mapping) => mapping.submission_id));
  const unpreparedSubmissions = submissions.filter(
    (submission) => !preparedSubmissionIds.has(submission.id),
  );
  const localSingleGradeAuthorized = Boolean(
    localAiStatus?.real_providers_allowed &&
    localAiStatus.local_single_answer_grading_enabled &&
    localAiStatus.qwen38.enabled &&
    localAiStatus.qwen38.grading_enabled,
  );
  const approvedBatchRegionIds = answerRegions
    .filter((region) => (
      Boolean(evidencePackets[region.id]?.readiness_result.ready_for_grading) &&
      !gradedRegionIds.has(region.id) &&
      !finalizedRegionIds.has(region.id)
    ))
    .map((region) => region.id);

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

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [
        assessmentData,
        questionData,
        questionNodeData,
        rubricCriterionData,
        submissionData,
        answerRegionData,
        questionNodeMappingData,
        reviewQueueData,
        evidencePrepData,
        gradingQueueData,
        localAiData,
        gradingRunData,
      ] =
        await Promise.all([
          getAssessment(assessmentId),
          listQuestions(assessmentId),
          listQuestionNodes(assessmentId),
          listRubricExtractionCriteria(assessmentId),
          listSubmissions(assessmentId),
          listAssessmentAnswerRegions(assessmentId),
          listAssessmentQuestionNodeMappings(assessmentId),
          getAssessmentReviewQueue(assessmentId),
          getEvidencePrepSummary(assessmentId).catch(() => null),
          getGradingQueueSummary(assessmentId).catch(() => null),
          getLocalAiStatus().catch(() => null),
          listAssessmentGradingRuns(assessmentId).catch(() => [] as GradingRun[]),
        ]);

      setAssessment(assessmentData);
      setQuestions(questionData);
      setQuestionNodes(questionNodeData);
      setQuestionNodeDrafts((current) => {
        const next = { ...current };
        for (const node of questionNodeData) {
          if (!next[node.id]) {
            next[node.id] = questionNodeDraftFor(node);
          }
        }
        return next;
      });
      setRubricCriteria(rubricCriterionData);
      setRubricCriterionDrafts((current) => {
        const next = { ...current };
        for (const criterion of rubricCriterionData) {
          if (!next[criterion.id]) {
            next[criterion.id] = rubricCriterionDraftFor(criterion);
          }
        }
        return next;
      });
      // The Windows pilot browser can intermittently refuse a burst of
      // loopback requests after all CORS preflights complete. Keep these small
      // reads sequential so one dropped connection cannot falsely relock the
      // entire teacher workflow while the backend is healthy.
      const rubricEntries: Array<readonly [number, Rubric[]]> = [];
      for (const question of questionData) {
        rubricEntries.push([question.id, await listRubrics(question.id)] as const);
      }
      setRubricsByQuestionId(Object.fromEntries(rubricEntries));
      setManualSetupDrafts((current) => {
        const next = { ...current };
        for (const question of questionData) {
          if (!next[question.id]) {
            next[question.id] = manualSetupDraftFor(question);
          }
        }
        return next;
      });
      setSubmissions(submissionData);
      setAnswerRegions(answerRegionData);
      setQuestionNodeMappings(questionNodeMappingData);
      if (!selectedPreviewRegionId && answerRegionData[0]) {
        setSelectedPreviewRegionId(String(answerRegionData[0].id));
      }
      const evidenceEntries: Array<readonly [number, GradingEvidencePacket]> = [];
      for (const region of answerRegionData) {
        evidenceEntries.push([region.id, await getGradingEvidencePacket(region.id)] as const);
      }
      setEvidencePackets(Object.fromEntries(evidenceEntries));
      const transcriptionEntries = await Promise.all(
        answerRegionData.map(async (region) => [
          region.id,
          await listAnswerRegionTranscriptionRuns(region.id).catch(() => [] as AnswerRegionOcrRun[]),
        ] as const),
      );
      setOcrRunsByRegionId(Object.fromEntries(transcriptionEntries));
      setReviewQueue(reviewQueueData);
      setEvidencePrepSummary(evidencePrepData);
      setGradingQueueSummary(gradingQueueData);
      setLocalAiStatus(localAiData);
      setGradingRuns(gradingRunData);
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

  useEffect(() => {
    const activeRegionIds = Object.entries(ocrRunsByRegionId)
      .filter(([, runs]) => runs.some((run) => run.status === "queued" || run.status === "running"))
      .map(([regionId]) => Number(regionId));
    if (activeRegionIds.length === 0) return;
    let cancelled = false;
    const refreshActiveTranscriptions = async () => {
      const entries = await Promise.all(
        activeRegionIds.map(async (regionId) => [
          regionId,
          await listAnswerRegionTranscriptionRuns(regionId).catch(
            () => ocrRunsByRegionId[regionId] ?? [],
          ),
        ] as const),
      );
      if (!cancelled) setOcrRunsByRegionId((current) => ({ ...current, ...Object.fromEntries(entries) }));
    };
    const timer = window.setInterval(() => void refreshActiveTranscriptions(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [ocrRunsByRegionId]);

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

  function updateManualSetupDraft(questionId: number, patch: Partial<ManualSetupDraft>) {
    setManualSetupDrafts((current) => ({
      ...current,
      [questionId]: {
        ...(current[questionId] ?? manualSetupDraftFor(questions.find((question) => question.id === questionId)!)),
        ...patch,
      },
    }));
  }

  async function handleSaveQuestion(question: Question) {
    const draft = manualSetupDrafts[question.id] ?? manualSetupDraftFor(question);
    setSavingQuestionId(question.id);
    setError(null);
    try {
      await updateQuestion(question.id, { question_text: draft.question_text });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save question");
    } finally {
      setSavingQuestionId(null);
    }
  }

  async function handleSaveModelAnswer(question: Question) {
    const draft = manualSetupDrafts[question.id] ?? manualSetupDraftFor(question);
    setSavingModelAnswerId(question.id);
    setError(null);
    try {
      await updateQuestion(question.id, { model_answer: draft.model_answer.trim() || null });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save model answer");
    } finally {
      setSavingModelAnswerId(null);
    }
  }

  async function handleSaveRubric(question: Question) {
    const draft = manualSetupDrafts[question.id] ?? manualSetupDraftFor(question);
    setSavingRubricQuestionId(question.id);
    setError(null);
    try {
      const activeRubric = activeRubricFor(question.id);
      const rubricJson = buildSingleCriterionRubric(question, draft);
      if (activeRubric) {
        await updateRubric(activeRubric.id, {
          rubric_json: rubricJson,
          is_active: true,
        });
      } else {
        await createRubric(question.id, {
          version: (rubricsByQuestionId[question.id]?.length ?? 0) + 1,
          is_active: true,
          rubric_json: rubricJson,
        });
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save rubric");
    } finally {
      setSavingRubricQuestionId(null);
    }
  }

  function updateQuestionNodeDraft(nodeId: number, patch: Partial<ExtractedQuestionNodeDraft>) {
    setQuestionNodeDrafts((current) => ({
      ...current,
      [nodeId]: {
        ...(current[nodeId] ?? questionNodeDraftFor(questionNodes.find((node) => node.id === nodeId)!)),
        ...patch,
      },
    }));
  }

  function updateRubricCriterionDraft(
    criterionId: number,
    patch: Partial<ExtractedRubricCriterionDraft>,
  ) {
    setRubricCriterionDrafts((current) => ({
      ...current,
      [criterionId]: {
        ...(current[criterionId] ?? rubricCriterionDraftFor(rubricCriteria.find((criterion) => criterion.id === criterionId)!)),
        ...patch,
      },
    }));
  }

  async function handleSaveQuestionNode(node: QuestionNode) {
    const draft = questionNodeDrafts[node.id] ?? questionNodeDraftFor(node);
    setSavingQuestionNodeId(node.id);
    setError(null);
    try {
      await updateQuestionNode(node.id, {
        question_number: draft.question_number.trim(),
        parent_question_number: draft.parent_question_number.trim() || null,
        label: draft.label.trim(),
        text: draft.text.trim(),
        marks: draft.marks.trim() ? Number(draft.marks) : null,
        source_page: draft.source_page.trim() ? Number(draft.source_page) : null,
        teacher_confirmed: draft.teacher_confirmed,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save extracted question node");
    } finally {
      setSavingQuestionNodeId(null);
    }
  }

  async function handleSaveRubricCriterion(criterion: RubricExtractionCriterion) {
    const draft = rubricCriterionDrafts[criterion.id] ?? rubricCriterionDraftFor(criterion);
    setSavingRubricCriterionId(criterion.id);
    setError(null);
    try {
      await updateRubricExtractionCriterion(criterion.id, {
        question_number: draft.question_number.trim() || null,
        criterion_label: draft.criterion_label.trim(),
        description: draft.description.trim(),
        max_marks: draft.max_marks.trim() ? Number(draft.max_marks) : null,
        blocker: draft.blocker.trim() || null,
        teacher_confirmed: draft.teacher_confirmed,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save extracted rubric criterion");
    } finally {
      setSavingRubricCriterionId(null);
    }
  }

  function activeRubricFor(questionId: number) {
    return (rubricsByQuestionId[questionId] ?? []).find((rubric) => rubric.is_active) ?? null;
  }

  function activeRubricCriteria(questionId: number) {
    const rubric = activeRubricFor(questionId);
    const criteria = rubric?.rubric_json.criteria;
    return Array.isArray(criteria) ? criteria : [];
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
      const job = await importQuestionsFromPaper(assessmentId, selectedFile, questionImportProvider);
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

  async function handleRunAutomaticMappings(repairUnconfirmedOnly = false) {
    setRunningMappings(true);
    setError(null);
    setScriptPreparationMessage(null);
    try {
      const responses = await runAssessmentQuestionNodeMappings(assessmentId, {
        replace_existing: !repairUnconfirmedOnly,
        repair_unconfirmed_only: repairUnconfirmedOnly,
        provider: "local_qwen38_visual",
        expected_model: localAiStatus?.qwen38.model ?? "qwen3.8-27b-q4km",
        draft_only_confirmed: true,
        maximum_ocr_calls: 25,
      });
      setScriptPreparationMessage(
        `${responses.reduce((total, response) => total + response.mappings.filter((mapping) => mapping.answer_region_id != null).length, 0)} Qwen3.8 answer regions prepared${repairUnconfirmedOnly ? " while preserving confirmed evidence" : ""}. Confirm each complete boundary, then request its verbatim Qwen3.8 transcription.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to prepare the answer script with local AI");
    } finally {
      setRunningMappings(false);
    }
  }

  async function handleRunVisualMappingRescue(submissionId: number) {
    setRunningMappings(true);
    setError(null);
    setScriptPreparationMessage(null);
    try {
      const submission = submissions.find((item) => item.id === submissionId);
      const response = await runSubmissionQuestionNodeMappings(submissionId, {
        replace_existing: false,
        repair_unconfirmed_only: true,
        provider: "local_qwen38_visual",
        expected_model: localAiStatus?.qwen38.model ?? "qwen3.8-27b-q4km",
        draft_only_confirmed: true,
        maximum_ocr_calls: Math.min(Math.max(submission?.pages.length ?? 1, 1), 25),
      });
      setScriptPreparationMessage(
        `Qwen3.8 visually repaired submission #${submissionId}: ${response.mappings.filter((mapping) => mapping.answer_region_id != null).length} review-only regions. Compare every red boundary with the complete page; no transcription or grade was created.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to repair answer boundaries with local Qwen3.8");
    } finally {
      setRunningMappings(false);
    }
  }

  async function handlePrepareSubmissionWithQwen38(submissionId: number) {
    setRunningMappings(true);
    setError(null);
    setScriptPreparationMessage(null);
    try {
      const submission = submissions.find((item) => item.id === submissionId);
      const response = await runSubmissionQuestionNodeMappings(submissionId, {
        replace_existing: false,
        repair_unconfirmed_only: false,
        provider: "local_qwen38_visual",
        expected_model: localAiStatus?.qwen38.model ?? "qwen3.8-27b-q4km",
        draft_only_confirmed: true,
        maximum_ocr_calls: Math.min(Math.max(submission?.pages.length ?? 1, 1), 25),
      });
      setScriptPreparationMessage(
        `Qwen3.8 prepared submission #${submissionId}: ${response.mappings.filter((mapping) => mapping.answer_region_id != null).length} review-only answer regions. Existing submissions and approved grades were not changed.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to prepare this answer script with local Qwen3.8");
    } finally {
      setRunningMappings(false);
    }
  }

  async function handleConfirmMapping(mapping: AnswerRegionMapping) {
    setConfirmingMappingId(mapping.id);
    setError(null);
    try {
      await confirmQuestionNodeMapping(mapping.id, true);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to confirm mapping");
    } finally {
      setConfirmingMappingId(null);
    }
  }

  async function handleLocalQwenGrade(answerRegionId: number) {
    if (!activeGradingRun) {
      setError("Start a Custom Controlled grading run before local Qwen grading.");
      return;
    }
    setGradingRegionId(answerRegionId);
    setError(null);
    try {
      await gradeAnswerRegionWithLocalQwen38(answerRegionId, {
        grading_run_id: activeGradingRun.id,
        provider: "llama_cpp_qwen38",
        expected_model: localAiStatus?.qwen38.model ?? "qwen3.8-27b-q4km",
        draft_only_confirmed: true,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Local Qwen3.8 grading failed");
    } finally {
      setGradingRegionId(null);
    }
  }

  async function handleGradeAllApproved() {
    if (!activeGradingRun) {
      setError("Start a Custom Controlled grading run before local Qwen grading.");
      return;
    }
    if (approvedBatchRegionIds.length === 0) {
      setError("No ungraded answer has both approved final-intent transcription and full-answer confirmation.");
      return;
    }
    setGradingAllApproved(true);
    setBatchGradeResult(null);
    setError(null);
    try {
      const result = await gradeAllApprovedAnswersWithLocalQwen38(assessmentId, {
        grading_run_id: activeGradingRun.id,
        provider: "llama_cpp_qwen38",
        expected_model: localAiStatus?.qwen38.model ?? "qwen3.8-27b-q4km",
        draft_only_confirmed: true,
        call_limit: Math.min(approvedBatchRegionIds.length, 25),
        stop_on_failure: true,
      });
      setBatchGradeResult(result);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "One-click local Qwen3.8 grading failed");
    } finally {
      setGradingAllApproved(false);
    }
  }

  async function handleRunVisualTranscription(mapping: AnswerRegionMapping) {
    if (!mapping.answer_region_id) return;
    const regionId = mapping.answer_region_id;
    setRunningOcrRegionId(regionId);
    setError(null);
    try {
      let run = await createVisualTranscriptionRun(
        regionId,
        localAiStatus?.qwen38.model ?? "qwen3.8-27b-q4km",
      );
      setOcrRunsByRegionId((current) => ({
        ...current,
        [regionId]: [run, ...(current[regionId] ?? []).filter((item) => item.id !== run.id)],
      }));
      for (let attempt = 0; attempt < 240 && ["queued", "running"].includes(run.status); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 3000));
        run = await getVisualTranscriptionRun(run.id);
        setOcrRunsByRegionId((current) => ({
          ...current,
          [regionId]: [run, ...(current[regionId] ?? []).filter((item) => item.id !== run.id)],
        }));
      }
      if (["queued", "running"].includes(run.status)) {
        setError("Visual transcription is still running. Reload this page to continue reviewing it.");
      } else if (run.status === "failed" || run.status === "uncertain") {
        setError(run.error ?? "Visual transcription did not complete safely.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Qwen3.8 visual transcription could not start");
    } finally {
      setRunningOcrRegionId(null);
    }
  }

  function rememberVisualRun(regionId: number, run: AnswerRegionOcrRun) {
    setOcrRunsByRegionId((current) => ({
      ...current,
      [regionId]: [run, ...(current[regionId] ?? []).filter((item) => item.id !== run.id)],
    }));
  }

  async function handleConfirmVisualTranscription(mapping: AnswerRegionMapping, run: AnswerRegionOcrRun) {
    if (!mapping.answer_region_id || !run.candidate_set_sha256) return;
    const regionId = mapping.answer_region_id;
    setConfirmingVisualRunId(run.id);
    setError(null);
    try {
      const confirmed = await confirmVisualTranscriptionRun(regionId, run.id, run.candidate_set_sha256);
      // Keep the returned run: load() cannot rehydrate it, so without this the
      // confirmed transcription would vanish from the screen.
      rememberVisualRun(regionId, confirmed);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Visual transcription confirmation failed");
    } finally {
      setConfirmingVisualRunId(null);
    }
  }

  async function handleRejectVisualTranscription(mapping: AnswerRegionMapping, run: AnswerRegionOcrRun) {
    if (!mapping.answer_region_id) return;
    const regionId = mapping.answer_region_id;
    setConfirmingVisualRunId(run.id);
    setError(null);
    try {
      const rejected = await rejectVisualTranscriptionRun(regionId, run.id, "all_candidates_wrong");
      rememberVisualRun(regionId, rejected);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Visual transcription rejection failed");
    } finally {
      setConfirmingVisualRunId(null);
    }
  }

  async function handleRunThinkingRepair(
    mapping: AnswerRegionMapping,
    sourceRun: AnswerRegionOcrRun,
  ) {
    if (!mapping.answer_region_id) return;
    const regionId = mapping.answer_region_id;
    setRepairingOcrRegionId(regionId);
    setError(null);
    try {
      let run = await createVisualTranscriptionThinkingRepair(
        regionId,
        sourceRun.id,
        localAiStatus?.qwen38.model ?? "qwen3.8-27b-q4km",
      );
      rememberVisualRun(regionId, run);
      for (let attempt = 0; attempt < 360 && ["queued", "running"].includes(run.status); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 3000));
        run = await getVisualTranscriptionRun(run.id);
        rememberVisualRun(regionId, run);
      }
      if (["queued", "running"].includes(run.status)) {
        setError("Thinking repair is still running. Reload this page to continue reviewing it.");
      } else if (["failed", "uncertain"].includes(run.status)) {
        setError(run.error ?? "Thinking repair did not complete safely.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Qwen3.8 thinking repair could not start");
    } finally {
      setRepairingOcrRegionId(null);
    }
  }

  async function handleConfirmThinkingRepair(
    mapping: AnswerRegionMapping,
    run: AnswerRegionOcrRun,
  ) {
    if (!mapping.answer_region_id || !run.output_sha256) return;
    const decisionSetSha256 = run.normalized_result?.decision_set_sha256;
    if (typeof decisionSetSha256 !== "string") {
      setError("Thinking repair decision integrity data is missing; confirmation is blocked.");
      return;
    }
    const regionId = mapping.answer_region_id;
    setConfirmingVisualRunId(run.id);
    setError(null);
    try {
      const confirmed = await confirmVisualTranscriptionThinkingRepair(regionId, run.id, {
        draft_text_sha256: run.output_sha256,
        decision_set_sha256: decisionSetSha256,
        reviewed_decision_indexes: reviewedRepairDecisions[run.id] ?? [],
      });
      rememberVisualRun(regionId, confirmed);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Thinking repair confirmation failed");
    } finally {
      setConfirmingVisualRunId(null);
    }
  }

  async function handleRejectThinkingRepair(
    mapping: AnswerRegionMapping,
    run: AnswerRegionOcrRun,
  ) {
    if (!mapping.answer_region_id) return;
    const regionId = mapping.answer_region_id;
    setConfirmingVisualRunId(run.id);
    setError(null);
    try {
      const rejected = await rejectVisualTranscriptionThinkingRepair(
        regionId,
        run.id,
        "all_candidates_wrong",
      );
      rememberVisualRun(regionId, rejected);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Thinking repair rejection failed");
    } finally {
      setConfirmingVisualRunId(null);
    }
  }

  async function handleSaveManualMapping(mapping: AnswerRegionMapping) {
    if (!mappingPageId || !selectedMappingQuestionNodeId) {
      setError("Select a question node and page before saving a manual mapping correction.");
      return;
    }
    setSavingMappingId(mapping.id);
    setError(null);
    try {
      await updateQuestionNodeMapping(mapping.id, {
        question_node_id: Number(selectedMappingQuestionNodeId),
        page_id: Number(mappingPageId),
        x: mappingX,
        y: mappingY,
        width: mappingWidth,
        height: mappingHeight,
        manual_answer_text: mappingManualAnswerText.trim() || null,
        confidence: 1,
        mapping_status: "mapped",
        blocker_reason: null,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save manual mapping correction");
    } finally {
      setSavingMappingId(null);
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
        manual_answer_text: manualAnswerText.trim() || null,
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
      setError("Select a page before suggesting answer mappings");
      return;
    }
    setSuggestingRegions(true);
    setError(null);
    setRegionSuggestionMessage(null);
    setRegionSuggestionWarnings([]);
    try {
      const response = await suggestAnswerRegionMappings(selectedPage.submission.id, {
        provider: regionSuggestionProvider,
        question_ids: questions.map((question) => question.id),
        page_ids: selectedPage.submission.pages.map((page) => page.id),
      });
      setSuggestionPageId(selectedPage.page.id);
      setRegionSuggestions(response.suggestion_groups);
      setRegionSuggestionMessage(response.message);
      setRegionSuggestionWarnings(response.provider_warnings);
      if (response.suggestion_groups[0]?.segments[0]) {
        const firstGroup = response.suggestion_groups[0];
        const first = firstGroup.segments[0];
        setRegionX(String(first.x));
        setRegionY(String(first.y));
        setRegionWidth(String(first.width));
        setRegionHeight(String(first.height));
        setSelectedQuestionId(String(firstGroup.suggested_question_id));
      }
    } catch (err) {
      setRegionSuggestions([]);
      setRegionSuggestionMessage(null);
      setRegionSuggestionWarnings([]);
      setError(err instanceof Error ? err.message : "Failed to suggest answer mappings");
    } finally {
      setSuggestingRegions(false);
    }
  }

  async function handleAcceptRegionSuggestion(suggestion: DraftAnswerRegionSuggestionGroup) {
    if (!selectedPage) {
      setError("Select a page before accepting answer-region mapping suggestions");
      return;
    }
    setAcceptingSuggestionId(suggestion.draft_id);
    setError(null);
    try {
      await acceptAnswerRegionMappingSuggestion(selectedPage.submission.id, {
        draft_id: suggestion.draft_id,
        question_id: suggestion.suggested_question_id,
        full_answer_confirmed: suggestion.continuation_risk === "continuation_included",
        segments: suggestion.segments,
      });
      setRegionSuggestions((current) => current.filter((item) => item.draft_id !== suggestion.draft_id));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to accept answer-region mapping suggestion");
    } finally {
      setAcceptingSuggestionId(null);
    }
  }

  async function handleEvidenceCorrection(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply evidence correction");
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

  async function handleCreateEvidencePrepRun() {
    setCreatingEvidencePrepRun(true);
    setError(null);
    try {
      const run = await createEvidencePrepRun(assessmentId);
      setEvidencePrepSummary(run);
      const queueSummary = await getGradingQueueSummary(assessmentId).catch(() => null);
      setGradingQueueSummary(queueSummary);
    } catch (err) {
      setError(err instanceof Error ? `Evidence preparation failed: ${err.message}` : "Evidence preparation failed");
    } finally {
      setCreatingEvidencePrepRun(false);
    }
  }

  async function handleCreateGradingQueueRun() {
    setCreatingGradingQueueRun(true);
    setError(null);
    try {
      const run = await createGradingQueueRun(assessmentId);
      setGradingQueueSummary(run);
    } catch (err) {
      setError(err instanceof Error ? `Grading queue scaffold failed: ${err.message}` : "Grading queue scaffold failed");
    } finally {
      setCreatingGradingQueueRun(false);
    }
  }

  return (
    <div className="space-y-6">
      {loading ? <LoadingState /> : null}
      {error && <ErrorState message={error} />}
      <section className="grid gap-4 rounded-2xl border border-slate-800 bg-slate-900 p-6 md:grid-cols-[1fr_auto] md:items-start">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Assessment workspace</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">{assessment?.title ?? "Assessment"}</h1>
          {assessment ? (
            <p className="mt-2 text-sm text-slate-400">
              {assessment.assessment_type} · {assessment.total_marks} marks · {assessment.status}
            </p>
          ) : null}
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
            {referencesReady
              ? "References are ready. Grade a whole class from one ZIP — the run maps, transcribes, and drafts scores in the background and only stops to ask you about exceptions."
              : "Prepare and confirm the question, solution, and rubric before student work is unlocked."}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          {referencesReady ? (
            <Link
              className="rounded bg-emerald-400 px-5 py-2.5 text-base font-semibold text-slate-950 shadow hover:bg-emerald-300"
              href={`/assessments/${assessmentId}/bulk-evaluation`}
            >
              Grade a class from a ZIP
            </Link>
          ) : null}
          <Link className={buttonClass} href={`/assessments/${assessmentId}/grading-run`}>
            {referencesReady ? "Review references" : "Prepare references"}
          </Link>
        </div>
      </section>

      {process.env.NEXT_PUBLIC_SHOW_LEGACY_REFERENCE_TOOLS === "true" ? <>
      <section className="rounded border border-emerald-700 bg-emerald-950/30 p-5">
        <p className="text-sm font-semibold uppercase tracking-wide text-emerald-200">Custom Controlled V0 — Manual Evidence Grading</p>
        <h2 className="mt-1 text-2xl font-semibold">Founder/teacher pilot flow for ready evidence → single-packet draft grading → teacher approval.</h2>
        <p className="mt-2 text-emerald-100">Teacher supplies question, model answer, active rubric, and student answer evidence before grading.</p>
        <p className="mt-1 text-amber-100">Manual answer text is required for V0 reliable grading.</p>
        <p className="mt-1 text-amber-100">Every real-provider result is a draft GradeSuggestion only.</p>
        <p className="mt-1 text-amber-100">Local Qwen cohort dispatch is available only from the grading-run page after an explicit capped preflight.</p>
        <p className="mt-1 text-amber-100">Teacher review is required. No autonomous mode, automatic FinalGrade, or export without teacher approval.</p>
      </section>

      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Custom Controlled V0 step map</h2>
        <p className="mt-2 text-sm text-slate-300">Use this Manual Evidence Grading flow for the founder/teacher pilot.</p>
        <p className="text-sm text-slate-400">Reference-material upload helper is support for Step 1 only; it is not a separate workflow.</p>
        <ol className="mt-4 grid gap-2 text-sm md:grid-cols-2">
          {[
            "Step 1: Reference materials",
            "Step 2: Question, model answer, and rubric",
            "Step 3: Student script/upload",
            "Step 4: Answer evidence and manual answer text",
            "Step 5: Evidence readiness",
            "Step 6: Queue scaffold",
            "Step 7: Real draft grade, teacher review, approval/export",
            "STOP: Do not run real grading unless evidence packet is ready",
          ].map((step) => (
            <li key={step} className="rounded border border-slate-800 bg-slate-950/40 p-3">{step}</li>
          ))}
        </ol>
      </section>

      <section className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Pilot context: Current teacher / assessment</h2>
          <p className="text-sm text-slate-400">Select/login teacher and confirm this is the intended synthetic/demo assessment before preparing evidence.</p>
        </div>
        <DemoTeacherSelector onTeacherChange={setSelectedTeacher} />
      </section>

      <section className="grid gap-4 rounded border border-cyan-900 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Step 1: Reference materials</h2>
          <p className="text-sm text-slate-300">Upload reference materials in the Custom Controlled material step, then return here.</p>
          <p className="text-sm text-slate-400">Reference materials mean the question paper, solution/model answer, and rubric PDFs. They must be uploaded and confirmed before questions/rubrics can be confirmed.</p>
        </div>
        <Link className={buttonClass} href={`/assessments/${assessmentId}/grading-run`}>
          Open Reference-material upload helper for Step 1 only
        </Link>
      </section>

      <section className="grid gap-4 rounded border border-cyan-900 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Step 2: Question, model answer, and rubric</h2>
          <p className="text-sm text-slate-300">Create or import the question, add the model answer, then open each grading unit to add one active rubric.</p>
          <p className="text-sm text-amber-200">Confirm questions/rubrics is blocked until: grading/evidence run exists, question paper uploaded, solution/model answer uploaded, rubric uploaded, materials confirmed, at least one canonical question exists, and every canonical question has an active rubric.</p>
          <p className="text-sm text-cyan-200">When blocked, use Step 1 for materials or this Step 2 area for questions/rubrics before trying confirmation again.</p>
        </div>
      </section>

      <section className="grid gap-4 rounded border border-cyan-900 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Questions, model answers, and rubric</h2>
          <p className="mt-2 text-sm text-slate-300">
            Upload and extract all three reference documents in one place. The old question-only upload has been removed from the teacher workflow.
          </p>
        </div>
        <Link className={buttonClass} href={`/assessments/${assessmentId}/grading-run`}>
          Open reference preparation
        </Link>
      </section>
      </> : null}

      {process.env.NEXT_PUBLIC_SHOW_LEGACY_REFERENCE_TOOLS === "true" ? <>
      <section className="grid gap-4 rounded border border-amber-900 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Step 2 helper: Import questions from reference paper</h2>
          <p className="text-sm text-amber-200">Draft extraction. Teacher review required.</p>
          <p className="text-sm text-slate-400">Default extraction is mock/simple. The supervised thinking-disabled Qwen3.8 visual reference workflow is available from the Custom Controlled run screen.</p>
          <p className="text-sm text-slate-400">Drafts never become canonical until the teacher selects, edits, and accepts them below.</p>
        </div>
        <form onSubmit={handleQuestionImport} className="grid gap-3">
          <label className="grid gap-2 text-sm">
            Draft extraction provider
            <select
              className={inputClass}
              value={questionImportProvider}
              onChange={(event) => setQuestionImportProvider(event.target.value as QuestionImportProvider)}
            >
              <option value="mock">Mock/simple (default)</option>
            </select>
          </label>
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
          <button
            className={buttonClass}
            disabled={importingQuestions || !questionImportFile}
            type="submit"
          >
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

      <section className="grid gap-4 rounded border border-cyan-900 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Step 2A: Extracted question tree and rubric confirmation</h2>
          <p className="text-sm text-slate-300">Experimental uploaded-document review. Teacher confirmation required before extracted materials are treated as grading-ready.</p>
          <p className="text-sm text-amber-200">Unconfirmed extracted question nodes or rubric criteria will block grading-run confirmation. Unresolved extraction blockers must be shown honestly, not treated as success.</p>
          <p className="text-sm text-slate-400">Manual question/model answer/rubric creation below still remains available and persists after refresh.</p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded border border-slate-800 p-3 text-sm text-slate-300">
            <p className="font-semibold">Extracted question tree</p>
            <p>{confirmedQuestionNodeCount}/{questionNodes.length} nodes confirmed</p>
          </div>
          <div className="rounded border border-slate-800 p-3 text-sm text-slate-300">
            <p className="font-semibold">Extracted rubric</p>
            <p>{confirmedRubricCriterionCount}/{rubricCriteria.length} criteria confirmed · blockers: {unresolvedRubricBlockerCount}</p>
          </div>
        </div>
        {questionNodes.length === 0 ? (
          <p className="rounded border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-100">No extracted question tree yet. Upload/extract first, or use the manual creation path below.</p>
        ) : (
          <div className="grid gap-3">
            {questionNodes.map((node) => {
              const draft = questionNodeDrafts[node.id] ?? questionNodeDraftFor(node);
              return (
                <article key={node.id} className="grid gap-3 rounded border border-slate-800 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="text-lg font-semibold">{draft.question_number || node.question_number} · {node.node_type}</h3>
                      <p className="text-xs text-slate-400">Run #{node.extraction_run_id} · page {node.source_page ?? "?"} · confidence {node.confidence ?? "n/a"}</p>
                    </div>
                    <label className="flex items-center gap-2 text-sm text-emerald-200">
                      <input
                        type="checkbox"
                        checked={draft.teacher_confirmed}
                        onChange={(event) => updateQuestionNodeDraft(node.id, { teacher_confirmed: event.target.checked })}
                      />
                      Teacher confirmed
                    </label>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <input className={inputClass} aria-label={`Extracted question number ${node.id}`} value={draft.question_number} onChange={(event) => updateQuestionNodeDraft(node.id, { question_number: event.target.value })} />
                    <input className={inputClass} aria-label={`Extracted parent question ${node.id}`} placeholder="Parent question number if subquestion" value={draft.parent_question_number} onChange={(event) => updateQuestionNodeDraft(node.id, { parent_question_number: event.target.value })} />
                    <input className={inputClass} aria-label={`Extracted label ${node.id}`} value={draft.label} onChange={(event) => updateQuestionNodeDraft(node.id, { label: event.target.value })} />
                    <input className={inputClass} aria-label={`Extracted marks ${node.id}`} placeholder="Marks" value={draft.marks} onChange={(event) => updateQuestionNodeDraft(node.id, { marks: event.target.value })} />
                    <input className={inputClass} aria-label={`Extracted source page ${node.id}`} placeholder="Source page" value={draft.source_page} onChange={(event) => updateQuestionNodeDraft(node.id, { source_page: event.target.value })} />
                  </div>
                  <textarea className={inputClass} aria-label={`Extracted question text ${node.id}`} value={draft.text} onChange={(event) => updateQuestionNodeDraft(node.id, { text: event.target.value })} />
                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    <button className={buttonClass} disabled={savingQuestionNodeId === node.id} type="button" onClick={() => void handleSaveQuestionNode(node)}>
                      {savingQuestionNodeId === node.id ? "Saving extracted node..." : "Save extracted node"}
                    </button>
                    <span className={draft.teacher_confirmed ? "text-emerald-300" : "text-amber-200"}>
                      {draft.teacher_confirmed ? "Teacher-confirmed and persisted after save." : "Teacher confirmation required before grading."}
                    </span>
                  </div>
                </article>
              );
            })}
          </div>
        )}
        {rubricCriteria.length === 0 ? (
          <p className="rounded border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-100">No extracted rubric yet. Upload/extract first, or continue with the manual rubric path below.</p>
        ) : (
          <div className="grid gap-3">
            {rubricCriteria.map((criterion) => {
              const draft = rubricCriterionDrafts[criterion.id] ?? rubricCriterionDraftFor(criterion);
              return (
                <article key={criterion.id} className="grid gap-3 rounded border border-slate-800 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="text-lg font-semibold">{draft.question_number || criterion.question_number || "Unlinked"} · {draft.criterion_label || criterion.criterion_label}</h3>
                      <p className="text-xs text-slate-400">Run #{criterion.extraction_run_id} · confidence {criterion.confidence ?? "n/a"}</p>
                    </div>
                    <label className="flex items-center gap-2 text-sm text-emerald-200">
                      <input
                        type="checkbox"
                        checked={draft.teacher_confirmed}
                        onChange={(event) => updateRubricCriterionDraft(criterion.id, { teacher_confirmed: event.target.checked })}
                      />
                      Teacher confirmed
                    </label>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <input className={inputClass} aria-label={`Extracted rubric question ${criterion.id}`} value={draft.question_number} onChange={(event) => updateRubricCriterionDraft(criterion.id, { question_number: event.target.value })} />
                    <input className={inputClass} aria-label={`Extracted rubric max marks ${criterion.id}`} placeholder="Max marks" value={draft.max_marks} onChange={(event) => updateRubricCriterionDraft(criterion.id, { max_marks: event.target.value })} />
                    <input className={inputClass} aria-label={`Extracted rubric label ${criterion.id}`} value={draft.criterion_label} onChange={(event) => updateRubricCriterionDraft(criterion.id, { criterion_label: event.target.value })} />
                  </div>
                  <textarea className={inputClass} aria-label={`Extracted rubric description ${criterion.id}`} value={draft.description} onChange={(event) => updateRubricCriterionDraft(criterion.id, { description: event.target.value })} />
                  <textarea className={inputClass} aria-label={`Extracted rubric blocker ${criterion.id}`} placeholder="Leave blank when resolved. Any saved blocker will continue to block grading readiness." value={draft.blocker} onChange={(event) => updateRubricCriterionDraft(criterion.id, { blocker: event.target.value })} />
                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    <button className={buttonClass} disabled={savingRubricCriterionId === criterion.id} type="button" onClick={() => void handleSaveRubricCriterion(criterion)}>
                      {savingRubricCriterionId === criterion.id ? "Saving extracted rubric..." : "Save extracted rubric"}
                    </button>
                    <span className={draft.teacher_confirmed && !draft.blocker.trim() ? "text-emerald-300" : "text-amber-200"}>
                      {draft.teacher_confirmed && !draft.blocker.trim()
                        ? "Teacher-confirmed rubric criterion ready for grading gate checks."
                        : "Teacher confirmation required. Saved blockers remain visible and block grading readiness."}
                    </span>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
      </> : null}

      <details className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
        <summary className="cursor-pointer font-semibold text-slate-200">Manual reference editing (advanced)</summary>
        <div className="mt-5 grid gap-5">
      <form onSubmit={handleSubmit} className="grid gap-4 rounded border border-slate-800 bg-slate-950/30 p-5">
        <h2 className="text-xl font-semibold">Step 2: Question, model answer, and rubric — manual creation</h2>
        <p className="text-sm text-slate-400">Manual question creation remains available. Model answer is required for Custom Controlled V0 readiness.</p>
        <input className={inputClass} placeholder="Question number" value={questionNo} onChange={(event) => setQuestionNo(event.target.value)} required />
        <textarea className={inputClass} placeholder="Question text" value={questionText} onChange={(event) => setQuestionText(event.target.value)} required />
        <textarea className={inputClass} placeholder="Model answer required for V0 readiness" value={modelAnswer} onChange={(event) => setModelAnswer(event.target.value)} />
        <input className={inputClass} placeholder="Total marks" value={totalMarks} onChange={(event) => setTotalMarks(event.target.value)} required />
        <button className={buttonClass} disabled={submitting} type="submit">
          {submitting ? "Creating..." : "Create question"}
        </button>
      </form>

      {!loading && questions.length === 0 ? <EmptyState message="No questions yet." /> : null}
      <div className="grid gap-3">
        {questions.map((question) => {
          const draft = manualSetupDrafts[question.id] ?? manualSetupDraftFor(question);
          const activeRubric = activeRubricFor(question.id);
          const criteria = activeRubricCriteria(question.id);
          const modelAnswerMissing = !draft.model_answer.trim();
          return (
            <article key={question.id} className="grid gap-3 rounded border border-slate-800 bg-slate-900 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Grading unit {question.question_no}</h2>
                  <p className="text-sm text-slate-400">{question.total_marks} marks · {gradingUnitType(question.question_no)}</p>
                </div>
                <Link href={`/questions/${question.id}`} className="text-sm text-cyan-300 underline">
                  Open full rubric editor
                </Link>
              </div>
              <label className="grid gap-2 text-sm">
                Question text
                <textarea className={inputClass} value={draft.question_text} onChange={(event) => updateManualSetupDraft(question.id, { question_text: event.target.value })} />
              </label>
              <button className={buttonClass} disabled={savingQuestionId === question.id} type="button" onClick={() => void handleSaveQuestion(question)}>
                {savingQuestionId === question.id ? "Saving question..." : "Save question"}
              </button>
              <label className="grid gap-2 text-sm">
                Model answer required for grading
                <textarea className={inputClass} value={draft.model_answer} onChange={(event) => updateManualSetupDraft(question.id, { model_answer: event.target.value })} />
              </label>
              <button className={buttonClass} disabled={savingModelAnswerId === question.id} type="button" onClick={() => void handleSaveModelAnswer(question)}>
                {savingModelAnswerId === question.id ? "Saving model answer..." : "Save model answer"}
              </button>
              {modelAnswerMissing ? (
                <p className="rounded border border-amber-800 bg-amber-950/30 p-2 text-sm text-amber-100">Model answer required for grading</p>
              ) : (
                <p className="rounded border border-emerald-800 bg-emerald-950/30 p-2 text-sm text-emerald-100">Saved model answer visible: {question.model_answer ?? draft.model_answer}</p>
              )}
              <div className="grid gap-3 rounded border border-slate-800 p-3">
                <p className="text-sm font-semibold">Active rubric required for grading</p>
                <input className={inputClass} aria-label={`Rubric criterion name for ${question.question_no}`} value={draft.criteria_name} onChange={(event) => updateManualSetupDraft(question.id, { criteria_name: event.target.value })} />
                <textarea className={inputClass} aria-label={`Rubric criterion description for ${question.question_no}`} value={draft.criteria_description} onChange={(event) => updateManualSetupDraft(question.id, { criteria_description: event.target.value })} />
                <input className={inputClass} aria-label={`Rubric criterion marks for ${question.question_no}`} type="number" min="0.01" step="0.01" value={draft.criteria_marks} onChange={(event) => updateManualSetupDraft(question.id, { criteria_marks: event.target.value })} />
                <button className={buttonClass} disabled={savingRubricQuestionId === question.id} type="button" onClick={() => void handleSaveRubric(question)}>
                  {savingRubricQuestionId === question.id ? "Saving rubric..." : "Save rubric"}
                </button>
                {activeRubric ? (
                  <div className="rounded border border-emerald-800 bg-emerald-950/30 p-2 text-sm text-emerald-100">
                    <p>Active rubric confirmed: version {activeRubric.version}</p>
                    <p>Criteria: {criteria.length > 0 ? JSON.stringify(criteria) : "No criteria visible"}</p>
                  </div>
                ) : (
                  <p className="rounded border border-amber-800 bg-amber-950/30 p-2 text-sm text-amber-100">Active rubric required for grading</p>
                )}
              </div>
            </article>
          );
        })}
      </div>
        </div>
      </details>

      {!loading && !referencesReady ? (
        <section className="rounded-2xl border border-amber-800/70 bg-amber-950/20 p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-300">Student work locked</p>
          <h2 className="mt-2 text-xl font-semibold">Finish reference review first</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
            Confirm at least one question, its model answer, and an active rubric. Student uploads and grading controls will appear only after that gate passes.
          </p>
        </section>
      ) : null}

      {referencesReady ? <>
      <form ref={uploadFormRef} onSubmit={handleUpload} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Student scripts</p>
          <h2 className="mt-1 text-xl font-semibold">Upload one answer script</h2>
          <p className="text-sm text-slate-400">
            PDF, PNG, JPG, or JPEG. Uploading stores pages only; it does not grade them.
            This single-script form is for one student — reviewing a whole class here
            means confirming every answer by hand.
          </p>
          <p className="mt-2 text-sm text-emerald-200">
            Grading a class?{" "}
            <Link className="font-semibold underline" href={`/assessments/${assessmentId}/bulk-evaluation`}>
              Grade a class from a ZIP
            </Link>{" "}
            runs mapping, transcription, and draft scoring in the background and surfaces
            only the answers that need you.
          </p>
        </div>
        <input className={inputClass} name="student_identifier" placeholder="student_identifier" value={studentIdentifier} onChange={(event) => setStudentIdentifier(event.target.value)} required />
        <input className={inputClass} placeholder="Student name (optional)" value={studentName} onChange={(event) => setStudentName(event.target.value)} />
        <input
          data-testid="submission-file-input"
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

      <details className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
        <summary className="cursor-pointer font-semibold text-slate-200">
          Import a ZIP without grading it (advanced)
        </summary>
      <form onSubmit={handleZipUpload} className="mt-5 grid gap-4">
        <div>
          <h2 className="text-xl font-semibold">Import scripts only</h2>
          {/* This path only creates submissions. Every imported script then needs
              its regions checked, its transcription confirmed, and grading started
              BY HAND, one answer at a time -- which is unusable for a class-sized
              ZIP. Teachers reached for this because it was the only control in the
              scripts area that mentioned a ZIP; the supervised run is what they
              actually wanted, so it is named here explicitly. */}
          <p className="rounded border border-amber-700/60 bg-amber-950/20 p-3 text-sm text-amber-100">
            This imports pages only. You would then confirm regions, transcription, and
            grading by hand for every answer of every script. To grade a class, use{" "}
            <Link className="font-semibold underline" href={`/assessments/${assessmentId}/bulk-evaluation`}>
              Grade a class from a ZIP
            </Link>{" "}
            instead — it does the mapping, transcription, and draft scoring for you and
            asks only about the answers it could not read confidently.
          </p>
          <p className="mt-2 text-sm text-slate-400">The ZIP may contain PDF, PNG, JPG, or JPEG files. Unsupported entries are reported and skipped.</p>
        </div>
        <label className="grid gap-2 text-sm">
          Student identifier strategy
          <select className={inputClass} value={zipIdentifierStrategy} onChange={(event) => setZipIdentifierStrategy(event.target.value as "basename" | "sequential")}>
            <option value="basename">Use file basename</option>
            <option value="sequential">Generated sequential IDs</option>
          </select>
        </label>
        <input className={inputClass} placeholder="Student name prefix (optional)" value={zipStudentNamePrefix} onChange={(event) => setZipStudentNamePrefix(event.target.value)} />
        <input data-testid="zip-file-input" className={inputClass} name="file" type="file" accept=".zip,application/zip,application/x-zip-compressed" onChange={handleZipUploadFileChange} />
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
      </details>

      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">Uploaded scripts</h2>
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

      {submissions.length > 0 ? <>
      <section className="grid gap-4 rounded border border-cyan-800 bg-slate-900 p-5" data-testid="local-script-preparation">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <h2 className="text-xl font-semibold">Prepare complete answer scripts</h2>
            <p className="mt-1 text-sm text-slate-300">
              Qwen3.8 vision reads each complete script page and maps one complete answer region to each finalized question, including ordered continuation segments. You do not crop, enter coordinates, or retype an answer.
            </p>
            <p className="mt-1 text-sm text-amber-200">
              Review the prepared image and evidence, then approve or reject it. The finalized question, solution, and rubric are reused automatically and remain read-only here.
            </p>
          </div>
          <div className="grid gap-2">
            {unpreparedSubmissions.map((submission) => (
              <button
                key={`prepare-submission-${submission.id}`}
                className={buttonClass}
                type="button"
                disabled={runningMappings || !localScriptPreparationAuthorized || !referencesReady || submission.pages.length === 0}
                onClick={() => void handlePrepareSubmissionWithQwen38(submission.id)}
              >
                {runningMappings
                  ? "Qwen3.8 vision is preparing a script..."
                  : `Prepare submission #${submission.id} with Qwen3.8 vision`}
              </button>
            ))}
            {unpreparedSubmissions.length === 0 ? (
              <p className="rounded border border-emerald-900 px-3 py-2 text-sm text-emerald-200">
                Every uploaded submission has preparation records. Existing submissions remain protected.
              </p>
            ) : null}
          </div>
          {flatMappings.some((mapping) => !mapping.teacher_confirmed) ? (
            <button
              className="rounded border border-amber-700 px-3 py-2 text-sm text-amber-100 hover:border-amber-500"
              type="button"
              disabled={runningMappings || !localScriptPreparationAuthorized || !referencesReady || pages.length === 0}
              onClick={() => void handleRunAutomaticMappings(true)}
            >
              {runningMappings ? "Repairing unresolved mappings..." : "Repair unconfirmed boundaries with Qwen3.8 vision"}
            </button>
          ) : null}
          {unresolvedMappingSubmissionIds.map((submissionId) => (
            <button
              key={`visual-mapping-rescue-${submissionId}`}
              className="rounded border border-violet-600 px-3 py-2 text-sm text-violet-100 hover:border-violet-400 disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              disabled={runningMappings || !localVisualMappingAuthorized}
              onClick={() => void handleRunVisualMappingRescue(submissionId)}
            >
              {runningMappings
                ? "Qwen3.8 boundary repair running..."
                : `Repair submission #${submissionId} boundaries with Qwen3.8 vision`}
            </button>
          ))}
        </div>
        <div className="grid gap-2 rounded border border-slate-800 p-3 text-xs text-slate-300 md:grid-cols-3">
          <p>Finalized references: {referencesReady ? "ready" : "blocked"}</p>
          <p>Script pages: {pages.length}</p>
          <p>Qwen3.8 standalone: {localAiStatus?.qwen38.available ? "ready" : localAiStatus?.qwen38.enabled ? "configured · starts on explicit action" : "disabled"}</p>
        </div>
        <p className="text-xs text-amber-200">Mapping, transcription, and grading are separate Qwen3.8 calls with fresh context and no retries. Repair preserves teacher-confirmed or graded evidence and never creates a transcript or grade.</p>
        {flatMappings.length > 0 ? (
          <p className="text-xs text-slate-300">
            Confirmed mappings are protected. Use Qwen3.8 boundary repair only for unconfirmed regions; it cannot replace confirmed evidence and creates no transcript or grade.
          </p>
        ) : null}
        {(unresolvedMappingSubmissionIds.length > 0 || unpreparedSubmissions.length > 0) && !localVisualMappingAuthorized ? (
          <p className="rounded border border-violet-900 bg-violet-950/20 p-3 text-sm text-violet-100">
            Qwen3.8 visual mapping is disabled in the host configuration. It must be explicitly enabled before scripts can be prepared or repaired.
          </p>
        ) : null}
        {!localScriptPreparationAuthorized ? (
          <p className="rounded border border-red-800 bg-red-950/30 p-3 text-sm text-red-100">
            Local script preparation is disabled in the host configuration. It must be explicitly enabled for this supervised rehearsal.
          </p>
        ) : null}
        {scriptPreparationMessage ? (
          <p className="rounded border border-emerald-800 bg-emerald-950/30 p-3 text-sm text-emerald-100">{scriptPreparationMessage}</p>
        ) : null}
        {answerRegions.length > 0 ? (
          <section className="grid gap-3 rounded border border-cyan-700 bg-cyan-950/20 p-4">
            <div>
              <h3 className="font-semibold text-cyan-100">One-click draft grading</h3>
              <p className="mt-1 text-xs text-slate-300">
                Grades every ungraded answer whose finalized surviving-work transcription and full-answer images are already teacher-approved. Calls run one at a time, stop on the first failure, and create drafts only.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button
                className={buttonClass}
                type="button"
                disabled={gradingAllApproved || !localSingleGradeAuthorized || !activeGradingRun || approvedBatchRegionIds.length === 0 || approvedBatchRegionIds.length > 25}
                onClick={() => void handleGradeAllApproved()}
              >
                {gradingAllApproved
                  ? "Qwen3.8 is grading approved answers sequentially..."
                  : `Grade all approved transcriptions (${approvedBatchRegionIds.length})`}
              </button>
              <span className="text-xs text-slate-400">Server ceiling: 25 calls · no retries · no automatic final grades</span>
            </div>
            {approvedBatchRegionIds.length > 25 ? (
              <p className="text-xs text-red-200">There are more than 25 ready answers. Grade a smaller supervised assessment; no partial batch will be started.</p>
            ) : null}
            {batchGradeResult ? (
              <p className={`text-xs ${batchGradeResult.failed_count ? "text-red-200" : "text-emerald-200"}`}>
                Completed {batchGradeResult.calls_completed} call(s): {batchGradeResult.graded_count} draft(s) created, {batchGradeResult.skipped_count} skipped, {batchGradeResult.failed_count} failed{batchGradeResult.stopped_on_failure ? "; stopped safely on the first failure" : ""}.
              </p>
            ) : null}
          </section>
        ) : null}
        {flatMappings.length === 0 ? (
          <EmptyState message="No prepared answer mappings yet. Upload the complete script, then run local preparation." />
        ) : (
          <div className="grid gap-3">
            {questionNodeMappings.flatMap((group) =>
              group.mappings.map((mapping) => {
                const warnings = localMappingWarnings(mapping);
                const visualRun = mapping.answer_region_id
                  ? [...(ocrRunsByRegionId[mapping.answer_region_id] ?? [])]
                      .filter((run) => run.profile === "qwen38_verbatim_visual")
                      .sort((left, right) => right.id - left.id)[0] ?? null
                  : null;
                const thinkingRepairRuns = mapping.answer_region_id
                  ? [...(ocrRunsByRegionId[mapping.answer_region_id] ?? [])]
                      .filter((run) => run.profile === "qwen38_thinking_repair" && run.normalized_result?.source_run_id === visualRun?.id)
                      .sort((left, right) => right.id - left.id)
                  : [];
                const thinkingRepairRun = thinkingRepairRuns[0] ?? null;
                const hasCurrentThinkingRepairRun = thinkingRepairRuns.some(
                  (run) => run.prompt_version === CURRENT_THINKING_REPAIR_PROMPT_VERSION,
                );
                const thinkingRepairFailureCode = typeof thinkingRepairRun?.normalized_result?.failure_code === "string"
                  ? thinkingRepairRun.normalized_result.failure_code
                  : null;
                const repairDecisions = thinkingRepairDecisions(thinkingRepairRun);
                const currentFinalIntentRun = Boolean(
                  visualRun?.prompt_version === CURRENT_FINAL_INTENT_PROMPT_VERSION,
                );
                const repairableFinalIntentRun = Boolean(
                  visualRun?.prompt_version && REPAIRABLE_FINAL_INTENT_PROMPT_VERSIONS.has(visualRun.prompt_version),
                );
                const requiresThinkingRepair = Boolean(
                  visualRun?.normalized_result?.requires_thinking_repair,
                );
                const baselineHasUnresolvedEvidence = Boolean(
                  visualRun && (
                    visualRun.warnings.includes("visual_transcription_uncertain") ||
                    visualRun.warnings.includes("uncertain_student_correction") ||
                    [
                      "[visibly crossed]",
                      "[overwritten]",
                      "[illegible crossed writing]",
                      "[unclear correction]",
                      "[illegible]",
                      "[visible writing unresolved",
                    ].some((marker) => (visualRun.draft_text ?? "").toLowerCase().includes(marker))
                  ),
                );
                const confirmedRun = thinkingRepairRun?.status === "confirmed"
                  ? thinkingRepairRun
                  : visualRun?.status === "confirmed" && repairableFinalIntentRun
                    ? visualRun
                    : null;
                const hasDraftSuggestion = Boolean(
                  mapping.answer_region_id && gradedRegionIds.has(mapping.answer_region_id),
                );
                const legacyRetranscriptionRequired = Boolean(
                  visualRun &&
                  !currentFinalIntentRun &&
                  visualRun.status !== "confirmed" &&
                  mapping.answer_region_id &&
                  !gradedRegionIds.has(mapping.answer_region_id) &&
                  !finalizedRegionIds.has(mapping.answer_region_id),
                );
                const failedCurrentRetranscriptionRequired = Boolean(
                  visualRun &&
                  currentFinalIntentRun &&
                  ["failed", "uncertain"].includes(visualRun.status) &&
                  mapping.answer_region_id &&
                  !gradedRegionIds.has(mapping.answer_region_id) &&
                  !finalizedRegionIds.has(mapping.answer_region_id),
                );
                const blankSafetyGate = mapping.mapping_status === "blocked" && !mapping.answer_region_id;
                const sourceSegments = mapping.answer_region?.segments ?? [];
                const sourceStates = mapping.answer_region_id == null
                  ? {}
                  : sourcePageImageStates[mapping.answer_region_id] ?? {};
                const sourcePagesState: AnswerRegionImageLoadState = sourceSegments.length === 0
                  ? "error"
                  : sourceSegments.some((segment) => sourceStates[segment.id] === "error")
                    ? "error"
                    : sourceSegments.every((segment) => sourceStates[segment.id] === "loaded")
                      ? "loaded"
                      : "loading";
                const cropStates = mapping.answer_region_id == null
                  ? {}
                  : segmentCropImageStates[mapping.answer_region_id] ?? {};
                const segmentCropsState: AnswerRegionImageLoadState = sourceSegments.length === 0
                  ? "error"
                  : sourceSegments.some((segment) => cropStates[segment.id] === "error")
                    ? "error"
                    : sourceSegments.every((segment) => cropStates[segment.id] === "loaded")
                      ? "loaded"
                      : "loading";
                const boundaryReviewed = mapping.answer_region_id == null
                  ? false
                  : Boolean(sourceBoundaryReviewed[mapping.answer_region_id]);
                return (
                  <article key={mapping.id} className="grid gap-3 rounded border border-slate-700 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <h3 className="font-semibold">{group.question_node.label} · submission #{mapping.submission_id}</h3>
                        <p className="text-xs text-slate-400">
                          {mapping.mapping_status} · mapping confidence {mapping.confidence ?? "n/a"} · {mapping.provider}
                        </p>
                        <p className="mt-1 max-w-4xl text-xs text-slate-300">Mapped question: {group.question_node.text}</p>
                      </div>
                      <span className={`rounded-full border px-2 py-1 text-xs ${mapping.teacher_confirmed || blankSafetyGate ? "border-emerald-700 text-emerald-200" : "border-amber-700 text-amber-200"}`}>
                        {mapping.teacher_confirmed ? "region confirmed" : blankSafetyGate ? "blank safety gate" : "approval required"}
                      </span>
                    </div>
                    {blankSafetyGate ? (
                      <p className="rounded border border-emerald-900 bg-emerald-950/20 p-3 text-sm text-emerald-100">
                        No visible answer was found. This question is excluded from local Qwen grading; no answer text will be fabricated.
                      </p>
                    ) : mapping.blocker_reason ? <p className="text-sm text-amber-200">{mapping.blocker_reason}</p> : null}
                    {mapping.answer_region_id ? (
                      <>
                        <details open={!mapping.teacher_confirmed || sourceSegments.length > 1} className="rounded border border-red-800 bg-red-950/20 p-3">
                          <summary className="cursor-pointer font-semibold text-red-100">Required: compare the crop boundary with the complete source page</summary>
                          <div className="mt-3 grid gap-3">
                            {sourceSegments.map((segment) => (
                              <AuthenticatedMappedSourcePage
                                key={segment.id}
                                answerRegionId={mapping.answer_region_id!}
                                segment={segment}
                                label={`Complete source page for ${group.question_node.label}, segment ${segment.order_index}`}
                                onLoadStateChange={handleSourcePageImageStateChange}
                              />
                            ))}
                            <label className="flex items-start gap-2 text-sm text-red-100">
                              <input
                                type="checkbox"
                                checked={boundaryReviewed}
                                disabled={sourcePagesState !== "loaded"}
                                onChange={(event) => setSourceBoundaryReviewed((current) => ({
                                  ...current,
                                  [mapping.answer_region_id!]: event.target.checked,
                                }))}
                              />
                              <span>I compared every red rectangle with the complete page and it contains the full answer without another question.</span>
                            </label>
                          </div>
                        </details>
                        <section className="grid gap-3 rounded border border-cyan-700 bg-cyan-950/10 p-3">
                          <div>
                            <p className="font-semibold text-cyan-100">
                              Complete prepared answer · {sourceSegments.length} segment{sourceSegments.length === 1 ? "" : "s"}
                            </p>
                            <p className="text-xs text-cyan-200">
                              Review every segment below in order. A continuation is part of the answer only when it appears here.
                            </p>
                          </div>
                          {sourceSegments.map((segment) => (
                            <AuthenticatedAnswerRegionSegmentImage
                              key={segment.id}
                              answerRegionId={mapping.answer_region_id!}
                              segmentId={segment.id}
                              orderIndex={segment.order_index}
                              alt={`Prepared answer segment ${segment.order_index} for ${group.question_node.label}, submission ${mapping.submission_id}`}
                              onLoadStateChange={handleSegmentCropImageStateChange}
                              editingDecisions={repairDecisions.filter((decision) => decision.page_index === segment.order_index)}
                            />
                          ))}
                        </section>
                      </>
                    ) : null}
                    {isLocalPreparedMapping(mapping) && mapping.answer_region_id ? (
                      <section className="grid gap-3 rounded border border-cyan-700 bg-slate-950/50 p-3 text-sm">
                        <div>
                          <p className="font-semibold text-slate-100">
                            Qwen3.8 visual mapping and grading
                          </p>
                          <p className="text-xs text-amber-200">Mapping, visible-evidence transcription, cancellation review, and full-answer coverage are separate teacher gates.</p>
                          <p className="text-xs text-slate-300">The thinking-disabled pass preserves visible student writing and only flags possible edits. If crossing, overwriting, or unresolved writing is present, a separate Thinking review must determine the final intended answer. Neither pass repairs the mathematics.</p>
                          {mapping.answer_region?.continuation_check_status === "possible_continuation" ? <p className="mt-2 rounded border border-red-800 bg-red-950/30 p-2 text-xs text-red-100">Incomplete mapping suspected: this crop reaches a page boundary while the next page has unassigned handwriting. Do not confirm it; use the explicit Qwen3.8 visual boundary rescue for this submission.</p> : null}
                        </div>
                        {!mapping.teacher_confirmed ? (
                          <button className={buttonClass} type="button" disabled={confirmingMappingId === mapping.id || segmentCropsState !== "loaded" || sourcePagesState !== "loaded" || !boundaryReviewed} onClick={() => void handleConfirmMapping(mapping)}>
                            {confirmingMappingId === mapping.id ? "Confirming region..." : segmentCropsState === "error" || sourcePagesState === "error" ? "All evidence images must load before confirmation" : segmentCropsState !== "loaded" || sourcePagesState !== "loaded" ? "Loading every source page and answer segment..." : !boundaryReviewed ? "Compare and acknowledge the full-page boundary first" : `Confirm all ${sourceSegments.length} displayed answer segment${sourceSegments.length === 1 ? "" : "s"}`}
                          </button>
                        ) : null}
                        {mapping.teacher_confirmed && (!visualRun || legacyRetranscriptionRequired || failedCurrentRetranscriptionRequired) ? (
                          <button className={buttonClass} type="button" disabled={runningOcrRegionId === mapping.answer_region_id || !localAiStatus?.qwen38.transcription_enabled} onClick={() => void handleRunVisualTranscription(mapping)}>
                            {runningOcrRegionId === mapping.answer_region_id
                              ? "Qwen3.8 is resolving corrections and transcribing..."
                              : failedCurrentRetranscriptionRequired
                                ? "Re-run evidence-preserving transcription"
                                : legacyRetranscriptionRequired
                                  ? "Re-transcribe with evidence-preserving rules"
                                  : "Transcribe visible answer evidence with Qwen3.8 vision"}
                          </button>
                        ) : null}
                        {visualRun ? (
                          <div className="grid gap-2 rounded border border-slate-700 p-3">
                            <p className="text-xs text-slate-300">Run #{visualRun.id} · {visualRun.status} · {visualRun.calls_used}/{visualRun.call_limit} visual calls · {visualRun.prompt_version ?? "legacy prompt"}</p>
                            {legacyRetranscriptionRequired ? (
                              <p className="rounded border border-amber-800 bg-amber-950/20 p-2 text-xs text-amber-100">
                                This transcript used the older combined transcription/cancellation policy. It cannot be directly confirmed; re-transcribe with the evidence-preserving policy or use the explicit Thinking repair when available.
                              </p>
                            ) : null}
                            {safeVisualTranscriptionError(visualRun.error) ? <p className="text-xs text-red-200">{safeVisualTranscriptionError(visualRun.error)}</p> : null}
                            {visualRun.warnings.includes("visible_edits_preserved") ? (
                              <p className="rounded border border-violet-800 bg-violet-950/20 p-2 text-xs text-violet-100">
                                Possible edits were detected. This evidence inventory preserves the visible writing; cancellation interpretation requires the explicit Thinking review below.
                              </p>
                            ) : null}
                            {visualRun.warnings.includes("thinking_repair_required") ? (
                              <p className="rounded border border-amber-700 bg-amber-950/30 p-2 text-xs font-semibold text-amber-100">
                                Possible cancellations or replacements were detected. Confirm this transcript only if it already contains exactly the student&apos;s surviving final work; otherwise run the Thinking comparison.
                              </p>
                            ) : null}
                            {visualRun.warnings.includes("student_replacement_detected") ? (
                              <p className="text-xs text-cyan-200">A visible replacement was detected; only the surviving replacement should appear below.</p>
                            ) : null}
                            {visualRun.warnings.includes("uncertain_student_correction") || visualRun.draft_text?.includes("[unclear correction]") ? (
                              <p className="rounded border border-red-800 bg-red-950/30 p-2 text-xs text-red-100">
                                Unclear correction detected. Do not confirm unless the displayed marker faithfully represents what can be read from the image.
                              </p>
                            ) : null}
                            {visualRun.draft_text ? <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-3 text-xs text-slate-100">{visualRun.draft_text}</pre> : null}
                            {visualRun.status === "succeeded" && currentFinalIntentRun && thinkingRepairRun?.status !== "confirmed" ? <div className="flex flex-wrap gap-2">
                              {!baselineHasUnresolvedEvidence ? <button className={buttonClass} type="button" disabled={confirmingVisualRunId === visualRun.id} onClick={() => void handleConfirmVisualTranscription(mapping, visualRun)}>{requiresThinkingRepair ? "I verified this is the finalized surviving work" : "Confirm this final transcription"}</button> : null}
                              <button className="rounded border border-red-700 px-3 py-2 text-xs text-red-100" type="button" disabled={confirmingVisualRunId === visualRun.id} onClick={() => void handleRejectVisualTranscription(mapping, visualRun)}>None matches — block and upload clearer page</button>
                            </div> : null}
                            {visualRun.status === "succeeded" && currentFinalIntentRun && baselineHasUnresolvedEvidence ? (
                              <p className="text-xs text-amber-200">The baseline explicitly contains unresolved or crossed-writing markers, so it cannot be finalized directly. Use Thinking or upload a clearer complete page.</p>
                            ) : null}
                          </div>
                        ) : null}
                        {visualRun && repairableFinalIntentRun && ["succeeded", "confirmed", "rejected"].includes(visualRun.status) && !hasCurrentThinkingRepairRun && thinkingRepairRun?.status !== "confirmed" && mapping.answer_region_id && !gradedRegionIds.has(mapping.answer_region_id) && !finalizedRegionIds.has(mapping.answer_region_id) ? (
                          <button
                            className="rounded border border-violet-500 bg-violet-950/40 px-3 py-2 font-semibold text-violet-100 disabled:opacity-50"
                            type="button"
                            disabled={repairingOcrRegionId === mapping.answer_region_id || !localAiStatus?.qwen38.thinking_repair_enabled}
                            onClick={() => void handleRunThinkingRepair(mapping, visualRun)}
                          >
                            {repairingOcrRegionId === mapping.answer_region_id
                              ? "Qwen3.8 Thinking is adjudicating visible edits..."
                              : thinkingRepairRun?.status === "failed"
                                ? "Start corrected Thinking repair"
                                : requiresThinkingRepair
                                  ? "Finalize surviving work with Qwen3.8 Thinking"
                                  : "Check final intent with Qwen3.8 Thinking"}
                          </button>
                        ) : null}
                        {thinkingRepairRun ? (
                          <div className="grid gap-3 rounded border border-violet-600 bg-violet-950/20 p-3">
                            <div>
                              <p className="font-semibold text-violet-100">Finalized surviving-work candidate · run #{thinkingRepairRun.id}</p>
                              <p className="text-xs text-violet-200">{thinkingRepairRun.status} · {thinkingRepairRun.calls_used}/{thinkingRepairRun.call_limit} calls · no question, solution, rubric, or marks were provided</p>
                              <p className="mt-1 text-xs text-amber-200">Verify every numbered visual box. Only visible surviving work is retained; mathematical plausibility is never evidence.</p>
                              <p className="mt-1 text-xs text-slate-300">Unresolved edits or uncertain surviving glyphs fail closed and cannot reach grading.</p>
                            </div>
                            {thinkingRepairRun.error ? <p className="text-xs text-red-200">{thinkingRepairRun.error}</p> : null}
                            {thinkingRepairFailureCode ? <p className="text-xs text-red-300">Failure category: {thinkingRepairFailureCode.replaceAll("_", " ")}</p> : null}
                            {thinkingRepairRun.draft_text ? <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-3 text-xs text-slate-100">{thinkingRepairRun.draft_text}</pre> : null}
                            {repairDecisions.length > 0 ? (
                              <fieldset className="grid gap-2 rounded border border-slate-700 p-3">
                                <legend className="px-1 text-xs font-semibold text-slate-100">Required: confirm each image-grounded editing decision</legend>
                                {repairDecisions.map((decision) => {
                                  const reviewed = reviewedRepairDecisions[thinkingRepairRun.id] ?? [];
                                  const checked = reviewed.includes(decision.decisionIndex);
                                  const tone = decision.status === "cancelled" ? "text-red-200" : decision.status === "replacement" || decision.status === "retained" ? "text-emerald-200" : "text-amber-200";
                                  return (
                                    <label key={decision.decisionIndex} className="flex items-start gap-2 rounded border border-slate-800 p-2 text-xs">
                                      <input
                                        type="checkbox"
                                        checked={checked}
                                        disabled={thinkingRepairRun.status !== "succeeded"}
                                        onChange={(event) => setReviewedRepairDecisions((current) => {
                                          const existing = current[thinkingRepairRun.id] ?? [];
                                          const next = event.target.checked
                                            ? [...new Set([...existing, decision.decisionIndex])]
                                            : existing.filter((item) => item !== decision.decisionIndex);
                                          return { ...current, [thinkingRepairRun.id]: next };
                                        })}
                                      />
                                      <span><strong className={tone}>Decision {decision.decisionIndex + 1}: {decision.status.replace("_", " ")}</strong> · segment {decision.page_index} · {decision.position_hint}</span>
                                    </label>
                                  );
                                })}
                              </fieldset>
                            ) : null}
                            {thinkingRepairRun.status === "succeeded" && thinkingRepairRun.prompt_version === CURRENT_THINKING_REPAIR_PROMPT_VERSION ? (
                              <div className="flex flex-wrap gap-2">
                                <button
                                  className={buttonClass}
                                  type="button"
                                  disabled={confirmingVisualRunId === thinkingRepairRun.id || (reviewedRepairDecisions[thinkingRepairRun.id] ?? []).length !== repairDecisions.length}
                                  onClick={() => void handleConfirmThinkingRepair(mapping, thinkingRepairRun)}
                                >
                                  Confirm finalized surviving-work transcription
                                </button>
                                <button className="rounded border border-red-700 px-3 py-2 text-xs text-red-100" type="button" disabled={confirmingVisualRunId === thinkingRepairRun.id} onClick={() => void handleRejectThinkingRepair(mapping, thinkingRepairRun)}>Discard Thinking alternative</button>
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        {confirmedRun ? <div className="flex flex-wrap gap-2">
                          <button className={buttonClass} type="button" disabled={Boolean(mapping.answer_region?.full_answer_confirmed)} onClick={() => void handleEvidenceCorrection(() => confirmAnswerRegionFullAnswer(mapping.answer_region_id!, { full_answer_confirmed: true, packet_status: "complete" }))}>Confirm displayed image is the full answer</button>
                          {mapping.answer_region?.full_answer_confirmed ? hasDraftSuggestion ? (
                            <Link className={buttonClass} href={`/assessments/${assessmentId}/review`}>Draft ready — open review queue</Link>
                          ) : (
                            <button className={buttonClass} type="button" disabled={gradingRegionId === mapping.answer_region_id || !localSingleGradeAuthorized} onClick={() => void handleLocalQwenGrade(mapping.answer_region_id!)}>{gradingRegionId === mapping.answer_region_id ? "Qwen3.8 is grading..." : "Grade confirmed answer with Qwen3.8"}</button>
                          ) : null}
                        </div> : null}
                      </section>
                    ) : null}
                    {warnings.length > 0 ? (
                      <details className="rounded border border-amber-900/70 p-3 text-xs text-amber-100">
                        <summary>OCR and mapping notes ({warnings.length})</summary>
                        <ul className="mt-2 list-disc pl-5">
                          {warnings.map((warning) => <li key={warning}>{warning}</li>)}
                        </ul>
                      </details>
                    ) : null}
                  </article>
                );
              }),
            )}
          </div>
        )}
      </section>
      {process.env.NEXT_PUBLIC_SHOW_LEGACY_REFERENCE_TOOLS === "true" ? (
      <section className="grid gap-4 rounded border border-cyan-900 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Step 3A: Automatic answer-region mapping to confirmed question nodes</h2>
          <p className="mt-1 text-sm text-slate-400">
            Confirmed question/subquestion nodes: {confirmedQuestionSubquestionNodes.length} · expected mappings: {expectedMappingCount} · current mappings: {flatMappings.length} · teacher-confirmed: {teacherConfirmedMappingCount}
          </p>
          <p className="text-sm text-amber-200">
            Grading must stay blocked until every required mapping is present, non-uncertain, non-blocked, and teacher-confirmed.
          </p>
        </div>
        <div className="grid gap-3 rounded border border-slate-800 p-3 text-sm text-slate-300 md:grid-cols-4">
          <p>uncertain: {uncertainMappingCount}</p>
          <p>blocked: {blockedMappingCount}</p>
          <p>answer regions linked: {flatMappings.filter((mapping) => mapping.answer_region_id != null).length}</p>
          <p>workflow ready: {expectedMappingCount > 0 && teacherConfirmedMappingCount >= expectedMappingCount && uncertainMappingCount === 0 && blockedMappingCount === 0 ? "yes" : "no"}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button className={buttonClass} type="button" disabled={runningMappings || submissions.length === 0 || confirmedQuestionSubquestionNodes.length === 0} onClick={() => void handleRunAutomaticMappings()}>
            {runningMappings ? "Running mapping..." : "Run automatic mapping"}
          </button>
        </div>
        {questionNodeMappings.length === 0 ? <EmptyState message="No question-node mappings yet." /> : null}
        <div className="grid gap-3">
          {questionNodeMappings.map((group) => (
            <article key={group.question_node.id} className="rounded border border-slate-800 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="font-semibold">{group.question_node.label}</h3>
                  <p className="text-xs text-slate-500">{group.question_node.text || "No extracted text"}</p>
                </div>
                <span className="rounded-full border border-slate-700 px-2 py-0.5 text-xs text-slate-300">
                  {group.mappings.length} mapping(s)
                </span>
              </div>
              {group.mappings.length === 0 ? <p className="mt-3 text-sm text-amber-200">No mapping created yet for this confirmed node.</p> : null}
              <div className="mt-3 grid gap-3">
                {group.mappings.map((mapping) => (
                  <div key={mapping.id} className="rounded border border-slate-700 p-3 text-sm">
                    <p className="font-medium">Submission #{mapping.submission_id} · status {mapping.mapping_status}</p>
                    <p className="text-xs text-slate-400">page: {mapping.source_page ?? "n/a"} · confidence: {mapping.confidence ?? "n/a"} · provider: {mapping.provider}</p>
                    <p className="text-xs text-slate-400">answer_region_id: {mapping.answer_region_id ?? "none"} · teacher_confirmed: {mapping.teacher_confirmed ? "yes" : "no"}</p>
                    {mapping.blocker_reason ? <p className="mt-1 text-xs text-red-200">blocker: {mapping.blocker_reason}</p> : null}
                    {mapping.source_reference ? <pre className="mt-2 overflow-x-auto rounded bg-slate-950/40 p-2 text-[11px] text-slate-300">{JSON.stringify(mapping.source_reference, null, 2)}</pre> : null}
                    <div className="mt-3 grid gap-2 md:grid-cols-5">
                      <select className={inputClass} value={selectedMappingQuestionNodeId} onChange={(event) => setSelectedMappingQuestionNodeId(event.target.value)}>
                        <option value="">Question node</option>
                        {confirmedQuestionSubquestionNodes.map((node) => (
                          <option key={node.id} value={node.id}>{node.label}</option>
                        ))}
                      </select>
                      <select className={inputClass} value={mappingPageId} onChange={(event) => setMappingPageId(event.target.value)}>
                        <option value="">Page</option>
                        {submissions.flatMap((submission) => submission.pages.map((page) => (
                          <option key={page.id} value={page.id}>{formatPageLabel(submission, page)}</option>
                        )))}
                      </select>
                      <input className={inputClass} placeholder="x" value={mappingX} onChange={(event) => setMappingX(event.target.value)} />
                      <input className={inputClass} placeholder="y" value={mappingY} onChange={(event) => setMappingY(event.target.value)} />
                      <input className={inputClass} placeholder="width" value={mappingWidth} onChange={(event) => setMappingWidth(event.target.value)} />
                      <input className={inputClass} placeholder="height" value={mappingHeight} onChange={(event) => setMappingHeight(event.target.value)} />
                    </div>
                    <textarea className={`${inputClass} mt-2`} rows={2} placeholder="Manual answer text for corrected mapping" value={mappingManualAnswerText} onChange={(event) => setMappingManualAnswerText(event.target.value)} />
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button className="rounded border border-cyan-700 px-3 py-1 text-xs text-cyan-200 hover:border-cyan-500" type="button" disabled={savingMappingId === mapping.id} onClick={() => void handleSaveManualMapping(mapping)}>
                        {savingMappingId === mapping.id ? "Saving..." : "Save manual correction"}
                      </button>
                      <button className="rounded border border-emerald-700 px-3 py-1 text-xs text-emerald-200 hover:border-emerald-500" type="button" disabled={confirmingMappingId === mapping.id || mapping.answer_region_id == null} onClick={() => void handleConfirmMapping(mapping)}>
                        {confirmingMappingId === mapping.id ? "Confirming..." : "Confirm mapping"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>
      ) : null}

      <form onSubmit={handleCreateRegion} className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-5">
        <div>
          <h2 className="text-xl font-semibold">Review prepared answer evidence</h2>
          <p className="text-sm text-slate-400">Review the answer image and model-prepared evidence for each student × grading unit. Multi-page answers stay in reading order and require confirmation before grading.</p>
          <p className="text-sm text-amber-200">Teacher confirmation is required before local Qwen can create a draft score.</p>
          <p className="mt-1 text-sm text-slate-400">
            Total answer regions: {answerRegions.length} · mapped questions: {mappedQuestionCount}/{questions.length} · unmapped questions: {unmappedQuestionCount} · mapped submissions: {mappedSubmissionCount}/{submissions.length}
          </p>
        </div>
        <div className="grid gap-3 rounded border border-slate-800 p-3 text-sm text-slate-300 md:grid-cols-2">
          <p>Question status: {questions.length === 0 ? "no questions" : `${mappedQuestionCount} mapped, ${unmappedQuestionCount} unmapped`}</p>
          <p>Submission/page status: {mappedSubmissionCount} submissions mapped · {unmappedSubmissionCount} unmapped submissions</p>
        </div>
        <div className="hidden flex-wrap items-center gap-3">
          <label className="grid gap-1 text-sm">
            Suggestion provider
            <select className={inputClass} value={regionSuggestionProvider} disabled>
              <option value="mock">Mock/deterministic mapping provider</option>
            </select>
          </label>
          <button className={buttonClass} disabled={suggestingRegions || !selectedPage} type="button" onClick={() => void handleSuggestAnswerRegions()}>
            {suggestingRegions ? "Suggesting..." : "Suggest answer mappings"}
          </button>
          <p className="text-sm text-amber-200">Mapping suggestions are drafts until accepted. Teacher/founder must confirm full answer evidence before grading.</p>
        </div>
        <p className="hidden text-xs text-slate-400">Mock deterministic mapping suggestions are draft-only. Real AI mapping is not implemented here.</p>
        {suggestionPageId === selectedPage?.page.id && regionSuggestionWarnings.length > 0 ? (
          <div className="rounded border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-100">
            <p className="font-semibold">Provider warnings</p>
            <ul className="list-disc pl-5">
              {regionSuggestionWarnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {suggestionPageId === selectedPage?.page.id && regionSuggestionMessage ? (
          <p className="rounded border border-slate-700 bg-slate-950/30 p-3 text-sm text-slate-300">{regionSuggestionMessage}</p>
        ) : null}
        {suggestionPageId === selectedPage?.page.id && regionSuggestions.length > 0 ? (
          <div className="grid gap-2 rounded border border-slate-800 p-3 text-sm text-slate-300 md:grid-cols-2">
            {regionSuggestions.map((suggestion) => {
              const primarySegment = suggestion.segments.find((segment) => segment.is_primary) ?? suggestion.segments[0];
              const pagesCovered = Array.from(new Set(suggestion.segments.map((segment) => segment.page_id)));
              return (
              <article key={suggestion.draft_id} className="rounded border border-slate-700 p-3">
                <p className="font-medium">
                  Question {suggestion.suggested_question_no} · Segment count {suggestion.segments.length}
                </p>
                <p className="text-xs text-slate-500">Pages covered {pagesCovered.join(", ")}</p>
                <p className="text-xs text-slate-500">Continuation risk: {suggestion.continuation_risk}</p>
                <p className="text-xs text-slate-500">
                  Primary segment: page {primarySegment.page_id}, x {primarySegment.x}, y {primarySegment.y}, w {primarySegment.width}, h {primarySegment.height}
                </p>
                <p className="text-xs text-slate-500">
                  Confidence {suggestion.confidence} · {suggestion.provider} · needs review
                </p>
                <ul className="mt-1 list-disc pl-4 text-xs text-slate-400">
                  {suggestion.segments.map((segment) => (
                    <li key={`${suggestion.draft_id}-${segment.order_index}`}>
                      Segment {segment.order_index}: page {segment.page_id}, continuation {segment.continuation_risk}
                    </li>
                  ))}
                </ul>
                {suggestion.warnings.length > 0 ? (
                  <ul className="mt-1 list-disc pl-4 text-xs text-amber-200">
                    {suggestion.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    className="rounded border border-cyan-700 px-3 py-1 text-xs text-cyan-200 hover:border-cyan-500"
                    type="button"
                    onClick={() => {
                      setRegionX(String(primarySegment.x));
                      setRegionY(String(primarySegment.y));
                      setRegionWidth(String(primarySegment.width));
                      setRegionHeight(String(primarySegment.height));
                      setSelectedQuestionId(String(suggestion.suggested_question_id));
                    }}
                  >
                    Use suggestion values
                  </button>
                  <button
                    className="rounded border border-emerald-700 px-3 py-1 text-xs text-emerald-200 hover:border-emerald-500"
                    type="button"
                    disabled={acceptingSuggestionId === suggestion.draft_id}
                    onClick={() => void handleAcceptRegionSuggestion(suggestion)}
                  >
                    {acceptingSuggestionId === suggestion.draft_id ? "Accepting..." : "Accept suggestion"}
                  </button>
                  <button
                    className="rounded border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:border-slate-400"
                    type="button"
                    onClick={() =>
                      setRegionSuggestions((current) => current.filter((item) => item.draft_id !== suggestion.draft_id))
                    }
                  >
                    Ignore suggestion
                  </button>
                </div>
              </article>
              );
            })}
          </div>
        ) : null}
        {suggestionPageId === selectedPage?.page.id && regionSuggestions.length === 0 && regionSuggestionMessage ? (
          <p className="text-sm text-slate-400">No draft suggestions to apply yet.</p>
        ) : null}
        {selectedPage && selectedQuestion ? (
          <p className="rounded border border-emerald-900 bg-emerald-950/20 p-3 text-sm text-emerald-200">
            Currently mapping {formatPageLabel(selectedPage.submission, selectedPage.page)} to grading unit {formatQuestionOption(selectedQuestion)} ({statusForQuestion(selectedQuestion.id)}).
          </p>
        ) : null}
        {!loading && questions.length === 0 ? (
          <p className="text-sm text-amber-200">Create a question before mapping answer regions.</p>
        ) : null}
        <label className="hidden gap-2 text-sm">
          Select page
          <select data-testid="answer-region-page-select" className={inputClass} value={selectedPageId} onChange={(event) => setSelectedPageId(event.target.value)} required>
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
        <label className="hidden gap-2 text-sm">
          Select question
          <select data-testid="answer-region-question-select" className={inputClass} value={selectedQuestionId} onChange={(event) => setSelectedQuestionId(event.target.value)} required>
            <option value="">Select question</option>
            {questions.map((question) => (
              <option key={question.id} value={question.id}>{formatQuestionOption(question)} · {statusForQuestion(question.id)}</option>
            ))}
          </select>
        </label>
        <div className="hidden">
          <p className="text-sm font-medium">Crop coordinates</p>
          <div className="mt-2 grid gap-2 md:grid-cols-4">
            <input className={inputClass} aria-label="Crop x" placeholder="x" value={regionX} onChange={(event) => setRegionX(event.target.value)} required />
            <input className={inputClass} aria-label="Crop y" placeholder="y" value={regionY} onChange={(event) => setRegionY(event.target.value)} required />
            <input className={inputClass} aria-label="Crop width" placeholder="width" value={regionWidth} onChange={(event) => setRegionWidth(event.target.value)} required />
            <input className={inputClass} aria-label="Crop height" placeholder="height" value={regionHeight} onChange={(event) => setRegionHeight(event.target.value)} required />
          </div>
          <textarea className={inputClass} aria-label="Manual answer evidence text" placeholder="Teacher-confirmed student answer text for real grading" value={manualAnswerText} onChange={(event) => setManualAnswerText(event.target.value)} rows={3} />
        </div>
        <button className={`hidden ${buttonClass}`} disabled={creatingRegion || pages.length === 0 || questions.length === 0} type="submit">
          {creatingRegion ? "Creating..." : "Create answer region"}
        </button>

        {!loading && answerRegions.length === 0 ? <EmptyState message="No answer regions yet." /> : null}
        {answerRegions.length > 0 ? (
          <label className="grid gap-2 text-sm">
            Selected answer region for Evidence Packet Preview
            <select className={inputClass} value={selectedPreviewRegion?.id ? String(selectedPreviewRegion.id) : ""} onChange={(event) => setSelectedPreviewRegionId(event.target.value)}>
              {answerRegions.map((region) => {
                const linkedQuestion = questions.find((question) => question.id === region.question_id) ?? null;
                return (
                  <option key={region.id} value={region.id}>
                    Answer region #{region.id} · {linkedQuestion ? formatQuestionOption(linkedQuestion) : `Question ${region.question_id}`} · submission #{region.submission_id}
                  </option>
                );
              })}
            </select>
          </label>
        ) : null}
        <div className="grid gap-2">
          {answerRegions.filter((region) => selectedPreviewRegion?.id === region.id).map((region) => {
            const linkedSubmission = submissions.find((submission) => submission.id === region.submission_id) ?? null;
            const linkedPage = linkedSubmission?.pages.find((page) => page.id === region.page_id) ?? null;
            const linkedQuestion = questions.find((question) => question.id === region.question_id) ?? null;
            const regionStatus = statusForRegion(region.id);
            const packet = evidencePackets[region.id] ?? null;
            const packetAnswer = packet?.student_answer_evidence;
            const readiness = packet?.readiness_result;
            const segmentOrder = packetAnswer?.segments
              .map((segment) => `segment ${String(segment.order_index ?? "?")}: page ${String(segment.page_id ?? "?")}`)
              .join("; ");
            const questionText = packet?.question_evidence.question_text ?? linkedQuestion?.question_text ?? "Not available yet";
            const modelAnswer =
              packet?.solution_model_answer_evidence.solution_model_answer_text_or_reference ??
              linkedQuestion?.model_answer ??
              "Not available yet";
            const modelAnswerMissing = modelAnswer === "Not available yet";
            const manualAnswerText = packetAnswer?.manual_answer_text?.trim() ?? region.manual_answer_text?.trim() ?? "";
            const manualAnswerMissing = manualAnswerText.length === 0;
            const readyForRealDraftGrading = Boolean(readiness?.ready_for_grading) && !manualAnswerMissing;
            const preparedMapping = flatMappings.find(
              (mapping) => mapping.answer_region_id === region.id && isLocalPreparedMapping(mapping),
            ) ?? null;
            const mappingGeometryConfirmed = !preparedMapping || preparedMapping.teacher_confirmed;
            const fullAnswerConfirmationReady = mappingGeometryConfirmed && !manualAnswerMissing;
            return (
              <article id={`answer-region-${region.id}`} key={region.id} data-testid="answer-region-card" className="grid gap-3 rounded border border-slate-700 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span>Answer region #{region.id}</span>
                  <span className="rounded-full border border-slate-600 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-300">
                    {regionStatus}
                  </span>
                </div>
                <p className="text-xs text-slate-500">
                  {linkedQuestion ? formatQuestionOption(linkedQuestion) : `Question ${region.question_id}`} · Submission #{linkedSubmission?.id ?? region.submission_id} · page {linkedPage?.page_no ?? region.page_id}
                </p>
                <section className="grid gap-3 rounded border border-cyan-700 bg-cyan-950/10 p-3">
                  <div>
                    <p className="font-semibold text-cyan-100">
                      Complete answer images · {region.segments.length} segment{region.segments.length === 1 ? "" : "s"}
                    </p>
                    <p className="text-xs text-cyan-200">These ordered images—not only the first crop—form the evidence packet.</p>
                  </div>
                  {region.segments.length > 0 ? region.segments.map((segment) => (
                    <AuthenticatedAnswerRegionSegmentImage
                      key={segment.id}
                      answerRegionId={region.id}
                      segmentId={segment.id}
                      orderIndex={segment.order_index}
                      alt={`Prepared answer segment ${segment.order_index} for answer region ${region.id}`}
                    />
                  )) : (
                    <AuthenticatedAnswerRegionImage
                      answerRegionId={region.id}
                      alt={`Prepared answer region ${region.id}`}
                    />
                  )}
                </section>

                <section className="grid gap-3 rounded border border-cyan-900 bg-slate-950/40 p-3" data-testid="evidence-packet-preview">
                  <div>
                    <h3 className="font-semibold text-cyan-200">Evidence Packet Preview</h3>
                    <p className="text-xs text-amber-200">This preview shows the evidence that would be sent for grading later. It does not grade.</p>
                  </div>
                  <div className="grid gap-2 text-xs text-slate-300 md:grid-cols-2">
                    <p>question label: {packet?.canonical_grading_unit.label ?? linkedQuestion?.question_no ?? "Not available yet"}</p>
                    <p>max marks: {packet?.canonical_grading_unit.max_marks ?? linkedQuestion?.total_marks ?? "Not available yet"}</p>
                    <p>question text: {questionText}</p>
                    <p>solution/model answer: {modelAnswer}</p>
                    <p>active rubric: {packet ? String(packet.canonical_grading_unit.active_rubric_present) : "Not available yet"}</p>
                    <p>criteria: {packet?.rubric_evidence.criteria_max_marks.length ? JSON.stringify(packet.rubric_evidence.criteria_max_marks) : "Not available yet"}</p>
                    <p>student answer region id: {packet?.assessment_context.answer_region_id ?? region.id}</p>
                    <p>segment count: {packetAnswer?.segment_count ?? region.segments.length ?? "Not available yet"}</p>
                    <p>packet pages covered: {packetAnswer?.pages_covered.join(", ") || (linkedPage?.page_no ? String(linkedPage.page_no) : "Not available yet")}</p>
                    <p>segment order: {segmentOrder || "Not available yet"}</p>
                    <p>prepared answer image: {packetAnswer?.crop_path ? "available" : "Not available yet"}</p>
                    <p>Teacher-approved prepared answer evidence: {manualAnswerMissing ? "not approved" : "approved"}</p>
                    <p>evidence_status: {packetAnswer?.packet_status ?? "Not available yet"}</p>
                    <p>continuation_check_status: {packetAnswer?.continuation_check_status ?? "Not available yet"}</p>
                    <p>ready_for_grading: {readiness ? String(readiness.ready_for_grading) : "Not available yet"}</p>
                    <p>blockers: {readiness?.blockers.length ? readiness.blockers.join("; ") : "Not available yet"}</p>
                    <p>warnings: {readiness?.warnings.length ? readiness.warnings.join("; ") : "Not available yet"}</p>
                  </div>
                  <div className={`rounded border p-3 text-sm ${manualAnswerMissing ? "border-red-700 bg-red-950/40 text-red-100" : "border-emerald-800 bg-emerald-950/30 text-emerald-100"}`}>
                    <p className="font-semibold">Approved student answer evidence</p>
                    {manualAnswerMissing ? (
                      <p>Approve the model-prepared mapping and answer evidence above. You do not need to type or rewrite the student answer.</p>
                    ) : (
                      <p className="whitespace-pre-wrap">{manualAnswerText}</p>
                    )}
                  </div>
                  {modelAnswerMissing ? (
                    <p className="rounded border border-amber-800 bg-amber-950/30 p-2 text-xs text-amber-100">
                      Blocker: solution/model answer is missing. Add a model answer in Step 2 manual question creation or import/accept reference material question data before expecting a ready packet.
                    </p>
                  ) : null}
                  {readyForRealDraftGrading ? (
                    <p className="rounded border border-emerald-800 bg-emerald-950/30 p-2 text-xs font-semibold text-emerald-100">
                      Ready for real draft grading: evidence packet prerequisites pass. Run only one explicitly approved single-packet real grading call.
                    </p>
                  ) : (
                    <p className="rounded border border-red-800 bg-red-950/30 p-2 text-xs font-semibold text-red-100">
                      Not ready for real draft grading. Approve the prepared answer evidence, then confirm that the displayed image contains the full answer.
                    </p>
                  )}
                  {!mappingGeometryConfirmed ? (
                    <p className="rounded border border-amber-800 bg-amber-950/30 p-2 text-xs text-amber-100">
                      Confirm every displayed mapping segment above before confirming full-answer coverage.
                    </p>
                  ) : manualAnswerMissing ? (
                    <p className="rounded border border-amber-800 bg-amber-950/30 p-2 text-xs text-amber-100">
                      Confirm a faithful Qwen3.8 visual transcription before confirming full-answer coverage.
                    </p>
                  ) : null}
                  <div className="flex flex-wrap gap-2">
                    <button className={buttonClass} type="button" disabled={!fullAnswerConfirmationReady} onClick={() => void handleEvidenceCorrection(() => confirmAnswerRegionFullAnswer(region.id, { full_answer_confirmed: true, packet_status: "complete" }))}>Confirm all displayed segments are the full answer</button>
                    <button className={buttonClass} type="button" disabled={!mappingGeometryConfirmed} onClick={() => void handleEvidenceCorrection(() => confirmAnswerRegionFullAnswer(region.id, { full_answer_confirmed: false, continuation_not_needed: true, packet_status: "unconfirmed" }))}>Mark continuation not needed</button>
                    <button className={buttonClass} type="button" disabled={!mappingGeometryConfirmed} onClick={() => void handleEvidenceCorrection(() => confirmAnswerRegionFullAnswer(region.id, { full_answer_confirmed: false, packet_status: "partial" }))}>Reject / needs correction</button>
                    <button className={buttonClass} type="button" disabled={!mappingGeometryConfirmed} onClick={() => void handleEvidenceCorrection(() => confirmAnswerRegionFullAnswer(region.id, { full_answer_confirmed: false, packet_status: "blank" }))}>Mark blank</button>
                  </div>
                  <div className="rounded border border-cyan-800 bg-cyan-950/20 p-3">
                    <p className="font-semibold text-cyan-100">Local Qwen3.8 draft grading</p>
                    <p className="mt-1 text-xs text-slate-300">
                      Qwen3.8 receives the finalized question, solution, active rubric, and only the teacher-confirmed answer text in a fresh text-only context. It creates a review-required draft and cannot finalize a grade.
                    </p>
                    <button
                      className={`mt-3 ${buttonClass}`}
                      type="button"
                      disabled={!readyForRealDraftGrading || !localSingleGradeAuthorized || !activeGradingRun || gradingRegionId === region.id || gradedRegionIds.has(region.id) || finalizedRegionIds.has(region.id)}
                      onClick={() => void handleLocalQwenGrade(region.id)}
                    >
                      {gradingRegionId === region.id
                        ? "Starting Qwen3.8 and grading..."
                        : gradedRegionIds.has(region.id) || finalizedRegionIds.has(region.id)
                          ? "Draft already created"
                          : "Grade confirmed answer with local Qwen3.8"}
                    </button>
                    {!localSingleGradeAuthorized ? (
                      <p className="mt-2 text-xs text-red-200">Local Qwen3.8 single-answer grading is disabled in the host configuration.</p>
                    ) : null}
                  </div>
                </section>
              </article>
            );
          })}
        </div>
      </form>

      {answerRegions.length > 0 ? <>
      <details className="rounded border border-slate-800 bg-slate-900 p-5">
        <summary className="cursor-pointer font-semibold text-slate-200">Advanced: batch readiness and queue diagnostics</summary>
        <p className="mt-2 text-sm text-slate-400">These diagnostics are optional for single-answer supervised local Qwen grading.</p>
        <div className="mt-4 grid gap-4">
      <section className="rounded border border-slate-800 bg-slate-900 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">Step 5: Evidence readiness</h2>
            <p className="text-sm text-amber-200">This prepares evidence only. It does not grade.</p>
            <p className="text-sm text-slate-400">Expected packets = submissions × grading units.</p>
            <p className="text-sm text-slate-400">Missing packets are blocked, not skipped.</p>
          </div>
          <button className={buttonClass} type="button" disabled={creatingEvidencePrepRun} onClick={() => void handleCreateEvidencePrepRun()}>
            {creatingEvidencePrepRun ? "Preparing evidence..." : "Create evidence prep run"}
          </button>
        </div>
        {evidencePrepSummary ? (
          <div className="mt-4 grid gap-4">
            <div className="grid gap-2 rounded border border-slate-800 p-3 text-sm md:grid-cols-6">
              <p>ready: {evidencePrepSummary.ready_packet_count}</p>
              <p>blocked: {evidencePrepSummary.blocked_packet_count}</p>
              <p>warnings: {evidencePrepSummary.warning_packet_count}</p>
              <p>partial: {evidencePrepSummary.partial_packet_count}</p>
              <p>blank: {evidencePrepSummary.blank_packet_count}</p>
              <p>status: {evidencePrepSummary.status}</p>
            </div>
            <div className="rounded border border-slate-800 p-3 text-sm">
              <p className="font-semibold">Blocked / quarantined items</p>
              {evidencePrepSummary.packets.filter((packet) => packet.quarantined).length === 0 ? (
                <p className="mt-2 text-slate-400">No quarantined packets in the current summary.</p>
              ) : (
                <div className="mt-2 grid gap-2">
                  {evidencePrepSummary.packets.filter((packet) => packet.quarantined).slice(0, 10).map((packet) => (
                    <article key={`${packet.submission_id}-${packet.question_id ?? "missing"}-${packet.answer_region_id ?? "none"}`} className="rounded border border-amber-900/70 p-3">
                      <p className="font-medium">
                        Submission #{packet.submission_id} · {packet.student_identifier ?? "unknown student"} · {packet.grading_unit_label ?? "unknown grading unit"}
                      </p>
                      <p className="text-slate-400">
                        evidence_status {packet.evidence_status} · continuation {packet.continuation_check_status} · segments {packet.segment_count}
                      </p>
                      <p className="text-xs text-slate-500">Packet pages covered: {packet.pages_covered.length > 0 ? packet.pages_covered.join(", ") : "none yet"}</p>
                      <p className="text-amber-200">Reason: {packet.blockers.join("; ") || "blocked by policy"}</p>
                      {packet.answer_region_id ? (
                        <a className="text-cyan-300 underline" href={`#answer-region-${packet.answer_region_id}`}>Go to correction area</a>
                      ) : (
                        <p className="text-cyan-300">Correction target: create/map evidence for submission #{packet.correction_target.submission_id ?? packet.submission_id} and grading unit {packet.correction_target.grading_unit_label ?? packet.grading_unit_label ?? "unknown"} in the answer-region form below.</p>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <p className="mt-3 text-sm text-slate-400">Evidence preparation summary has not loaded yet.</p>
        )}
        <p className="mt-3 text-xs text-slate-500">No batch grade button is available here. Real AI/OCR and Codex are not invoked by evidence preparation.</p>
      </section>

      <section id="grading-queue" className="rounded border border-slate-800 bg-slate-900 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">Step 6: Queue scaffold</h2>
            <p className="text-sm text-amber-200">This only prepares a queue from confirmed evidence. It does not grade.</p>
            <p className="text-sm text-slate-400">Only confirmed complete evidence packets can enter the queue.</p>
            <p className="text-sm text-slate-400">Queue records are not grades. Provider execution is disabled. No batch grade button is available.</p>
          </div>
          <button className={buttonClass} type="button" disabled={creatingGradingQueueRun} onClick={() => void handleCreateGradingQueueRun()}>
            {creatingGradingQueueRun ? "Preparing queue..." : "Create grading queue scaffold"}
          </button>
        </div>
        {gradingQueueSummary ? (
          <div className="mt-4 grid gap-4">
            <div className="grid gap-2 rounded border border-slate-800 p-3 text-sm md:grid-cols-4">
              <p>status: {gradingQueueSummary.status}</p>
              <p>candidates: {gradingQueueSummary.total_candidate_packets}</p>
              <p>queued item count: {gradingQueueSummary.queued_item_count}</p>
              <p>refused item count: {gradingQueueSummary.refused_item_count}</p>
            </div>
            <div className="rounded border border-emerald-900/70 p-3 text-sm">
              <p className="font-semibold">Queued confirmed packets</p>
              {gradingQueueSummary.items.length === 0 ? (
                <p className="mt-2 text-slate-400">No confirmed packets are queued yet.</p>
              ) : (
                <div className="mt-2 grid gap-2">
                  {gradingQueueSummary.items.slice(0, 10).map((item) => (
                    <article key={item.id} className="rounded border border-emerald-900/70 p-3">
                      <p className="font-medium">
                        Submission #{item.submission_id} · {item.student_identifier ?? "unknown student"} · {item.grading_unit_label}
                      </p>
                      <p className="text-slate-400">
                        queue_status {item.queue_status} · stale_status {item.stale_status} · provider_allowed {String(item.provider_allowed)} · segments {item.segment_count}
                      </p>
                      {item.current_refusal_reasons.length > 0 ? <p className="text-amber-200">Current blockers: {item.current_refusal_reasons.join("; ")}</p> : null}
                      <p className="text-xs text-slate-500">Packet pages covered: {item.pages_covered.length > 0 ? item.pages_covered.join(", ") : "none"}</p>
                    </article>
                  ))}
                </div>
              )}
            </div>
            <div className="rounded border border-amber-900/70 p-3 text-sm">
              <p className="font-semibold">Refused packet reasons</p>
              {gradingQueueSummary.refused_items.length === 0 ? (
                <p className="mt-2 text-slate-400">No refused packets in the current queue summary.</p>
              ) : (
                <div className="mt-2 grid gap-2">
                  {gradingQueueSummary.refused_items.slice(0, 10).map((item) => (
                    <article key={`${item.submission_id}-${item.grading_unit_id ?? "missing"}-${item.answer_region_id ?? "none"}`} className="rounded border border-amber-900/70 p-3">
                      <p className="font-medium">
                        Submission #{item.submission_id} · {item.student_identifier ?? "unknown student"} · {item.grading_unit_label ?? "unknown grading unit"}
                      </p>
                      <p className="text-slate-400">
                        evidence_status {item.evidence_status} · continuation {item.continuation_check_status} · segments {item.segment_count}
                      </p>
                      <p className="text-xs text-slate-500">Packet pages covered: {item.pages_covered.length > 0 ? item.pages_covered.join(", ") : "none"}</p>
                      <p className="text-amber-200">Reason: {item.refusal_reasons.join("; ") || "refused by queue contract"}</p>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <p className="mt-3 text-sm text-slate-400">Grading queue scaffold summary has not loaded yet.</p>
        )}
        <p className="mt-3 text-xs text-slate-500">Queue records are not grades. Stale queue items must be rebuilt before provider execution.</p>
        <p className="mt-3 text-xs text-slate-500">No provider run button, no batch grade button, and no FinalGrade action are available in this scaffold.</p>
      </section>
        </div>
      </details>

      <section className="grid gap-3 rounded-2xl border border-slate-800 bg-slate-900 p-5 md:grid-cols-[1fr_auto] md:items-center">
        <div>
          <h2 className="text-lg font-semibold">Teacher review stays separate</h2>
          <p className="mt-1 text-sm text-slate-400">Only teacher-approved draft suggestions can become final grades or appear in export.</p>
        </div>
        {reviewQueue.some((item) => item.latest_grade_suggestion) ? (
          <Link className={buttonClass} href={`/assessments/${assessmentId}/review`}>Open review queue</Link>
        ) : (
          <span className="text-sm text-slate-500">No grading drafts yet</span>
        )}
      </section>
      </> : null}
      </> : null}
      </> : null}

    </div>
  );
}

function gradingUnitType(questionNo: string): string {
  const parentheticalCount = (questionNo.match(/\(/g) ?? []).length;
  return parentheticalCount >= 2 ? "subpart grading unit" : "whole sub-question grading unit";
}

function formatQuestionOption(question: Question): string {
  return `${question.question_no} — ${question.total_marks} marks`;
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
