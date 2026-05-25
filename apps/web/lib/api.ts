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

type RequestOptions = {
  method?: string;
  body?: unknown;
};

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
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

export function createUser(payload: UserCreate) {
  return apiRequest<User>("/users", { method: "POST", body: payload });
}

export function listUsers() {
  return apiRequest<User[]>("/users");
}

export function createCourse(payload: CourseCreate) {
  return apiRequest<Course>("/courses", { method: "POST", body: payload });
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
