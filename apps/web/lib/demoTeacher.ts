import { type User } from "./api";

export const DEMO_TEACHER_STORAGE_KEY = "teacher-assistant.demoTeacherId";

export type DemoTeacher = Pick<User, "id" | "name" | "email" | "role">;

export function readDemoTeacherId(): number | null {
  if (typeof window === "undefined") {
    return null;
  }
  const stored = window.localStorage.getItem(DEMO_TEACHER_STORAGE_KEY);
  if (!stored) {
    return null;
  }
  const parsed = Number(stored);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function writeDemoTeacherId(teacherId: number) {
  window.localStorage.setItem(DEMO_TEACHER_STORAGE_KEY, String(teacherId));
}

export function clearDemoTeacherId() {
  window.localStorage.removeItem(DEMO_TEACHER_STORAGE_KEY);
}

export function findSelectedDemoTeacher(users: User[], teacherId: number | null): DemoTeacher | null {
  if (!teacherId) {
    return null;
  }
  return users.find((user) => user.id === teacherId && user.role === "teacher") ?? null;
}

export function formatDemoTeacher(teacher: DemoTeacher | null): string {
  if (!teacher) {
    return "No demo teacher selected";
  }
  return `${teacher.name} (${teacher.email}) · teacher_id: ${teacher.id}`;
}
