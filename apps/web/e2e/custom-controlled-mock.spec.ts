import { expect, test } from "@playwright/test";

import {
  apiJson,
  browserAuthSmoke,
  createSyntheticFiles,
  logoutViaBrowser,
  readAuthToken,
  seedCustomControlledFlow,
  uniqueTeacherCredentials,
} from "./support";

test("custom controlled mock grading loop keeps FinalGrade gated until teacher approval", async ({ page }) => {
  const credentials = uniqueTeacherCredentials("CustomControlled");
  await browserAuthSmoke(page, credentials);

  const token = await readAuthToken(page);
  const files = createSyntheticFiles("ta-w2-020");
  const seeded = await seedCustomControlledFlow(token, files);

  await page.goto(`/assessments/${seeded.assessment.id}/grading-run`);
  await expect(page.getByRole("heading", { name: "Custom Controlled Grading Run" })).toBeVisible();
  await expect(page.getByText("Materials confirmed: yes")).toBeVisible();
  await expect(page.getByRole("button", { name: "Bulk mock grade ungraded answers" })).toBeVisible();
  await page.getByRole("button", { name: "Bulk mock grade ungraded answers" }).click();

  await expect(page.getByText("Review readiness: 1 suggestions")).toBeVisible();
  await expect(page.getByText("Export readiness: 0 final grades")).toBeVisible();

  const reviewBeforeApproval = await apiJson<Array<{ latest_grade_suggestion: { id: number; needs_review: boolean } | null; final_grade: unknown | null }>>(
    `/assessments/${seeded.assessment.id}/review-queue`,
  );
  expect(reviewBeforeApproval).toHaveLength(1);
  expect(reviewBeforeApproval[0]?.latest_grade_suggestion?.needs_review).toBe(true);
  expect(reviewBeforeApproval[0]?.final_grade).toBeNull();

  await page.goto(`/assessments/${seeded.assessment.id}`);
  await page.getByLabel("Select existing teacher").selectOption(String(seeded.teacher.id));
  await expect(page.getByText(`Current demo teacher`)).toBeVisible();
  await expect(page.getByText("needs_review: true")).toBeVisible();
  await expect(page.getByText("Teacher review is required before any FinalGrade is created.")).toBeVisible();

  await page.getByRole("button", { name: "Finalize as approved" }).click();
  await expect(page.getByText(/Current final grade:/i)).toBeVisible();

  const finalGrade = await apiJson<{ id: number; final_score: string | number; approval_status: string }>(
    `/answer-regions/${seeded.answerRegionId}/final-grade`,
    { token },
  );
  expect(finalGrade.final_score).not.toBeNull();
  expect(finalGrade.approval_status).toBe("approved");

  const reviewAfterApproval = await apiJson<Array<{ latest_grade_suggestion: { id: number } | null; final_grade: { id: number } | null }>>(
    `/assessments/${seeded.assessment.id}/review-queue`,
  );
  expect(reviewAfterApproval).toHaveLength(1);
  expect(reviewAfterApproval[0]?.final_grade?.id).toBeTruthy();

  const exportLink = page.getByRole("link", { name: "Download final grades (.xlsx)" });
  await expect(exportLink).toBeVisible();
  await expect(exportLink).toHaveAttribute(
    "href",
    `http://host.docker.internal:8000/assessments/${seeded.assessment.id}/export/final-grades.xlsx`,
  );

  await logoutViaBrowser(page);
});
