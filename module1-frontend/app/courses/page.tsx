"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { AppShell } from "@/components/ui/layout/AppShell";
import type { Enrollment } from "@/lib/types";

export default function CoursesPage() {
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadEnrollments() {
      try {
        const { data } = await api.get<Enrollment[]>("/enrollments/my-enrollments");
        setEnrollments(data);
      } catch (err: any) {
        setError(err?.response?.data?.detail ?? "Failed to load courses.");
      } finally {
        setLoading(false);
      }
    }
    loadEnrollments();
  }, []);

  return (
    <AppShell>
      <h1 className="text-2xl font-bold mb-6">Courses</h1>

      {error && <div className="alert-error">{error}</div>}
      {loading && <p className="text-gray-500">Loading courses...</p>}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {enrollments.map((enrollment) => (
          <div key={enrollment.id} className="card-panel !max-w-none">
            <p className="text-sm text-gray-500">{enrollment.course_code}</p>
            <h2 className="text-lg font-semibold">{enrollment.course_name}</h2>
            <p className="text-sm text-gray-600 mt-1">{enrollment.semester}</p>
            <p className="text-sm text-gray-600">
              Instructor: {enrollment.instructor_name}
            </p>
            {!enrollment.is_active && (
              <p className="text-xs text-red-500 mt-2">Enrollment inactive</p>
            )}
          </div>
        ))}

        {!loading && enrollments.length === 0 && (
          <p className="text-gray-500">You're not enrolled in any courses.</p>
        )}
      </div>
    </AppShell>
  );
}