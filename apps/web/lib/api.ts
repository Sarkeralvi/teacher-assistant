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

export type GradeSuggestion = {
  id: number;
  grading_job_id: number;
  answer_region_id: number;
  question_id: number;
  model_provider: string;
  model_name: string;
  prompt_version: string;
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
};

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const hasJsonBody = options.body !== undefined;
  const headers: Record<string, string> = {};
  if (hasJsonBody) {
    headers["Content-Type"] = "application/json";
  }
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers: Object.keys(headers).length > 0 ? headers : undefined,
    body: hasJsonBody ? JSON.stringify(options.body) : options.formData,
    cache: "no-store",
  });

  if (!response.ok) {
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
  return apiRequest<{ job: unknown; suggestion: GradeSuggestion }>(`/answer-regions/${answerRegionId}/grade`, {
    method: "POST",
  });
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
