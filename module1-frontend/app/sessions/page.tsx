"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Session } from "@/lib/types";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function canCheckIn(session: Session): boolean {
  const now = new Date();
  const opens = new Date(session.checkin_opens_at);
  const closes = new Date(session.checkin_closes_at);
  return session.status === "active" && now >= opens && now <= closes;
}

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadSessions() {
      try {
        const { data } = await api.get<Session[]>("/sessions/my-sessions");
        setSessions(data);
      } catch (err: any) {
        setError(err?.response?.data?.detail ?? "Failed to load sessions.");
      } finally {
        setLoading(false);
      }
    }
    loadSessions();
  }, []);

  if (loading) return <main className="p-8">Loading sessions...</main>;

  return (
    <main className="min-h-screen p-8">
      <h1 className="text-2xl font-bold mb-6">Your Sessions</h1>

      {error && <div className="alert-error">{error}</div>}

      <div className="space-y-4">
        {sessions.map((session) => (
          <div key={session.id} className="card-panel !max-w-none">
            <p className="text-sm text-gray-500">{session.course_code}</p>
            <h2 className="text-lg font-semibold">{session.course_name}</h2>
            <p className="text-sm text-gray-600 mt-1">
              {session.name} · {formatTime(session.scheduled_start)}–{formatTime(session.scheduled_end)}
            </p>
            <p className="text-sm text-gray-600">{session.venue_name}</p>

            <button
              className="btn-primary mt-4"
              disabled={!canCheckIn(session)}
              onClick={() => alert("Check-in flow not built yet")}
            >
              {canCheckIn(session) ? "Check In" : session.status}
            </button>
          </div>
        ))}

        {sessions.length === 0 && (
          <p className="text-gray-500">No sessions found.</p>
        )}
      </div>
    </main>
  );
}