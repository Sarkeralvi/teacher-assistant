import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));

for (const file of [
  "lib/api.ts",
  "components/AppShell.tsx",
  "components/AssessmentDetailClient.tsx",
  "components/AuthenticatedMappedSourcePage.tsx",
  "components/AssessmentReviewClient.tsx",
  "components/CustomControlledGradingRunClient.tsx",
  "app/assessments/[assessmentId]/page.tsx",
  "app/assessments/[assessmentId]/review/page.tsx",
  "app/assessments/[assessmentId]/grading-run/page.tsx",
  "app/login/page.tsx",
  "app/register/page.tsx",
  "playwright.config.ts",
  "e2e/auth-smoke.spec.ts",
]) {
  if (!existsSync(join(root, file))) {
    throw new Error(`Missing required frontend workflow file: ${file}`);
  }
}

const packageJson = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
for (const [name, value] of [
  ["e2e", "playwright test"],
  ["e2e:headed", "playwright test --headed"],
]) {
  if (packageJson.scripts?.[name] !== value) {
    throw new Error(`Package script ${name} must equal ${value}`);
  }
}

const api = readFileSync(join(root, "lib/api.ts"), "utf8");
for (const symbol of [
  "getCurrentUser",
  "login",
  "register",
  "logout",
  "getAssessment",
  "createCustomGradingRun",
  "listAssessmentGradingRuns",
  "getGradingRun",
  "uploadGradingRunMaterials",
  "ReferenceExtraction",
  "ReferenceQuestionConfirmation",
  "startReferenceExtraction",
  "getReferenceExtraction",
  "confirmReferenceExtraction",
  "uploadSubmission",
  "uploadSubmissionZip",
  "createAnswerRegion",
  "createVisualTranscriptionRun",
  "confirmVisualTranscriptionRun",
  "confirmAnswerRegionFullAnswer",
  "createEvidencePrepRun",
  "createGradingQueueRun",
  "preflightCohortDispatch",
  "createCohortDispatch",
  "getAssessmentReviewQueue",
  "approveGradeSuggestion",
  "getAssessmentFinalGradesExportUrl",
]) {
  if (!api.includes(symbol)) {
    throw new Error(`API client missing ${symbol}`);
  }
}

for (const marker of ["token: getStoredAuthToken()", "authErrorMessage", "Could not reach backend"]) {
  if (!api.includes(marker)) {
    throw new Error(`API client missing auth/error marker: ${marker}`);
  }
}

const appShell = readFileSync(join(root, "components/AppShell.tsx"), "utf8");
for (const marker of ["Signed in as", "Dashboard", "Courses", "Logout", "Login", "Create account"]) {
  if (!appShell.includes(marker)) {
    throw new Error(`App shell missing navigation marker: ${marker}`);
  }
}
if (appShell.includes("Backend:")) {
  throw new Error("Teacher navigation must not expose backend implementation details");
}

const referencePage = readFileSync(
  join(root, "components/CustomControlledGradingRunClient.tsx"),
  "utf8",
);
for (const marker of [
  "Prepare grading references",
  "Upload the three reference PDFs",
  "Question paper",
  "Solution / model answer",
  "Rubric",
  "You do not need to upload the question paper anywhere else.",
  "Confirm files and extract drafts",
  "thinking-disabled Qwen3.8 vision task",
  "Confirm and extract drafts",
  "Review questions, model answers, and rubric",
  "Confirm grading references",
  "Continue to student evidence",
  "This screen cannot grade students, approve marks, or create final grades.",
  "No cloud provider or retry is allowed.",
  "startReferenceExtraction",
  "getReferenceExtraction",
  "confirmReferenceExtraction",
  "validateDrafts",
]) {
  if (!referencePage.includes(marker)) {
    throw new Error(`Reference preparation UI missing marker: ${marker}`);
  }
}

if (referencePage.includes("localAi.paddle_ocr.enabled")) {
  throw new Error("Qwen3.8 reference extraction must not depend on retired PaddleOCR");
}
for (const marker of [
  "localAi.qwen38.available",
  "localAi.qwen38.visual_preparation_enabled",
]) {
  if (!referencePage.includes(marker)) {
    throw new Error(`Reference preparation readiness is missing Qwen3.8 marker: ${marker}`);
  }
}

for (const obsolete of [
  "Start custom controlled run",
  "Upload/confirm materials",
  "Functional V0 workflow dashboard",
  "Bulk mock grade ungraded answers",
  "Current status and marking policy",
]) {
  if (referencePage.includes(obsolete)) {
    throw new Error(`Reference preparation UI still exposes obsolete control: ${obsolete}`);
  }
}

const assessment = readFileSync(join(root, "components/AssessmentDetailClient.tsx"), "utf8");
for (const marker of [
  "Assessment workspace",
  "Prepare references",
  "NEXT_PUBLIC_SHOW_LEGACY_REFERENCE_TOOLS",
  "Manual reference editing (advanced)",
  "Upload submission",
  "Upload script ZIP",
  "Qwen3.8 visual mapping and grading",
  "AuthenticatedAnswerRegionImage",
  "AuthenticatedAnswerRegionSegmentImage",
  "Loading every source page and answer segment...",
  "Repair unconfirmed boundaries with Qwen3.8 vision",
  "Prepare submission #",
  "Existing submissions and approved grades were not changed.",
  "Confirmed mappings are protected.",
  "Required: compare the crop boundary with the complete source page",
  "open={!mapping.teacher_confirmed || sourceSegments.length > 1}",
  "Compare and acknowledge the full-page boundary first",
  "Complete prepared answer",
  "Review every segment below in order.",
  "Incomplete mapping suspected",
  "Transcribe visible answer evidence with Qwen3.8 vision",
  "Confirm this final transcription",
  "preserves visible student writing",
  "repairs the mathematics",
  "Possible edits were detected.",
  "thinking_repair_required",
  "Unclear correction detected.",
  "Re-transcribe with evidence-preserving rules",
  "Re-run evidence-preserving transcription",
  "safeVisualTranscriptionError",
  "older combined transcription/cancellation policy",
  "cannot replace confirmed evidence and creates no transcript or grade",
  "!finalizedRegionIds.has(mapping.answer_region_id)",
  "Finalize surviving work with Qwen3.8 Thinking",
  "qwen38-final-intent-thinking-repair-v9",
  "Start corrected Thinking repair",
  "Failure category:",
  "no question, solution, rubric, or marks were provided",
  "Required: confirm each image-grounded editing decision",
  "Discard Thinking alternative",
  "Unresolved edits or uncertain surviving glyphs fail closed",
  "thinking_repair_enabled",
  "Grade all approved transcriptions",
  "Server ceiling: 25 calls",
  "Create answer region",
  "Confirm displayed image is the full answer",
  "This prepares evidence only. It does not grade.",
  "This only prepares a queue from confirmed evidence. It does not grade.",
]) {
  if (!assessment.includes(marker)) {
    throw new Error(`Assessment evidence UI missing marker: ${marker}`);
  }
}

const reviewTotals = readFileSync(join(root, "components/AssessmentReviewClient.tsx"), "utf8");
for (const marker of [
  "Submission totals",
  "Totals use teacher-approved grades only.",
  "Approved total",
  "Incomplete",
]) {
  if (!reviewTotals.includes(marker)) {
    throw new Error(`Assessment review UI missing total marker: ${marker}`);
  }
}

// Every Paddle transcription and candidate surface is retired from the active
// teacher workflow. Qwen3.8 handles mapping, verbatim transcription, and draft
// grading as three separately authorized calls.
for (const retired of [
  "Draft text with local PaddleOCR",
  "PaddleOCR evidence review",
  "Enhanced local OCR",
  "Confirm selected reading for every band",
  "createAnswerRegionOcrRescueRun",
  "confirmAnswerRegionOcrCandidates",
  "getAnswerRegionOcrBandImageUrl",
  "createPaddleOcrRun",
  "confirmPaddleOcrRun",
  "rejectPaddleOcrRun",
]) {
  if (assessment.includes(retired)) {
    throw new Error(`Assessment evidence UI still exposes retired PaddleOCR surface: ${retired}`);
  }
  if (api.includes(retired)) {
    throw new Error(`API client still exposes retired PaddleOCR surface: ${retired}`);
  }
}

for (const marker of [
  '"local_qwen38_visual"',
  'provider: "llama_cpp_qwen38"',
  "gradeAnswerRegionWithLocalQwen38",
  "gradeAllApprovedAnswersWithLocalQwen38",
  "/grade-local-qwen38",
  "/grade-approved-local-qwen38",
  "getAnswerRegionSegmentImageUrl",
]) {
  if (!api.includes(marker)) {
    throw new Error(`API client missing active Qwen3.8 workflow marker: ${marker}`);
  }
}

for (const marker of [
  "Repair submission #",
  "boundaries with Qwen3.8 vision",
  "no transcription or grade was created",
  "localVisualMappingAuthorized",
]) {
  if (!assessment.includes(marker)) {
    throw new Error(`Assessment UI missing explicit visual boundary rescue marker: ${marker}`);
  }
}

const review = readFileSync(join(root, "components/AssessmentReviewClient.tsx"), "utf8");
for (const marker of [
  "Review local Qwen draft grades",
  "Every score here is a review-required draft.",
  "Approve AI suggestion",
  "Edit score and save final grade",
  "Reject suggestion",
  "Export approved grades (.xlsx)",
  "This draft used an older grading policy",
  "Grading prompt:",
]) {
  if (!review.includes(marker)) {
    throw new Error(`Teacher review UI missing marker: ${marker}`);
  }
}

const browserUi = `${referencePage}\n${assessment}\n${review}`;
if (/fetch\([^)]*(openai|codex|llm|chat\/completions)/i.test(browserUi)) {
  throw new Error("Frontend must never call an AI provider directly");
}

console.log("frontend workflow static checks passed");
