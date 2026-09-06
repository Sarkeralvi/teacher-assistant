import { readFileSync } from "node:fs";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import {
  browserAuthSmoke,
  uniqueTeacherCredentials,
} from "./support";
import { AUTH_TOKEN_STORAGE_KEY } from "../lib/api";

const enabled = process.env.REAL_PROVIDER_REHEARSAL === "1";
const apiBase = process.env.E2E_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
const providers = (process.env.REAL_REHEARSAL_PROFILES ?? "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const sourceToken = process.env.REAL_REHEARSAL_SOURCE_TOKEN ?? "";
const sourceAssessmentId = Number(process.env.REAL_REHEARSAL_SOURCE_ASSESSMENT_ID ?? "0");
const sourceQuestionId = Number(process.env.REAL_REHEARSAL_SOURCE_QUESTION_ID ?? "0");
const sourceAnswerRegionId = Number(process.env.REAL_REHEARSAL_SOURCE_ANSWER_REGION_ID ?? "0");
const questionPdf = process.env.REAL_REHEARSAL_QUESTION_PDF ?? "";
const solutionPdf = process.env.REAL_REHEARSAL_SOLUTION_PDF ?? "";
const rubricPdf = process.env.REAL_REHEARSAL_RUBRIC_PDF ?? "";
const studentImage = process.env.REAL_REHEARSAL_STUDENT_IMAGE ?? "";
const bulkZip = process.env.REAL_REHEARSAL_BULK_ZIP ?? "";

type JsonObject = Record<string, unknown>;
type MultipartValue = string | number | boolean | {
  name: string;
  mimeType: string;
  buffer: Buffer;
};

async function api<T>(
  request: APIRequestContext,
  path: string,
  token: string,
  options: {
    method?: "GET" | "POST" | "PATCH";
    data?: unknown;
    multipart?: Record<string, MultipartValue>;
  } = {},
): Promise<T> {
  const response = await request.fetch(`${apiBase}${path}`, {
    method: options.method ?? "GET",
    headers: { Authorization: `Bearer ${token}` },
    data: options.data,
    multipart: options.multipart,
    timeout: 900_000,
  });
  if (!response.ok()) {
    throw new Error(`${options.method ?? "GET"} ${path} failed: ${response.status()} ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

async function browserToken(page: Page, label: string): Promise<string> {
  await browserAuthSmoke(page, uniqueTeacherCredentials(label));
  const token = await page.evaluate((key) => window.localStorage.getItem(key), AUTH_TOKEN_STORAGE_KEY);
  if (!token) throw new Error("Browser authentication token was not stored");
  return token;
}

async function sourceQuestion(request: APIRequestContext) {
  const question = await api<JsonObject>(
    request,
    `/questions/${sourceQuestionId}`,
    sourceToken,
  );
  const rubrics = await api<JsonObject[]>(
    request,
    `/questions/${sourceQuestionId}/rubrics`,
    sourceToken,
  );
  const rubric = rubrics.find((item) => item.is_active === true) ?? rubrics[0];
  if (!rubric) throw new Error("Source question has no rubric");
  const answerRegion = await api<JsonObject>(
    request,
    `/answer-regions/${sourceAnswerRegionId}`,
    sourceToken,
  );
  if (typeof answerRegion.manual_answer_text !== "string" || !answerRegion.manual_answer_text.trim()) {
    throw new Error("Source answer region has no teacher-confirmed transcript");
  }
  return { question, rubric, answerRegion };
}

async function createAssessment(
  request: APIRequestContext,
  token: string,
  label: string,
): Promise<{ assessment: JsonObject; teacher: JsonObject }> {
  const teacher = await api<JsonObject>(request, "/auth/me", token);
  const course = await api<JsonObject>(request, "/courses", token, {
    method: "POST",
    data: {
      teacher_id: teacher.id,
      code: `REAL-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 6)}`,
      title: `Real provider rehearsal ${label}`,
      department: "Controlled QA",
      semester: "Rehearsal",
    },
  });
  const assessment = await api<JsonObject>(request, `/courses/${course.id}/assessments`, token, {
    method: "POST",
    data: {
      title: `Real provider rehearsal ${label}`,
      assessment_type: "exam",
      total_marks: 6,
      status: "draft",
    },
  });
  return { assessment, teacher };
}

async function createConfirmedGradingRun(
  request: APIRequestContext,
  token: string,
  assessmentId: number,
) {
  const source = await sourceQuestion(request);
  const question = await api<JsonObject>(request, `/assessments/${assessmentId}/questions`, token, {
    method: "POST",
    data: {
      question_no: source.question.question_no,
      question_text: source.question.question_text,
      total_marks: source.question.total_marks,
      model_answer: source.question.model_answer,
    },
  });
  await api(request, `/questions/${question.id}/rubrics`, token, {
    method: "POST",
    data: {
      version: 1,
      is_active: true,
      rubric_json: source.rubric.rubric_json,
    },
  });
  const importJob = await api<JsonObject>(
    request,
    `/assessments/${assessmentId}/question-imports`,
    token,
    {
      method: "POST",
      multipart: {
        file: {
          name: "question.pdf",
          mimeType: "application/pdf",
          buffer: readFileSync(questionPdf),
        },
        provider: "mock",
        provider_data_boundary_confirmed: false,
      },
    },
  );
  const importedDrafts = importJob.draft_questions as JsonObject[];
  if (!importedDrafts[0]?.draft_id) throw new Error("Mock question import produced no draft");
  await api(request, `/question-imports/${importJob.id}/accept`, token, {
    method: "POST",
    data: {
      draft_questions: [{
        draft_id: importedDrafts[0].draft_id,
        question_no: source.question.question_no,
        question_text: source.question.question_text,
        model_answer: source.question.model_answer,
        total_marks: source.question.total_marks,
      }],
    },
  });
  const run = await api<JsonObject>(request, `/assessments/${assessmentId}/grading-runs/custom`, token, {
    method: "POST",
    data: { mode: "custom_controlled", marking_policy: "general", notes: "Real provider rehearsal" },
  });
  await api(request, `/grading-runs/${run.id}/materials`, token, {
    method: "POST",
    multipart: {
      question_pdf: { name: "question.pdf", mimeType: "application/pdf", buffer: readFileSync(questionPdf) },
      solution_pdf: { name: "solution.pdf", mimeType: "application/pdf", buffer: readFileSync(solutionPdf) },
      rubric_pdf: { name: "rubric.pdf", mimeType: "application/pdf", buffer: readFileSync(rubricPdf) },
    },
  });
  await api(request, `/grading-runs/${run.id}/confirm-materials`, token, { method: "POST" });
  await api(request, `/grading-runs/${run.id}/confirm-questions-rubrics`, token, { method: "POST" });
  return { question, run };
}

async function lockProfile(page: Page, assessmentId: number, profileId: string) {
  console.log(`[rehearsal] ${profileId}: opening assessment ${assessmentId}`);
  await page.goto(`/assessments/${assessmentId}`);
  const select = page.getByTestId("brain-profile-select");
  await expect(select).toBeVisible({ timeout: 30_000 });
  console.log(`[rehearsal] ${profileId}: selecting profile`);
  await select.selectOption(profileId, { timeout: 30_000 });
  const consent = page.getByTestId("brain-profile-consent").getByRole("checkbox");
  await consent.waitFor({ state: "visible", timeout: 5_000 }).catch(() => undefined);
  if (await consent.isVisible()) await consent.check();
  const lockButton = page.getByRole("button", { name: "Lock profile for this grading run" });
  await expect(lockButton).toBeEnabled({ timeout: 10_000 });
  console.log(`[rehearsal] ${profileId}: locking profile`);
  await lockButton.click();
  await expect(page.getByTestId("brain-profile-locked")).toContainText("Locked to", {
    timeout: 30_000,
  });
}

test.describe("explicit real-provider rehearsal", () => {
  test.skip(!enabled, "Set REAL_PROVIDER_REHEARSAL=1 for a founder-authorized run");
  test.describe.configure({ mode: "serial", timeout: 1_200_000 });

  for (const profileId of providers) {
    test(`${profileId}: browser reference preparation reaches review-only drafts`, async ({ page, request }) => {
      const token = await browserToken(page, `Reference ${profileId}`);
      const { assessment } = await createAssessment(request, token, `reference ${profileId}`);
      const run = await api<JsonObject>(request, `/assessments/${assessment.id}/grading-runs/custom`, token, {
        method: "POST",
        data: { mode: "custom_controlled", marking_policy: "general", notes: "Real reference rehearsal" },
      });
      await page.goto(`/assessments/${assessment.id}/grading-run`);
      await page.locator("#question-pdf").setInputFiles(questionPdf);
      await page.locator("#solution-pdf").setInputFiles(solutionPdf);
      await page.locator("#rubric-pdf").setInputFiles(rubricPdf);
      await page.getByRole("button", { name: "Upload three PDFs" }).click();
      await expect(page.getByText("All three references are stored.")).toBeVisible({ timeout: 60_000 });
      await page.getByTestId("brain-profile-select").selectOption(profileId);
      const consent = page.getByTestId("brain-profile-consent").getByRole("checkbox");
      await consent.waitFor({ state: "visible", timeout: 5_000 }).catch(() => undefined);
      if (await consent.isVisible()) await consent.check();
      const lockButton = page.getByRole("button", { name: "Lock profile for this grading run" });
      await expect(lockButton).toBeEnabled({ timeout: 10_000 });
      await lockButton.click();
      await expect(page.getByTestId("brain-profile-locked")).toBeVisible();
      await page.getByText("I confirm these are the correct question", { exact: false }).locator("..").getByRole("checkbox").check();
      await page.getByRole("button", { name: "Confirm and extract drafts" }).click();
      await expect(page.getByRole("heading", { name: "Review questions, model answers, and rubric" })).toBeVisible({
        timeout: 900_000,
      });
      const extraction = await api<JsonObject>(request, `/grading-runs/${run.id}/reference-extraction`, token);
      expect(extraction.status).toBe("succeeded");
      expect(Number(extraction.qwen_call_count)).toBe(1);
    });

    test(`${profileId}: browser single-answer grading persists a draft only`, async ({ page, request }) => {
      const token = await browserToken(page, `Single ${profileId}`);
      const { assessment } = await createAssessment(request, token, `single ${profileId}`);
      const source = await sourceQuestion(request);
      const { question } = await createConfirmedGradingRun(request, token, Number(assessment.id));
      await lockProfile(page, Number(assessment.id), profileId);
      await page.getByPlaceholder("student_identifier").fill(`single-${profileId}-${Date.now()}`);
      await page.getByTestId("submission-file-input").setInputFiles(studentImage);
      const uploadedResponse = page.waitForResponse(
        (response) => response.url().includes("/submissions/upload") && response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Upload submission" }).click();
      const submissionResponse = await uploadedResponse;
      expect(submissionResponse.ok()).toBe(true);
      const submission = await submissionResponse.json() as JsonObject;
      const pages = submission.pages as JsonObject[];
      const region = await api<JsonObject>(request, `/submission-pages/${pages[0].id}/answer-regions`, token, {
        method: "POST",
        data: {
          question_id: question.id,
          x: 0,
          y: 0,
          width: 1,
          height: 1,
          full_answer_confirmed: true,
          manual_answer_text: source.answerRegion.manual_answer_text,
        },
      });
      await api(request, `/answer-regions/${region.id}/corrections/full-answer-confirmation`, token, {
        method: "PATCH",
        data: {
          full_answer_confirmed: true,
          continuation_not_needed: true,
          packet_status: "complete",
          manual_answer_text: source.answerRegion.manual_answer_text,
        },
      });
      await page.reload();
      const gradeButton = page.getByRole("button", { name: "Grade confirmed answer with the configured brain" }).last();
      await expect(gradeButton).toBeEnabled({ timeout: 30_000 });
      const gradeResponsePromise = page.waitForResponse(
        (response) => response.url().endsWith(`/answer-regions/${region.id}/grade-brain`) && response.request().method() === "POST",
        { timeout: 900_000 },
      );
      await gradeButton.click();
      const gradeResponse = await gradeResponsePromise;
      expect(gradeResponse.ok(), await gradeResponse.text()).toBe(true);
      const payload = await gradeResponse.json() as JsonObject;
      const suggestion = payload.suggestion as JsonObject;
      expect(suggestion.model_provider).toBe(profileId);
      expect(suggestion.needs_review).toBe(true);
      const finalGrade = await request.get(`${apiBase}/answer-regions/${region.id}/final-grade`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(finalGrade.status()).toBe(404);
    });
  }

  test("bulk run is distinct and remains draft-only", async ({ page, request }) => {
    const profileId = process.env.REAL_REHEARSAL_BULK_PROFILE ?? providers[0];
    if (!profileId || !bulkZip) test.skip(true, "Bulk profile and ZIP are required");
    const token = await browserToken(page, `Bulk ${profileId}`);
    const { assessment } = await createAssessment(request, token, `bulk ${profileId}`);
    const { run } = await createConfirmedGradingRun(request, token, Number(assessment.id));
    await page.goto(`/assessments/${assessment.id}/bulk-evaluation`);
    await page.locator('input[type="file"]').setInputFiles(bulkZip);
    await page.locator("select").filter({ has: page.locator(`option[value="${run.id}"]`) }).selectOption(String(run.id));
    await page.getByTestId("bulk-brain-profile-select").selectOption(profileId);
    await page.getByRole("checkbox").check();
    // Two page reads plus bounded edit-repair and formula-verification calls for
    // both scripts fit inside this explicit rehearsal budget.
    await page.getByLabel("Maximum model calls").fill("16");
    const createResponsePromise = page.waitForResponse(
      (response) => response.url().includes("/bulk-evaluation-runs") && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Start bulk evaluation" }).click();
    const createResponse = await createResponsePromise;
    expect(createResponse.ok(), await createResponse.text()).toBe(true);
    const bulkRun = await createResponse.json() as JsonObject;
    const bulkRunId = Number(bulkRun.id);
    await expect.poll(async () => {
      const current = await api<JsonObject>(request, `/bulk-evaluation-runs/${bulkRunId}`, token);
      return current.status;
    }, { timeout: 1_100_000 }).toMatch(/^(completed_with_exceptions|review_ready)$/);

    const firstState = await api<JsonObject>(request, `/bulk-evaluation-runs/${bulkRunId}`, token);
    if (firstState.status === "completed_with_exceptions") {
      const source = await sourceQuestion(request);
      const exceptions = await api<JsonObject[]>(request, `/bulk-evaluation-runs/${bulkRunId}/exceptions`, token);
      expect(exceptions).toHaveLength(2);
      for (const exception of exceptions) {
        const itemId = Number(exception.item_id);
        const item = await api<JsonObject>(request, `/bulk-evaluation-runs/${bulkRunId}/items/${itemId}`, token);
        await api(request, `/question-node-mappings/${item.mapping_id}/confirm`, token, {
          method: "POST",
          data: { teacher_confirmed: true },
        });
        await api(request, `/answer-regions/${item.answer_region_id}/corrections/full-answer-confirmation`, token, {
          method: "PATCH",
          data: {
            full_answer_confirmed: true,
            continuation_not_needed: true,
            packet_status: "complete",
            manual_answer_text: source.answerRegion.manual_answer_text,
          },
        });
      }

      console.log(`[rehearsal] bulk ${bulkRunId}: confirmed ${exceptions.length} exception packets`);
      await page.reload();
      await expect(page.getByRole("heading", { name: "3. Exceptions requiring attention" })).toBeVisible({ timeout: 30_000 });
      for (const exception of exceptions) {
        const itemId = Number(exception.item_id);
        const studentIdentifier = String(exception.student_identifier);
        console.log(`[rehearsal] bulk ${bulkRunId}: resuming ${studentIdentifier} item ${itemId}`);
        const article = page.locator("article").filter({ hasText: studentIdentifier });
        await expect(article).toBeVisible({ timeout: 30_000 });
        const resumeResponsePromise = page.waitForResponse(
          (response) => response.url().endsWith(`/bulk-evaluation-runs/${bulkRunId}/items/${itemId}/resume`) && response.request().method() === "POST",
          { timeout: 30_000 },
        );
        await article.getByRole("button", { name: "Resume item" }).click({ timeout: 30_000 });
        const resumeResponse = await resumeResponsePromise;
        expect(resumeResponse.ok(), await resumeResponse.text()).toBe(true);
        await expect.poll(async () => {
          const item = await api<JsonObject>(request, `/bulk-evaluation-runs/${bulkRunId}/items/${itemId}`, token);
          return item.status;
        }, { timeout: 900_000 }).toMatch(/^(graded|exception|uncertain)$/);
        const completedItem = await api<JsonObject>(request, `/bulk-evaluation-runs/${bulkRunId}/items/${itemId}`, token);
        if (completedItem.status === "graded") {
          expect(Number(completedItem.grade_suggestion_id)).toBeGreaterThan(0);
        } else {
          expect((completedItem.exception_codes as unknown[]).length).toBeGreaterThan(0);
        }
        await page.reload();
      }
    }

    const completedRun = await api<JsonObject>(request, `/bulk-evaluation-runs/${bulkRunId}`, token);
    const completedItems = completedRun.items as JsonObject[];
    expect(completedItems.some((item) => Number(item.grade_suggestion_id) > 0)).toBe(true);
    for (const item of completedItems) {
      const finalGrade = await request.get(`${apiBase}/answer-regions/${item.answer_region_id}/final-grade`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(finalGrade.status()).toBe(404);
    }
    const progress = page.getByRole("heading", { name: "2. Background progress" }).locator("..");
    await expect(progress.getByText(/Run #\d+ · review_ready/).first()).toBeVisible({ timeout: 1_100_000 });
    await expect(page.getByText("Draft only", { exact: true })).toBeVisible();
  });
});
