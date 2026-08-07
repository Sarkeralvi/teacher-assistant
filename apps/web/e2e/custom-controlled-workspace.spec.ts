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
