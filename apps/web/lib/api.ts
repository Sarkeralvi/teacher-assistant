export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export type User = {
  id: number;
  name: string;
  email: string;
  role: string;
  created_at: string;
  updated_at: string;
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer" | string;
  user: User;
};

export const AUTH_TOKEN_STORAGE_KEY = "teacherAssistantAuthToken";

export function getStoredAuthToken() {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
}

export function setStoredAuthToken(token: string) {
  window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
}

export function clearStoredAuthToken() {
  window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
}

export type Course = {
  id: number;
  teacher_id: number;
  code: string;
  title: string;
  department: string | null;
  semester: string | null;
  created_at: string;
  updated_at: string;
};

export type Assessment = {
  id: number;
  course_id: number;
  title: string;
  assessment_type: string;
  total_marks: string | number;
  status: string;
  created_at: string;
  updated_at: string;
};

export type Question = {
  id: number;
  assessment_id: number;
  question_no: string;
  question_text: string;
  model_answer: string | null;
  total_marks: string | number;
  created_at: string;
  updated_at: string;
};

export type DraftQuestion = {
  draft_id: string;
  question_no: string;
  question_text: string;
  model_answer: string | null;
  total_marks: string | number | null;
  confidence: string | number;
  source_page: number;
  source_text_excerpt: string;
  needs_review: boolean;
};

export type QuestionImportProvider = "mock" | "codex_cli_question_extractor";

export type QuestionImportJob = {
  id: number;
  assessment_id: number;
  status: string;
  original_filename: string;
  content_type: string;
  file_path: string;
  provider: string;
  draft_questions: DraftQuestion[];
  provider_warnings: string[];
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type QuestionImportAcceptResponse = {
  job_id: number;
  created_count: number;
  questions: Question[];
};

export type SubmissionZipUploadResponse = {
  assessment_id: number;
  requested_file_count: number;
  imported_count: number;
  skipped_count: number;
  failed_count: number;
  submissions_created: Submission[];
  errors: string[];
  warnings: string[];
};

export type MarkingPolicy = "tough" | "general" | "easy";

export type GradingRunWorkflowState = {
  materials_uploaded: boolean;
  materials_confirmed: boolean;
  questions_confirmed: boolean;
  rubrics_confirmed: boolean;
  scripts_uploaded: boolean;
  answer_regions_created: boolean;
  grading_ready: boolean;
  suggestions_created: boolean;
  review_ready: boolean;
  final_grades_created: boolean;
  export_ready: boolean;
  question_count: number;
  rubric_count: number;
  submission_count: number;
  submission_page_count: number;
  answer_region_count: number;
  mapped_question_count: number;
  mapped_page_count: number;
  mapped_submission_count: number;
  unmapped_question_count: number;
  unmapped_page_count: number;
  unmapped_submission_count: number;
  grade_suggestion_count: number;
  final_grade_count: number;
  blockers: string[];
  next_actions: string[];
  derived_status: string;
};

export type GradingRun = {
  id: number;
  assessment_id: number;
  created_by_teacher_id: number;
  mode: "custom_controlled" | string;
  status: string;
  marking_policy: MarkingPolicy;
  question_pdf_path: string | null;
  solution_pdf_path: string | null;
  rubric_pdf_path: string | null;
  materials_confirmed_at: string | null;
  questions_confirmed_at: string | null;
  rubrics_confirmed_at: string | null;
  notes: string | null;
  workflow_state: GradingRunWorkflowState;
  created_at: string;
  updated_at: string;
};

export type GradingRunCreate = {
  notes?: string | null;
  marking_policy?: MarkingPolicy;
};

export type GradingRunUpdate = {
  status?: string;
  notes?: string | null;
  marking_policy?: MarkingPolicy;
};

export type Rubric = {
  id: number;
  question_id: number;
  version: number;
  rubric_json: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type SubmissionPage = {
  id: number;
  submission_id: number;
  page_no: number;
  image_path: string;
  quality_score: string | number | null;
  created_at: string;
  updated_at: string;
};

export type Submission = {
  id: number;
  assessment_id: number;
  student_identifier: string;
  student_name: string | null;
  status: string;
  pages: SubmissionPage[];
  created_at: string;
  updated_at: string;
};

export type AnswerRegion = {
  id: number;
  submission_id: number;
  question_id: number;
  page_id: number;
  x: string | number;
  y: string | number;
  width: string | number;
  height: string | number;
  image_path: string;
  created_at: string;
  updated_at: string;
};

export type DraftAnswerRegionSuggestion = {
  draft_id: string;
  x: string | number;
  y: string | number;
  width: string | number;
  height: string | number;
  confidence: string | number;
  reason: string;
  source: string;
  needs_teacher_confirmation: boolean;
};

export type AnswerRegionSuggestionResponse = {
  page_id: number;
  source: string;
  message: string;
  suggestions: DraftAnswerRegionSuggestion[];
};

export type GradingJob = {
  id: number;
  answer_region_id: number;
  status: string;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

export type GradeSuggestion = {
  id: number;
  grading_job_id: number;
  answer_region_id: number;
  question_id: number;
  model_provider: string;
  model_name: string;
  prompt_version: string;
  marking_policy: MarkingPolicy;
  raw_response_json: {
    rubric_breakdown?: Array<{
      criterion_id: string;
      criterion: string;
      max_marks: string | number;
      awarded_marks: string | number;
      reason: string;
      evidence: string | null;
      confidence: string | number;
    }>;
    review_flags?: string[];
    [key: string]: unknown;
  };
  score: string | number | null;
  max_score: string | number;
  confidence: string | number | null;
  needs_review: boolean;
  feedback: string | null;
  cost_estimate: string | number | null;
  created_at: string;
};

export type FinalGrade = {
  id: number;
  answer_region_id: number;
  teacher_id: number;
  suggestion_id: number | null;
  final_score: string | number;
  teacher_comment: string | null;
  approval_status: "approved" | "edited" | "rejected" | string;
  created_at: string;
  updated_at: string;
};

export type BatchMockGradeResponse = {
  assessment_id: number;
  total_answer_regions: number;
  graded_count: number;
  skipped_count: number;
  failed_count: number;
  created_grade_suggestion_ids: number[];
  errors: string[];
};

export type BrowserCodexGradeResponse = {
  job: {
    id: number;
    answer_region_id: number;
    status: string;
    error: string | null;
    created_at: string;
    completed_at: string | null;
  };
  suggestion: Omit<GradeSuggestion, "raw_response_json"> & { review_flags: string[] };
};

export type BatchApproveFinalGradesResponse = {
  requested_count: number;
  approved_count: number;
  skipped_count: number;
  failed_count: number;
  final_grade_ids: number[];
  errors: string[];
};

export type ReviewQueueItem = {
  answer_region: AnswerRegion;
  submission: { id: number; student_identifier: string; student_name: string | null };
  question: { id: number; question_no: string; question_text: string; total_marks: string | number };
  latest_grade_suggestion: GradeSuggestion | null;
  final_grade: FinalGrade | null;
  review_status: "ungraded" | "suggested" | "finalized";
};

export type AssessmentSummary = {
  assessment_id: number;
  course_id: number;
  total_submissions: number;
  total_answer_regions: number;
  total_grade_suggestions: number;
  total_final_grades: number;
  approved_count: number;
  edited_count: number;
  rejected_count: number;
  pending_review_count: number;
  average_final_score: string | number | null;
  max_possible_score: string | number | null;
  generated_at: string;
};

type RequestOptions = {
  method?: string;
  body?: unknown;
  formData?: FormData;
  token?: string | null;
  authErrorMessage?: string;
};

export const UPLOAD_AUTH_ERROR_MESSAGE = "Please log in again before uploading materials.";

export function backendUnreachableMessage() {
  return `Could not reach backend at ${API_BASE_URL}. Check backend server.`;
}

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const hasJsonBody = options.body !== undefined;
  const headers: Record<string, string> = {};
  if (hasJsonBody) {
    headers["Content-Type"] = "application/json";
  }
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers: Object.keys(headers).length > 0 ? headers : undefined,
      body: hasJsonBody ? JSON.stringify(options.body) : options.formData,
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(backendUnreachableMessage());
    }
    throw error;
  }

  if (!response.ok) {
    if (response.status === 401 && options.authErrorMessage) {
      throw new Error(options.authErrorMessage);
    }
    let detail = `${response.status} ${response.statusText}`;
    try {
      const errorBody = (await response.json()) as { detail?: unknown };
      if (typeof errorBody.detail === "string") {
        detail = errorBody.detail;
      }
    } catch {
      // Keep default status text.
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type UserCreate = Pick<User, "name" | "email"> & { role?: string };
export type AuthRegister = UserCreate & { password: string };
export type AuthLogin = Pick<User, "email"> & { password: string };
export type CourseCreate = Pick<Course, "teacher_id" | "code" | "title"> &
  Partial<Pick<Course, "department" | "semester">>;
export type CourseUpdate = Partial<CourseCreate>;
export type AssessmentCreate = Pick<Assessment, "title" | "assessment_type" | "total_marks"> & {
  status?: string;
};
export type QuestionCreate = Pick<Question, "question_no" | "question_text" | "total_marks"> & {
  model_answer?: string | null;
};
export type DraftQuestionAccept = Pick<DraftQuestion, "draft_id" | "question_no" | "question_text"> & {
  model_answer?: string | null;
  total_marks: string | number;
};
export type RubricCreate = Pick<Rubric, "version" | "rubric_json"> & { is_active?: boolean };
export type AnswerRegionCreate = Pick<AnswerRegion, "question_id" | "x" | "y" | "width" | "height">;

export function createUser(payload: UserCreate) {
  return apiRequest<User>("/users", { method: "POST", body: payload });
}

export function register(payload: AuthRegister) {
  return apiRequest<AuthResponse>("/auth/register", { method: "POST", body: payload });
}

export function login(payload: AuthLogin) {
  return apiRequest<AuthResponse>("/auth/login", { method: "POST", body: payload });
}

export function getCurrentUser(token = getStoredAuthToken()) {
  return apiRequest<User>("/auth/me", { token });
}

export async function logout() {
  const token = getStoredAuthToken();
  clearStoredAuthToken();
  if (token) {
    await apiRequest<void>("/auth/logout", { method: "POST", token });
  }
}

export function listUsers() {
  return apiRequest<User[]>("/users");
}

export function createCourse(payload: CourseCreate) {
  return apiRequest<Course>("/courses", { method: "POST", body: payload });
}

export type AuthenticatedCourseCreate = Omit<CourseCreate, "teacher_id">;

export function createAuthenticatedCourse(payload: AuthenticatedCourseCreate) {
  return apiRequest<Course>("/courses", { method: "POST", body: payload, token: getStoredAuthToken() });
}

export function listCourses() {
  return apiRequest<Course[]>("/courses");
}

export function getCourse(courseId: number) {
  return apiRequest<Course>(`/courses/${courseId}`);
}

export function updateCourse(courseId: number, payload: CourseUpdate) {
  return apiRequest<Course>(`/courses/${courseId}`, { method: "PATCH", body: payload });
}

export function createAssessment(courseId: number, payload: AssessmentCreate) {
  return apiRequest<Assessment>(`/courses/${courseId}/assessments`, {
    method: "POST",
    body: payload,
  });
}

export function listAssessments(courseId: number) {
  return apiRequest<Assessment[]>(`/courses/${courseId}/assessments`);
}

export function getAssessment(assessmentId: number) {
  return apiRequest<Assessment>(`/assessments/${assessmentId}`);
}

export function createQuestion(assessmentId: number, payload: QuestionCreate) {
  return apiRequest<Question>(`/assessments/${assessmentId}/questions`, {
    method: "POST",
    body: payload,
  });
}

export function listQuestions(assessmentId: number) {
  return apiRequest<Question[]>(`/assessments/${assessmentId}/questions`);
}

export function importQuestionsFromPaper(
  assessmentId: number,
  file: File,
  provider: QuestionImportProvider = "mock",
) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("provider", provider);
  return apiRequest<QuestionImportJob>(`/assessments/${assessmentId}/question-imports`, {
    method: "POST",
    formData,
  });
}

export function getQuestionImportJob(jobId: number) {
  return apiRequest<QuestionImportJob>(`/question-imports/${jobId}`);
}

export function createCustomGradingRun(assessmentId: number, payload: GradingRunCreate = {}) {
  return apiRequest<GradingRun>(`/assessments/${assessmentId}/grading-runs/custom`, {
    method: "POST",
    body: payload,
    token: getStoredAuthToken(),
    authErrorMessage: UPLOAD_AUTH_ERROR_MESSAGE,
  });
}

export function listAssessmentGradingRuns(assessmentId: number) {
  return apiRequest<GradingRun[]>(`/assessments/${assessmentId}/grading-runs`, {
    token: getStoredAuthToken(),
    authErrorMessage: UPLOAD_AUTH_ERROR_MESSAGE,
  });
}

export function getGradingRun(gradingRunId: number) {
  return apiRequest<GradingRun>(`/grading-runs/${gradingRunId}`, {
    token: getStoredAuthToken(),
    authErrorMessage: UPLOAD_AUTH_ERROR_MESSAGE,
  });
}

export function updateGradingRun(gradingRunId: number, payload: GradingRunUpdate) {
  return apiRequest<GradingRun>(`/grading-runs/${gradingRunId}`, {
    method: "PATCH",
    body: payload,
    token: getStoredAuthToken(),
    authErrorMessage: UPLOAD_AUTH_ERROR_MESSAGE,
  });
}

export function uploadGradingRunMaterials(
  gradingRunId: number,
  payload: { question_pdf?: File | null; solution_pdf?: File | null; rubric_pdf?: File | null },
) {
  const formData = new FormData();
  if (payload.question_pdf) {
    formData.append("question_pdf", payload.question_pdf);
  }
  if (payload.solution_pdf) {
    formData.append("solution_pdf", payload.solution_pdf);
  }
  if (payload.rubric_pdf) {
    formData.append("rubric_pdf", payload.rubric_pdf);
  }
  return apiRequest<GradingRun>(`/grading-runs/${gradingRunId}/materials`, {
    method: "POST",
    formData,
    token: getStoredAuthToken(),
    authErrorMessage: UPLOAD_AUTH_ERROR_MESSAGE,
  });
}

export function confirmGradingRunMaterials(gradingRunId: number) {
  return apiRequest<GradingRun>(`/grading-runs/${gradingRunId}/confirm-materials`, {
    method: "POST",
    token: getStoredAuthToken(),
    authErrorMessage: UPLOAD_AUTH_ERROR_MESSAGE,
  });
}

export function confirmGradingRunQuestionsRubrics(gradingRunId: number) {
  return apiRequest<GradingRun>(`/grading-runs/${gradingRunId}/confirm-questions-rubrics`, {
    method: "POST",
    token: getStoredAuthToken(),
    authErrorMessage: UPLOAD_AUTH_ERROR_MESSAGE,
  });
}

export function gradeGradingRunReadyRegionsMock(gradingRunId: number) {
  return apiRequest<BatchMockGradeResponse & { workflow_state: GradingRunWorkflowState }>(
    `/grading-runs/${gradingRunId}/grade-all-mock`,
    {
      method: "POST",
      token: getStoredAuthToken(),
      authErrorMessage: UPLOAD_AUTH_ERROR_MESSAGE,
    },
  );
}

export function acceptQuestionImportDrafts(jobId: number, draftQuestions: DraftQuestionAccept[]) {
  return apiRequest<QuestionImportAcceptResponse>(`/question-imports/${jobId}/accept`, {
    method: "POST",
    body: { draft_questions: draftQuestions },
  });
}

export function getQuestion(questionId: number) {
  return apiRequest<Question>(`/questions/${questionId}`);
}

export function createRubric(questionId: number, payload: RubricCreate) {
  return apiRequest<Rubric>(`/questions/${questionId}/rubrics`, {
    method: "POST",
    body: payload,
  });
}

export function listRubrics(questionId: number) {
  return apiRequest<Rubric[]>(`/questions/${questionId}/rubrics`);
}

export function uploadSubmission(
  assessmentId: number,
  payload: { student_identifier: string; student_name?: string; file: File },
) {
  const formData = new FormData();
  formData.append("student_identifier", payload.student_identifier);
  if (payload.student_name) {
    formData.append("student_name", payload.student_name);
  }
  formData.append("file", payload.file);
  return apiRequest<Submission>(`/assessments/${assessmentId}/submissions/upload`, {
    method: "POST",
    formData,
  });
}

export function uploadSubmissionZip(
  assessmentId: number,
  payload: {
    file: File;
    student_identifier_strategy?: "basename" | "sequential";
    student_name_prefix?: string;
  },
) {
  const formData = new FormData();
  formData.append("file", payload.file);
  if (payload.student_identifier_strategy) {
    formData.append("student_identifier_strategy", payload.student_identifier_strategy);
  }
  if (payload.student_name_prefix) {
    formData.append("student_name_prefix", payload.student_name_prefix);
  }
  return apiRequest<SubmissionZipUploadResponse>(
    `/assessments/${assessmentId}/submissions/upload-zip`,
    {
      method: "POST",
      formData,
    },
  );
}

export function listSubmissions(assessmentId: number) {
  return apiRequest<Submission[]>(`/assessments/${assessmentId}/submissions`);
}

export function deleteSubmission(assessmentId: number, submissionId: number) {
  return apiRequest<void>(`/assessments/${assessmentId}/submissions/${submissionId}`, {
    method: "DELETE",
  });
}

export function getSubmissionPageImageUrl(pageId: number) {
  return `${API_BASE_URL}/submission-pages/${pageId}/image`;
}

export function createAnswerRegion(pageId: number, payload: AnswerRegionCreate) {
  return apiRequest<AnswerRegion>(`/submission-pages/${pageId}/answer-regions`, {
    method: "POST",
    body: payload,
  });
}

export function suggestAnswerRegions(pageId: number) {
  return apiRequest<AnswerRegionSuggestionResponse>(`/submission-pages/${pageId}/answer-regions/suggest`, {
    method: "POST",
  });
}

export function listSubmissionAnswerRegions(submissionId: number) {
  return apiRequest<AnswerRegion[]>(`/submissions/${submissionId}/answer-regions`);
}

export function listAssessmentAnswerRegions(assessmentId: number, questionId?: number) {
  const query = questionId ? `?question_id=${questionId}` : "";
  return apiRequest<AnswerRegion[]>(`/assessments/${assessmentId}/answer-regions${query}`);
}

export function getAnswerRegionImageUrl(answerRegionId: number) {
  return `${API_BASE_URL}/answer-regions/${answerRegionId}/image`;
}


export function gradeAnswerRegion(answerRegionId: number) {
  return apiRequest<{ job: GradingJob; suggestion: GradeSuggestion }>(`/answer-regions/${answerRegionId}/grade`, {
    method: "POST",
  });
}

export function gradeAnswerRegionWithCodexDev(answerRegionId: number) {
  return apiRequest<BrowserCodexGradeResponse>(`/answer-regions/${answerRegionId}/grade-codex-dev`, {
    method: "POST",
    token: getStoredAuthToken(),
  });
}

export function batchMockGradeAssessment(assessmentId: number) {
  return apiRequest<BatchMockGradeResponse>(`/assessments/${assessmentId}/grade-all-mock`, {
    method: "POST",
  });
}

export function approveSelectedFinalGrades(assessmentId: number, payload: { grade_suggestion_ids: number[] }) {
  return apiRequest<BatchApproveFinalGradesResponse>(`/assessments/${assessmentId}/final-grades/approve-selected`, {
    method: "POST",
    body: payload,
    token: getStoredAuthToken(),
  });
}

export function listGradeSuggestions(answerRegionId: number) {
  return apiRequest<GradeSuggestion[]>(`/answer-regions/${answerRegionId}/grade-suggestions`);
}

export type FinalGradeActionPayload = {
  teacher_id?: number;
  teacher_comment?: string | null;
};

export type FinalGradeEditPayload = FinalGradeActionPayload & {
  final_score: string | number;
};

export function approveGradeSuggestion(gradeSuggestionId: number, payload: FinalGradeActionPayload) {
  return apiRequest<FinalGrade>(`/grade-suggestions/${gradeSuggestionId}/approve`, {
    method: "POST",
    body: payload,
    token: getStoredAuthToken(),
  });
}

export function editGradeSuggestion(gradeSuggestionId: number, payload: FinalGradeEditPayload) {
  return apiRequest<FinalGrade>(`/grade-suggestions/${gradeSuggestionId}/edit`, {
    method: "POST",
    body: payload,
    token: getStoredAuthToken(),
  });
}

export function rejectGradeSuggestion(gradeSuggestionId: number, payload: FinalGradeActionPayload) {
  return apiRequest<FinalGrade>(`/grade-suggestions/${gradeSuggestionId}/reject`, {
    method: "POST",
    body: payload,
    token: getStoredAuthToken(),
  });
}

export function finalizeGradeSuggestion(
  gradeSuggestionId: number,
  payload: FinalGradeEditPayload & { approval_status: "approved" | "edited" | "rejected" },
) {
  if (payload.approval_status === "approved") {
    return approveGradeSuggestion(gradeSuggestionId, payload);
  }
  if (payload.approval_status === "rejected") {
    return rejectGradeSuggestion(gradeSuggestionId, payload);
  }
  return editGradeSuggestion(gradeSuggestionId, payload);
}

export function getAnswerRegionFinalGrade(answerRegionId: number) {
  return apiRequest<FinalGrade>(`/answer-regions/${answerRegionId}/final-grade`);
}

export function getAssessmentReviewQueue(assessmentId: number) {
  return apiRequest<ReviewQueueItem[]>(`/assessments/${assessmentId}/review-queue`);
}

export function getAssessmentSummary(assessmentId: number) {
  return apiRequest<AssessmentSummary>(`/assessments/${assessmentId}/summary`);
}

export function getAssessmentFinalGradesExportUrl(assessmentId: number) {
  return `${API_BASE_URL}/assessments/${assessmentId}/export/final-grades.xlsx`;
}
