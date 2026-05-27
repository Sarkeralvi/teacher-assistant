"use client";

import { useEffect, useState } from "react";

import { listUsers, type User } from "../lib/api";
import {
  clearDemoTeacherId,
  findSelectedDemoTeacher,
  formatDemoTeacher,
  readDemoTeacherId,
  writeDemoTeacherId,
  type DemoTeacher,
} from "../lib/demoTeacher";
import { buttonClass, inputClass } from "./AppShell";

type Props = Readonly<{
  onTeacherChange?: (teacher: DemoTeacher | null) => void;
}>;

export function DemoTeacherSelector({ onTeacherChange }: Props) {
  const [users, setUsers] = useState<User[]>([]);
  const [selectedTeacherId, setSelectedTeacherId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const selectedTeacher = findSelectedDemoTeacher(users, selectedTeacherId);
  const teacherUsers = users.filter((user) => user.role === "teacher");

  useEffect(() => {
    async function loadTeachers() {
      setLoading(true);
      setError(null);
      try {
        const userData = await listUsers();
        const storedId = readDemoTeacherId();
        setUsers(userData);
        setSelectedTeacherId(storedId);
        onTeacherChange?.(findSelectedDemoTeacher(userData, storedId));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load demo teachers");
      } finally {
        setLoading(false);
      }
    }
    void loadTeachers();
  }, [onTeacherChange]);

  function handleSelect(value: string) {
    if (!value) {
      clearDemoTeacherId();
      setSelectedTeacherId(null);
      onTeacherChange?.(null);
      return;
    }
    const teacherId = Number(value);
    writeDemoTeacherId(teacherId);
    setSelectedTeacherId(teacherId);
    onTeacherChange?.(findSelectedDemoTeacher(users, teacherId));
  }

  return (
    <section className="grid gap-3 rounded border border-cyan-900 bg-cyan-950/20 p-4">
      <div>
        <h2 className="text-lg font-semibold">Current demo teacher</h2>
        <p className="text-sm text-slate-300">{formatDemoTeacher(selectedTeacher)}</p>
        {!selectedTeacher ? <p className="text-sm text-amber-200">Select a demo teacher first.</p> : null}
      </div>
      <label className="grid gap-2 text-sm">
        Select existing teacher
        <select
          className={inputClass}
          value={selectedTeacherId ?? ""}
          onChange={(event) => handleSelect(event.target.value)}
          disabled={loading}
        >
          <option value="">Select a demo teacher first.</option>
          {teacherUsers.map((user) => (
            <option key={user.id} value={user.id}>
              {user.name} · {user.email} · teacher_id: {user.id}
            </option>
          ))}
        </select>
      </label>
      {error ? <p className="text-sm text-red-300">{error}</p> : null}
      {teacherUsers.length === 0 && !loading ? (
        <p className="text-sm text-slate-400">Create a teacher on the Users page, then select it here.</p>
      ) : null}
    </section>
  );
}

export function SetDemoTeacherButton({ user, onSelected }: Readonly<{ user: User; onSelected?: () => void }>) {
  return (
    <button
      className={buttonClass}
      type="button"
      onClick={() => {
        writeDemoTeacherId(user.id);
        onSelected?.();
      }}
    >
      Set as current demo teacher
    </button>
  );
}
