import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, type Page } from "@playwright/test";

import { API_BASE_URL, AUTH_TOKEN_STORAGE_KEY, type Assessment, type Course, type GradingRun, type Question, type Rubric, type Submission, type User } from "../lib/api";

const NODE_API_BASE_URL = process.env.E2E_API_BASE_URL?.replace(/\/$/, "") ?? API_BASE_URL;

export type TeacherCredentials = Readonly<{
  name: string;
  email: string;
  password: string;
}>;

export type SeededFlow = Readonly<{
  teacher: User;
  course: Course;
  assessment: Assessment;
  question: Question;
  rubric: Rubric;
  gradingRun: GradingRun;
  submission: Submission;
  answerRegionId: number;
  submissionPageId: number;
}>;

export function uniqueTeacherCredentials(prefix: string): TeacherCredentials {
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    name: `${prefix} Teacher ${stamp}`,
    email: `${prefix.toLowerCase().replace(/[^a-z0-9]+/g, ".")}+${stamp}@example.test`,
    password: `Playwright-${stamp}-!`,
  };
}

async function setInputValue(page: Page, testId: string, value: string) {
  await page.getByTestId(testId).evaluate((element, nextValue) => {
    const input = element as HTMLInputElement;
    const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    descriptor?.set?.call(input, nextValue as string);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }, value);
}

export async function registerTeacherViaBrowser(page: Page, credentials: TeacherCredentials) {
  await page.goto("/register", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("register-form")).toBeVisible();
  await page.waitForTimeout(500);
  await setInputValue(page, "register-name-input", credentials.name);
  await expect(page.getByTestId("register-name-input")).toHaveValue(credentials.name);
  await setInputValue(page, "register-email-input", credentials.email);
  await expect(page.getByTestId("register-email-input")).toHaveValue(credentials.email);
  await setInputValue(page, "register-password-input", credentials.password);
  await expect(page.getByTestId("register-password-input")).toHaveValue(credentials.password);
  await expect(page.getByTestId("register-submit-button")).toBeEnabled();
  await Promise.all([
    page.waitForURL(/\/courses(?:\?.*)?$/, { waitUntil: "commit" }),
    page.getByTestId("register-submit-button").click(),
  ]);
  await expect(page.getByTestId("current-teacher")).toContainText(credentials.name);
  await expect(page.getByTestId("current-teacher")).toContainText(credentials.email);
}


export async function logoutViaBrowser(page: Page) {
  await page.getByTestId("logout-button").click();
  await expect(page.getByText("No teacher logged in.")).toBeVisible();
}

export async function loginTeacherViaBrowser(page: Page, credentials: TeacherCredentials) {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("login-form")).toBeVisible();
  await page.waitForTimeout(500);
  await setInputValue(page, "login-email-input", credentials.email);
  await expect(page.getByTestId("login-email-input")).toHaveValue(credentials.email);
  await setInputValue(page, "login-password-input", credentials.password);
  await expect(page.getByTestId("login-password-input")).toHaveValue(credentials.password);
  await Promise.all([
    page.waitForURL(/\/courses(?:\?.*)?$/, { waitUntil: "commit" }),
    page.getByTestId("login-submit-button").click(),
  ]);
  await expect(page.getByTestId("current-teacher")).toContainText(credentials.email);
}

export async function browserAuthSmoke(page: Page, credentials: TeacherCredentials) {
  await registerTeacherViaBrowser(page, credentials);
  await logoutViaBrowser(page);
  await loginTeacherViaBrowser(page, credentials);
}

export async function readAuthToken(page: Page): Promise<string> {
  const token = await page.evaluate((storageKey) => window.localStorage.getItem(storageKey), AUTH_TOKEN_STORAGE_KEY);
  if (!token) {
    throw new Error("Expected auth token in browser localStorage");
  }
  return token;
}

export function createSyntheticFiles(prefix: string) {
  const dir = mkdtempSync(join(tmpdir(), `teacher-assistant-${prefix}-`));
  const questionPdf = join(dir, "question.pdf");
  const solutionPdf = join(dir, "solution.pdf");
  const rubricPdf = join(dir, "rubric.pdf");
  const submissionImage = join(dir, "submission.png");

  writeFileSync(questionPdf, buildSinglePagePdf(`${prefix} question paper`));
  writeFileSync(solutionPdf, buildSinglePagePdf(`${prefix} model answer`));
  writeFileSync(rubricPdf, buildSinglePagePdf(`${prefix} rubric`));
  writeFileSync(submissionImage, buildPngPixel());

  return { dir, questionPdf, solutionPdf, rubricPdf, submissionImage };
}

export async function apiJson<T>(path: string, options: { method?: string; body?: unknown; token?: string | null } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  const response = await fetch(`${NODE_API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers: Object.keys(headers).length > 0 ? headers : undefined,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API ${response.status} ${response.statusText} for ${path}: ${detail}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function apiMultipart<T>(
  path: string,
  formData: FormData,
  options: { method?: string; token?: string | null } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  const response = await fetch(`${NODE_API_BASE_URL}${path}`, {
    method: options.method ?? "POST",
    headers: Object.keys(headers).length > 0 ? headers : undefined,
    body: formData,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API ${response.status} ${response.statusText} for ${path}: ${detail}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function seedCustomControlledFlow(token: string, files: ReturnType<typeof createSyntheticFiles>): Promise<SeededFlow> {
  const teacher = await apiJson<User>("/auth/me", { token });
  const course = await apiJson<Course>("/courses", {
    method: "POST",
    token,
    body: {
      teacher_id: teacher.id,
      code: `TA-W2-020-${Date.now().toString(36).toUpperCase()}`,
      title: "TA-W2-020 Playwright smoke course",
      department: "QA",
      semester: "Smoke",
    },
  });

  const assessment = await apiJson<Assessment>(`/courses/${course.id}/assessments`, {
    method: "POST",
    token,
    body: {
      title: "Custom controlled smoke assessment",
      assessment_type: "exam",
      total_marks: 10,
      status: "draft",
    },
  });

  const question = await apiJson<Question>(`/assessments/${assessment.id}/questions`, {
    method: "POST",
    token,
    body: {
      question_no: "1",
      question_text: "Synthetic short-answer prompt for E2E smoke testing.",
      total_marks: 10,
      model_answer: "Synthetic model answer.",
    },
  });

  const rubric = await apiJson<Rubric>(`/questions/${question.id}/rubrics`, {
    method: "POST",
    token,
    body: {
      version: 1,
      is_active: true,
      rubric_json: {
        total_marks: 10,
        criteria: [
          {
            id: "c1",
            name: "Correct idea",
            description: "Identifies the correct principle or idea.",
            max_marks: 6,
          },
          {
            id: "c2",
            name: "Clarity",
            description: "Shows clear presentation.",
            max_marks: 4,
          },
        ],
      },
},
  });

  const gradingRun = await apiJson<GradingRun>(`/assessments/${assessment.id}/grading-runs/custom`, {
    method: "POST",
    token,
    body: {
      mode: "custom_controlled",
      notes: "Playwright smoke flow",
      marking_policy: "general",
    },
  });

  const materialForm = new FormData();
  materialForm.append("question_pdf", new File([filesToBuffer(files.questionPdf)], "question.pdf", { type: "application/pdf" }));
  materialForm.append("solution_pdf", new File([filesToBuffer(files.solutionPdf)], "solution.pdf", { type: "application/pdf" }));
  materialForm.append("rubric_pdf", new File([filesToBuffer(files.rubricPdf)], "rubric.pdf", { type: "application/pdf" }));
  await apiMultipart<GradingRun>(`/grading-runs/${gradingRun.id}/materials`, materialForm, { token });
  const confirmedMaterials = await apiJson<GradingRun>(`/grading-runs/${gradingRun.id}/confirm-materials`, {
    method: "POST",
    token,
  });
  await apiJson<GradingRun>(`/grading-runs/${gradingRun.id}/confirm-questions-rubrics`, {
    method: "POST",
    token,
  });

  const submissionForm = new FormData();
  submissionForm.append("student_identifier", "synthetic-script-001");
  submissionForm.append("student_name", "Synthetic Script");
  submissionForm.append("file", new File([filesToBuffer(files.submissionImage)], "script.png", { type: "image/png" }));
  const submission = await apiMultipart<Submission>(`/assessments/${assessment.id}/submissions/upload`, submissionForm, { token });

  const submissionPageId = submission.pages[0]?.id;
  if (!submissionPageId) {
    throw new Error("Synthetic submission did not create a page");
  }

  const answerRegion = await apiJson<{ id: number }>(`/submission-pages/${submissionPageId}/answer-regions`, {
    method: "POST",
    token,
    body: {
      question_id: question.id,
      x: 0,
      y: 0,
      width: 1,
      height: 1,
    },
  });

  if (!confirmedMaterials.materials_confirmed_at) {
    throw new Error("Grading-run materials were not confirmed");
  }

  return {
    teacher,
    course,
    assessment,
    question,
    rubric,
    gradingRun,
    submission,
    answerRegionId: answerRegion.id,
    submissionPageId,
  };
}

function buildPngPixel() {
  // 1x1 transparent PNG; valid for PIL/Pillow and backend page extraction.
  return Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jFioAAAAASUVORK5CYII=",
    "base64",
  );
}

function buildSinglePagePdf(title: string) {
  const escapedTitle = title.replace(/([\\()])/g, "\\$1");
  const stream = `BT /F1 18 Tf 72 720 Td (${escapedTitle}) Tj ET`;
  const objects = [
    "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
    "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
    "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
    `4 0 obj\n<< /Length ${Buffer.byteLength(stream, "utf8")} >>\nstream\n${stream}\nendstream\nendobj\n`,
    "5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
  ];

  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const object of objects) {
    offsets.push(Buffer.byteLength(pdf, "utf8"));
    pdf += object;
  }

  const xrefOffset = Buffer.byteLength(pdf, "utf8");
  let xref = `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let index = 1; index < offsets.length; index += 1) {
    xref += `${String(offsets[index]).padStart(10, "0")} 00000 n \n`;
  }

  const trailer = `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf + xref + trailer, "utf8");
}

function filesToBuffer(filePath: string) {
  return readFileSync(filePath);
}
