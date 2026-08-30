import { expect, test } from "@playwright/test";

import {
  browserAuthSmoke,
  createSyntheticFiles,
  seedCustomControlledFlow,
  uniqueTeacherCredentials,
} from "./support";

test("bulk workspace hides granular evidence until manuscript inspection", async ({ page }) => {
  await browserAuthSmoke(page, uniqueTeacherCredentials("BulkWorkspace"));
  const files = createSyntheticFiles("bulk-workspace");
  const token = await page.evaluate(() => window.localStorage.getItem("teacherAssistantAuthToken"));
  if (!token) throw new Error("Browser authentication token was not stored");
  const seeded = await seedCustomControlledFlow(token, files);
  const run = {
    id: 901,
    assessment_id: seeded.assessment.id,
    grading_run_id: seeded.gradingRun.id,
    created_by_teacher_id: 1,
    provider: "llama_cpp_qwen38",
    model_name: "qwen3.8-test",
    marking_policy: "general",
    policy_version: "bulk-supervised-qwen38-v1",
    reference_bundle_sha256: "a".repeat(64),
    review_snapshot_sha256: null,
    archive_sha256: "b".repeat(64),
    manifest_sha256: null,
    status: "review_ready",
    stage: "review",
    authorized_call_limit: 100,
    calls_used: 4,
    total_submissions: 1,
    total_pages: 2,
    total_items: 2,
    processed_items: 2,
    clean_item_count: 1,
    exception_count: 1,
    approved_count: 0,
    stop_requested: false,
    heartbeat_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    error: null,
    items: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  await page.route(
    `**/assessments/${seeded.assessment.id}/bulk-evaluation-runs`,
    (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([run]) }),
  );
  await page.route("**/bulk-evaluation-runs/901/exceptions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          item_id: 44,
          submission_id: seeded.submission.id,
          student_identifier: "bulk-student-01",
          question_id: seeded.question.id,
          question_label: seeded.question.question_no,
          answer_region_id: seeded.answerRegionId,
          stage: "transcription",
          exception_codes: ["ambiguous_symbol"],
          warnings: ["Critical symbol needs teacher review"],
        },
      ]),
    }),
  );

  await page.goto(`/assessments/${seeded.assessment.id}/bulk-evaluation`);

  await expect(page.getByRole("heading", { name: "Upload once. Review exceptions first." })).toBeVisible();
  await expect(page.getByText("bulk-student-01", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Inspect manuscript" })).toBeVisible();
  await expect(page.getByText("Approved student answer evidence", { exact: false })).toHaveCount(0);
  await expect(page.getByText("Evidence Packet Preview", { exact: false })).toHaveCount(0);
  await expect(page.locator("img")).toHaveCount(0);
});
