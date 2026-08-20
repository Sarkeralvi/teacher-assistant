import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));

for (const file of [
  "lib/api.ts",
  "components/AppShell.tsx",
  "components/AssessmentDetailClient.tsx",
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
  "local Qwen3.8 vision",
  "Qwen3.8 is reading questions, solutions, and rubric",
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
  "Qwen3.8 visual evidence",
  "Create verbatim visual transcription",
  "Confirm faithful transcription",
  "Create answer region",
  "Confirm displayed image is the full answer",
  "This prepares evidence only. It does not grade.",
  "This only prepares a queue from confirmed evidence. It does not grade.",
]) {
  if (!assessment.includes(marker)) {
    throw new Error(`Assessment evidence UI missing marker: ${marker}`);
  }
}

// The PaddleOCR recognition stack and its endpoints were removed. Keep its UI from
// returning: these controls would call routes that no longer exist and 404 for a teacher.
for (const retired of [
  "Draft text with local PaddleOCR",
  "PaddleOCR evidence review",
  "Enhanced local OCR",
  "Confirm selected reading for every band",
  "createAnswerRegionOcrRun",
  "createAnswerRegionOcrRescueRun",
  "confirmAnswerRegionOcrCandidates",
  "getAnswerRegionOcrBandImageUrl",
]) {
  if (assessment.includes(retired)) {
    throw new Error(`Assessment evidence UI still exposes retired PaddleOCR surface: ${retired}`);
  }
  if (api.includes(retired)) {
    throw new Error(`API client still exposes retired PaddleOCR surface: ${retired}`);
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
