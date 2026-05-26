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
  "app/dashboard/page.tsx",
  "app/users/page.tsx",
  "app/courses/page.tsx",
  "app/courses/[courseId]/page.tsx",
  "app/assessments/[assessmentId]/page.tsx",
  "app/assessments/[assessmentId]/review/page.tsx",
  "app/questions/[questionId]/page.tsx",
];

for (const file of requiredFiles) {
  if (!existsSync(join(root, file))) {
    throw new Error(`Missing required frontend workflow file: ${file}`);
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
  "listSubmissions",
  "getSubmissionPageImageUrl",
  "createAnswerRegion",
  "listSubmissionAnswerRegions",
  "listAssessmentAnswerRegions",
  "getAnswerRegionImageUrl",
  "gradeAnswerRegion",
  "approveGradeSuggestion",
  "editGradeSuggestion",
  "rejectGradeSuggestion",
  "finalizeGradeSuggestion",
  "getAnswerRegionFinalGrade",
  "getAssessmentReviewQueue",
  "getAssessmentSummary",
  "getAssessmentFinalGradesExportUrl",
  "AssessmentSummary",
  "GradeSuggestion",
  "FinalGrade",
  "ReviewQueueItem",
]) {
  if (!api.includes(`export`) || !api.includes(symbol)) {
    throw new Error(`API client missing ${symbol}`);
  }
}

const dashboard = readFileSync(join(root, "app/dashboard/page.tsx"), "utf8");
if (!dashboard.includes("Users / teacher setup") || !dashboard.includes("Courses")) {
  throw new Error("Dashboard must link to users and courses workflow pages");
}

const assessmentDetail = readFileSync(join(root, "components/AssessmentDetailClient.tsx"), "utf8");
for (const text of [
  "Upload submission",
  "student_identifier",
  "Submissions",
  "Pages",
  "Answer regions",
  "Select page",
  "Select question",
  "Crop coordinates",
  "Create answer region",
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
]) {
  if (!assessmentDetail.includes(text)) {
    throw new Error(`Assessment detail must include upload/answer-region UI marker: ${text}`);
  }
}

const assessmentReview = readFileSync(join(root, "components/AssessmentReviewClient.tsx"), "utf8");
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
  "approveGradeSuggestion",
  "editGradeSuggestion",
  "rejectGradeSuggestion",
  "getAssessmentSummary",
  "getAssessmentFinalGradesExportUrl",
]) {
  if (!assessmentReview.includes(text)) {
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

console.log("frontend workflow static checks passed");
