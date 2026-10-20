"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { cachedGet } from "@/lib/offlineData";
import { warmRoutes } from "@/lib/offlineStore";
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
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const { data, stale } = await cachedGet<Checkin[]>("/checkins/my-checkins", {
          course_id: courseId,
        });
        setCheckins(data);
        setOffline(stale);
        if (!stale) {
          // Online: save each check-in page and its details for offline use
          warmRoutes(data.map((c) => `/courses/${courseId}/checkins/${c.id}`));
          data.forEach((c) => cachedGet(`/checkins/${c.id}`).catch(() => {}));
        }
      } catch (err: any) {
        const detail = err?.response?.data?.detail;
        setError(
          !err?.response
            ? "You're offline, and this page has no saved data yet."
            : typeof detail === "string"
            ? detail
            : "Failed to load your check-ins."
        );
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
          {offline && (
            <div className="bg-yellow-100 border-l-4 border-yellow-500 text-yellow-800 p-3 text-sm mb-4">
              You&apos;re offline. Showing saved data.
            </div>
          )}
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