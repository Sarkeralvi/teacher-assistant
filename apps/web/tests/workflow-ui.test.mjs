import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;

const requiredFiles = [
  "lib/api.ts",
  "components/AppShell.tsx",
  "components/UsersClient.tsx",
  "components/CoursesClient.tsx",
  "components/CourseDetailClient.tsx",
  "components/AssessmentDetailClient.tsx",
  "components/AssessmentReviewClient.tsx",
  "components/QuestionDetailClient.tsx",
  "components/CustomControlledGradingRunClient.tsx",
  "app/dashboard/page.tsx",
  "app/users/page.tsx",
  "app/courses/page.tsx",
  "app/courses/[courseId]/page.tsx",
  "app/assessments/[assessmentId]/page.tsx",
  "app/assessments/[assessmentId]/review/page.tsx",
  "app/assessments/[assessmentId]/grading-run/page.tsx",
  "app/login/page.tsx",
  "app/register/page.tsx",
  "app/questions/[questionId]/page.tsx",
  "playwright.config.ts",
  "e2e/support.ts",
  "e2e/auth-smoke.spec.ts",
  "e2e/custom-controlled-mock.spec.ts",
];

for (const file of requiredFiles) {
  if (!existsSync(join(root, file))) {
    throw new Error(`Missing required frontend workflow file: ${file}`);
  }
}

const packageJson = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
for (const [scriptName, scriptValue] of [
  ["e2e", "playwright test"],
  ["e2e:headed", "playwright test --headed"],
]) {
  if (packageJson.scripts?.[scriptName] !== scriptValue) {
    throw new Error(`Package script ${scriptName} must equal ${scriptValue}`);
  }
}

const api = readFileSync(join(root, "lib/api.ts"), "utf8");
for (const symbol of [
  "API_BASE_URL",
  "createUser",
  "listUsers",
  "createCourse",
  "listCourses",
  "getCourse",
  "createAssessment",
  "listAssessments",
  "getAssessment",
  "createQuestion",
  "listQuestions",
  "getQuestion",
  "createRubric",
  "listRubrics",
  "uploadSubmission",
  "uploadSubmissionZip",
  "SubmissionZipUploadResponse",
  "listSubmissions",
  "getSubmissionPageImageUrl",
  "createAnswerRegion",
  "listSubmissionAnswerRegions",
  "listAssessmentAnswerRegions",
  "getAnswerRegionImageUrl",
  "gradeAnswerRegion",
  "gradeAnswerRegionWithCodexDev",
  "BrowserCodexGradeResponse",
  "approveGradeSuggestion",
  "editGradeSuggestion",
  "rejectGradeSuggestion",
  "finalizeGradeSuggestion",
  "getAnswerRegionFinalGrade",
  "getAssessmentReviewQueue",
  "getAssessmentSummary",
  "getAssessmentFinalGradesExportUrl",
  "batchMockGradeAssessment",
  "approveSelectedFinalGrades",
  "BatchMockGradeResponse",
  "BatchApproveFinalGradesResponse",
  "QuestionImportJob",
  "DraftQuestion",
  "importQuestionsFromPaper",
  "getQuestionImportJob",
  "acceptQuestionImportDrafts",
  "QuestionImportAcceptResponse",
  "QuestionImportProvider",
  "deleteSubmission",
  "logout",
  "getStoredAuthToken",
  "setStoredAuthToken",
  "getCurrentUser",
  "login",
  "register",
  "Authorization",
  "createAuthenticatedCourse",
  "AssessmentSummary",
  "GradeSuggestion",
  "FinalGrade",
  "ReviewQueueItem",
  "GradingRun",
  "createCustomGradingRun",
  "listAssessmentGradingRuns",
  "getGradingRun",
  "updateGradingRun",
  "confirmGradingRunMaterials",
  "confirmGradingRunQuestionsRubrics",
  "gradeGradingRunReadyRegionsMock",
  "GradingRunWorkflowState",
  "MarkingPolicy",
  "marking_policy",
]) {
  if (!api.includes(`export`) || !api.includes(symbol)) {
    throw new Error(`API client missing ${symbol}`);
  }
}

const appShell = readFileSync(join(root, "components/AppShell.tsx"), "utf8");
for (const text of ["Current teacher", "Logout", "Login", "Register", "getCurrentUser", "logout"]) {
  if (!appShell.includes(text)) {
    throw new Error(`App shell must include auth navigation marker: ${text}`);
  }
}

const loginPage = readFileSync(join(root, "app/login/page.tsx"), "utf8");
for (const text of [
  "Login",
  "email",
  "password",
  "login(",
  "setStoredAuthToken",
  "localStorage",
  "dev-only",
  'data-testid="login-form"',
  'data-testid="login-email-input"',
  'data-testid="login-password-input"',
  'data-testid="login-submit-button"',
]) {
  if (!loginPage.includes(text)) {
    throw new Error(`Login page must include auth marker: ${text}`);
  }
}

const registerPage = readFileSync(join(root, "app/register/page.tsx"), "utf8");
for (const text of [
  "Register",
  "name",
  "email",
  "password",
  "register(",
  "setStoredAuthToken",
  "localStorage",
  "dev-only",
  'data-testid="register-form"',
  'data-testid="register-name-input"',
  'data-testid="register-email-input"',
  'data-testid="register-password-input"',
  'data-testid="register-submit-button"',
]) {
  if (!registerPage.includes(text)) {
    throw new Error(`Register page must include auth marker: ${text}`);
  }
}

const dashboard = readFileSync(join(root, "app/dashboard/page.tsx"), "utf8");
if (!dashboard.includes("Users / teacher setup") || !dashboard.includes("Courses")) {
  throw new Error("Dashboard must link to users and courses workflow pages");
}

const demoTeacherSelector = readFileSync(join(root, "components/DemoTeacherSelector.tsx"), "utf8");
const assessmentDetail = readFileSync(join(root, "components/AssessmentDetailClient.tsx"), "utf8");
const assessmentDetailUi = assessmentDetail + demoTeacherSelector;
for (const text of [
  "Upload script ZIP",
  "PDF, PNG, JPG, JPEG only.",
  "ZIP import summary",
  "imported_count",
  "skipped_count",
  "failed_count",
  "uploadSubmissionZip",
  "zipUploadResult",
  "Upload submission",
  "student_identifier",
  "Choose a PDF or image file before uploading",
  "handleSubmissionFileChange",
  "selectedUploadFileName",
  "uploadFormRef",
  "accept=\".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg\"",
  "disabled={uploading || !studentIdentifier.trim() || !submissionFile}",
  "Create a question before mapping answer regions.",
  "Upload failed:",
  "Review & export final grades",
  "Download final grades (.xlsx)",
  "getAssessmentFinalGradesExportUrl(assessmentId)",
  "href={`/assessments/${assessmentId}/review`}",
  "Submissions",
  "Pages",
  "Answer regions",
  "Select page",
  "Select question",
  "Crop coordinates",
  "Create answer region",
  "Suggest answer regions",
  "Suggestion provider",
  "Codex-backed suggestions (backend flag required)",
  "Mock provider is default. Codex-backed suggestions require CODEX_ANSWER_REGION_SUGGESTIONS_ENABLED=true and backend image input enabled.",
  "Provider warnings",
  "AI suggestions are drafts. Teacher must confirm before grading.",
  "Accept suggestion",
  "Ignore",
  "needs review",
  "Cropped image",
  "Teacher review queue",
  "Mock Grade",
  "MOCK suggestion",
  "Rubric breakdown",
  "Final score",
  "Teacher comment",
  "Finalize as approved",
  "Finalize as edited",
  "Finalize as rejected",
  "Select a demo teacher first.",
  "Current demo teacher",
  "Delete this submission? This is for demo cleanup only.",
  "Codex CLI provider is integrated in backend, but this demo button uses mock grading for safe local testing.",
  "Import questions from paper",
  "Draft extraction. Teacher review required.",
  "Default extraction is mock/simple.",
  "Real Codex extraction must be explicitly enabled.",
  "If real extraction is not enabled, uploaded images will not be treated as understood question papers.",
  "Question paper file",
  "handleQuestionImportFileChange",
  "selectedQuestionImportFileName",
  "importQuestionsFromPaper(assessmentId, selectedFile)",
  "Create selected questions",
  "acceptQuestionImportDrafts",
  "Manual question creation remains available",
  "draftQuestionEdits",
  "Custom Controlled Grading Run",
  "Semi-Automated: not ready for teacher workflow yet",
  'data-testid="semi-automated-mode-not-ready"',
  "Grading run modes require teacher confirmation before export.",
  "href={`/assessments/${assessmentId}/grading-run`}",
]) {
  if (!assessmentDetailUi.includes(text)) {
    throw new Error(`Assessment detail must include upload/answer-region UI marker: ${text}`);
  }
}


const gradingRunPage = readFileSync(join(root, "app/assessments/[assessmentId]/grading-run/page.tsx"), "utf8");
const gradingRunClient = readFileSync(join(root, "components/CustomControlledGradingRunClient.tsx"), "utf8");
const gradingRunUi = gradingRunPage + gradingRunClient;
for (const text of [
  "Custom Controlled Grading Run",
  "Mode unavailable",
  'data-testid="grading-mode-unavailable"',
  "Custom controlled mode: teacher confirmation required.",
  "Start custom controlled run",
  "Upload/confirm materials",
  "Question PDF",
  "Solution/model answer PDF",
  "Rubric PDF",
  "Confirm or create questions/rubrics",
  "Upload scripts",
  "Create answer regions manually",
  "Run mock batch grading",
  "Review suggestions",
  "Approve selected / export",
  "No automatic answer-region detection",
  "No real Codex batch grading by default",
  "createCustomGradingRun(assessmentId",
  "uploadGradingRunMaterials",
  "listAssessmentGradingRuns",
  "updateGradingRun",
  "href={`/assessments/${assessmentId}`}",
  "href={`/assessments/${assessmentId}/review`}",
  "getAssessmentFinalGradesExportUrl(assessmentId)",
  "Functional V0 workflow dashboard",
  "Workflow blockers",
  "Next actions",
  "Materials confirmed",
  "Questions/rubrics confirmed",
  "Scripts uploaded",
  "Answer regions created",
  "Grading readiness",
  "Review readiness",
  "Export readiness",
  "Confirm uploaded materials",
  "Confirm questions/rubrics",
  "Bulk mock grade ungraded answers",
  "Current status and marking policy",
  "Marking policy selector",
  "Tough",
  "General",
  "Easy",
  "Tough: stricter",
  "General: normal",
  "Easy: more lenient",
  "marking_policy: markingPolicy",
  "Mock grading only. Real Codex batch grading is not enabled.",
  "Review queue",
  "Bulk mock grading result",
  "confirmGradingRunMaterials",
  "confirmGradingRunQuestionsRubrics",
  "gradeGradingRunReadyRegionsMock",
]) {
  if (!gradingRunUi.includes(text)) {
    throw new Error(`Custom controlled grading-run UI missing marker: ${text}`);
  }
}

for (const forbidden of ["openai", "anthropic", "gemini", "codex exec", "/grade-all-codex"]) {
  if (gradingRunUi.toLowerCase().includes(forbidden)) {
    throw new Error(`Custom controlled wizard must not include direct LLM/Codex marker: ${forbidden}`);
  }
}

const assessmentReview = readFileSync(join(root, "components/AssessmentReviewClient.tsx"), "utf8");
const assessmentReviewUi = assessmentReview + demoTeacherSelector;
for (const text of [
  "Teacher review and final grade approval",
  "AI GradeSuggestions are suggestions only",
  "answer region image",
  "Question text",
  "student_identifier",
  "AI suggested score",
  "confidence",
  "needs_review",
  "Rubric breakdown",
  "feedback",
  "Current FinalGrade",
  "Approve AI suggestion",
  "Edit score and save final grade",
  "Reject suggestion",
  "Assessment summary",
  "Reviewed",
  "Pending review",
  "Export final grades (.xlsx)",
  "Download final grades (.xlsx)",
  "Approve or edit at least one grade before export is useful.",
  "batchMockGradeAssessment(assessmentId)",
  "approveSelectedFinalGrades(assessmentId, {",
  "Batch mock grade ungraded answers",
  "Batch mock grading only. No real Codex batch calls.",
  "If this app is connected to the Docker backend, Codex is unavailable because that runtime is mock-only and does not include Codex CLI.",
  "Real Codex grade this answer",
  "Runs one real Codex CLI call through POST /answer-regions/{item.answer_region.id}/grade-codex-dev on the backend. Use only for controlled testing. Teacher review required.",
  "Docker backend/mock-only mode cannot run this; use host-backend Codex dev mode.",
  "gradeAnswerRegionWithCodexDev",
  "batchResult",
  "graded_count",
  "skipped_count",
  "failed_count",
  "statusFilter",
  "Review queue filter",
  "All statuses",
  "ungraded",
  "suggested",
  "finalized",
  "approved",
  "edited",
  "rejected",
  "filteredItems",
  "getStatusCounts",
  "getAssessmentFinalGradesExportUrl(assessmentId)",
  "summary.total_final_grades === 0",
  "approveGradeSuggestion",
  "editGradeSuggestion",
  "rejectGradeSuggestion",
  "getAssessmentSummary",
  "getAssessmentFinalGradesExportUrl",
  "getCurrentUser",
  "currentUser",
  "Login to approve or edit final grades",
  "Logged-in teacher is used for approve/edit/reject.",
  "approveGradeSuggestion(item.latest_grade_suggestion.id, {",
  "editGradeSuggestion(item.latest_grade_suggestion.id, {",
  "rejectGradeSuggestion(item.latest_grade_suggestion.id, {",
  "Batch grading uses mock only. The per-answer Real Codex button calls the backend dev endpoint and only works when the backend is host/WSL Codex mode.",
  "Review item overview",
  "Status label",
  "AI/mock score",
  "Final score if finalized",
  "Open cropped answer image",
  "Quick actions",
  "No items in this filter",
  "Next: upload submissions → create answer regions → batch mock grade → review → export",
  "Next item to review",
  "Needs teacher review",
  "Mock score",
  "Marking policy used",
  "suggestion.marking_policy",
  "Select all visible suggested items",
  "Clear selection",
  "Approve selected",
  "selectedSuggestionIds",
  "selected count",
  "Select at least one suggested item to approve.",
  "No visible suggested items can be selected in this filter.",
  "Batch final-grade approval result",
  "requested_count",
  "approved_count",
]) {
  if (!assessmentReviewUi.includes(text)) {
    throw new Error(`Assessment review page must include teacher-review UI marker: ${text}`);
  }
}

const questionDetail = readFileSync(join(root, "components/QuestionDetailClient.tsx"), "utf8");
for (const text of [
  "Total marks",
  "Add criterion",
  "Remove criterion",
  "Criterion ID",
  "Criterion name",
  "Criterion description",
  "Criterion max marks",
  "Criteria marks sum",
  "Raw JSON preview",
]) {
  if (!questionDetail.includes(text)) {
    throw new Error(`Question detail must include rubric editor UI marker: ${text}`);
  }
}

const usersClient = readFileSync(join(root, "components/UsersClient.tsx"), "utf8") + demoTeacherSelector;
for (const text of ["Set as current demo teacher", "Current demo teacher", "localStorage"]) {
  if (!usersClient.includes(text)) {
    throw new Error(`Users page must include demo teacher selector marker: ${text}`);
  }
}

const coursesClient = readFileSync(join(root, "components/CoursesClient.tsx"), "utf8") + demoTeacherSelector;
for (const text of ["Login to create courses", "currentUser", "createAuthenticatedCourse", "No raw teacher_id is needed for logged-in teachers."]) {
  if (!coursesClient.includes(text)) {
    throw new Error(`Courses page must use selected demo teacher marker: ${text}`);
  }
}

if (assessmentDetailUi.includes("grading-run?mode=semi_automated") || assessmentDetailUi.includes("grading-run?mode=fully_automated")) {
  throw new Error("Assessment detail must not expose semi/fully automated grading links in the normal teacher workflow");
}

if (/fetch\([^)]*(openai|codex|llm|chat\/completions)/i.test(assessmentDetail + assessmentReview)) {
  throw new Error("Frontend must not make direct LLM/Codex provider calls");
}

const reviewClientForCodex = readFileSync(join(root, "components/AssessmentReviewClient.tsx"), "utf8");
for (const text of [
  "Real Codex grade this answer",
  "Runs one real Codex CLI call through POST /answer-regions/{item.answer_region.id}/grade-codex-dev on the backend. Use only for controlled testing. Teacher review required.",
  "Docker backend/mock-only mode cannot run this; use host-backend Codex dev mode.",
  "gradeAnswerRegionWithCodexDev",
  "realCodexRegionId",
  "setError(err instanceof Error ? err.message : \"Failed to run real Codex smoke grading\")",
]) {
  if (!reviewClientForCodex.includes(text)) {
    throw new Error(`Review UI missing browser Codex smoke marker: ${text}`);
  }
}
if (reviewClientForCodex.includes("codex exec") || reviewClientForCodex.includes("CodexCliProvider")) {
  throw new Error("Frontend must not call Codex/LLM directly");
}

console.log("frontend workflow static checks passed");