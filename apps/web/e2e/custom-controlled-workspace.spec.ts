import { expect, test } from "@playwright/test";

import {
  apiJson,
  browserAuthSmoke,
  createSyntheticFiles,
  readAuthToken,
  seedCustomControlledFlow,
  uniqueTeacherCredentials,
} from "./support";

test("custom controlled workspace reveals only the next teacher action", async ({ page }) => {
  const credentials = uniqueTeacherCredentials("CustomControlled");
  await browserAuthSmoke(page, credentials);

  const token = await readAuthToken(page);
  const files = createSyntheticFiles("teacher-workspace");
  const seeded = await seedCustomControlledFlow(token, files);

  await page.goto(`/assessments/${seeded.assessment.id}`);
  await expect(page.getByRole("heading", { name: "Custom controlled smoke assessment" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Review references" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Upload one answer script" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Uploaded scripts" })).toBeVisible();
  await expect(page.getByText("FUTURE / not part", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Run automatic mapping" })).toHaveCount(0);

  await page.goto(`/assessments/${seeded.assessment.id}/grading-run`);
  await expect(page.getByRole("heading", { name: "Prepare grading references" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Continue to student evidence" })).toBeVisible();
  await expect(page.getByText("Start custom controlled run")).toHaveCount(0);

  const review = await apiJson<Array<{ latest_grade_suggestion: unknown | null; final_grade: unknown | null }>>(
    `/assessments/${seeded.assessment.id}/review-queue`,
    { token },
  );
  expect(review).toHaveLength(1);
  expect(review[0]?.latest_grade_suggestion).toBeNull();
  expect(review[0]?.final_grade).toBeNull();
});

test("teacher uploads the three reference PDFs once through the browser", async ({ page }) => {
  const credentials = uniqueTeacherCredentials("ReferenceUpload");
  await browserAuthSmoke(page, credentials);

  const token = await readAuthToken(page);
  const teacher = await apiJson<{ id: number }>("/auth/me", { token });
  const course = await apiJson<{ id: number }>("/courses", {
    method: "POST",
    token,
    body: {
      teacher_id: teacher.id,
      code: `TA-UPLOAD-${Date.now().toString(36).toUpperCase()}`,
      title: "Reference upload browser smoke course",
      department: "QA",
      semester: "Smoke",
    },
  });
  const assessment = await apiJson<{ id: number }>(`/courses/${course.id}/assessments`, {
    method: "POST",
    token,
    body: {
      title: "Reference upload browser smoke assessment",
      assessment_type: "exam",
      total_marks: 10,
      status: "draft",
    },
  });
  const files = createSyntheticFiles("reference-upload-browser");

  await page.goto(`/assessments/${assessment.id}/grading-run`);
  await expect(page.getByRole("heading", { name: "Prepare grading references" })).toBeVisible();
  await page.locator("#question-pdf").setInputFiles(files.questionPdf);
  await page.locator("#solution-pdf").setInputFiles(files.solutionPdf);
  await page.locator("#rubric-pdf").setInputFiles(files.rubricPdf);
  await expect(page.getByText("question.pdf", { exact: true })).toBeVisible();
  await expect(page.getByText("solution.pdf", { exact: true })).toBeVisible();
  await expect(page.getByText("rubric.pdf", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Upload three PDFs" }).click();
  await expect(page.getByText("All three references are stored.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Confirm files and extract drafts" })).toBeVisible();
  await expect(page.getByText("You do not need to upload the question paper anywhere else.")).toBeVisible();
});

test("teacher uploads a student script and receives only a pending mock draft", async ({ page }) => {
  const credentials = uniqueTeacherCredentials("ScriptUpload");
  await browserAuthSmoke(page, credentials);

  const token = await readAuthToken(page);
  const files = createSyntheticFiles("student-script-browser");
  const seeded = await seedCustomControlledFlow(token, files);

  await page.goto(`/assessments/${seeded.assessment.id}`);
  await expect(page.getByRole("heading", { name: "Upload one answer script" })).toBeVisible();
  await page.getByPlaceholder("student_identifier").fill("browser-script-001");
  await page.getByTestId("submission-file-input").setInputFiles(files.submissionImage);
  await expect(page.getByText("Selected file: submission.png")).toBeVisible();
  await page.getByRole("button", { name: "Upload submission" }).click();
  await expect(page.getByText("Total submissions: 2", { exact: false })).toBeVisible();

  const graded = await apiJson<{
    suggestion: { model_provider: string; needs_review: boolean };
  }>(`/answer-regions/${seeded.answerRegionId}/grade`, {
    method: "POST",
    token,
  });
  expect(graded.suggestion.model_provider).toBe("mock");
  expect(graded.suggestion.needs_review).toBe(true);

  const review = await apiJson<Array<{ latest_grade_suggestion: unknown | null; final_grade: unknown | null }>>(
    `/assessments/${seeded.assessment.id}/review-queue`,
    { token },
  );
  expect(review).toHaveLength(1);
  expect(review[0]?.latest_grade_suggestion).not.toBeNull();
  expect(review[0]?.final_grade).toBeNull();
});
