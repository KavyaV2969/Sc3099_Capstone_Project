"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { AppShell } from "@/components/ui/layout/AppShell";
import type { Checkin } from "@/lib/types";

const statusStyle: Record<string, string> = {
  approved: "bg-green-100 text-green-700",
  flagged: "bg-yellow-100 text-yellow-800",
  rejected: "bg-red-100 text-red-700",
  appealed: "bg-blue-100 text-blue-700",
};

export default function CourseCheckinsPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [checkins, setCheckins] = useState<Checkin[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const { data } = await api.get<Checkin[]>("/checkins/my-checkins", {
          params: { course_id: courseId },
        });
        setCheckins(data);
      } catch (err: any) {
        const detail = err?.response?.data?.detail;
        setError(typeof detail === "string" ? detail : "Failed to load your check-ins.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [courseId]);

  return (
    <AppShell>
      <div className="flex justify-center">
        <div className="max-w-md w-full">
          <Link href="/courses" className="text-sm text-blue-600 underline">
            ← Back to courses
          </Link>
          <h1 className="text-2xl font-bold mt-3 mb-6">
            {checkins[0]?.course_code ?? "Course"} check-ins
          </h1>

          {error && <div className="alert-error">{error}</div>}
          {loading && <p className="text-gray-500">Loading...</p>}

          {!loading && !error && checkins.length === 0 && (
            <p className="text-gray-500">You haven&apos;t checked in to this course yet.</p>
          )}

          {checkins.map((c) => (
            <Link
              key={c.id}
              href={`/courses/${courseId}/checkins/${c.id}`}
              className="card-panel !max-w-none mb-3 block hover:shadow-md transition-shadow"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-semibold">{c.session_name ?? "Session"}</span>
                <span
                  className={`text-xs rounded-full px-2 py-0.5 capitalize ${
                    statusStyle[c.status] ?? "bg-gray-100 text-gray-700"
                  }`}
                >
                  {c.status}
                </span>
              </div>
              <p className="text-sm text-gray-500">
                {new Date(c.checked_in_at).toLocaleString()}
              </p>
            </Link>
          ))}
        </div>
      </div>
    </AppShell>
  );
}