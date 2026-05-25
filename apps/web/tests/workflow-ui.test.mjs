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
  "components/QuestionDetailClient.tsx",
  "app/dashboard/page.tsx",
  "app/users/page.tsx",
  "app/courses/page.tsx",
  "app/courses/[courseId]/page.tsx",
  "app/assessments/[assessmentId]/page.tsx",
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
]) {
  if (!api.includes(`export`) || !api.includes(symbol)) {
    throw new Error(`API client missing ${symbol}`);
  }
}

const dashboard = readFileSync(join(root, "app/dashboard/page.tsx"), "utf8");
if (!dashboard.includes("Users / teacher setup") || !dashboard.includes("Courses")) {
  throw new Error("Dashboard must link to users and courses workflow pages");
}

console.log("frontend workflow static checks passed");
