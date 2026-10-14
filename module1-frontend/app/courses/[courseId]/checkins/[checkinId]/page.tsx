"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { AppShell } from "@/components/ui/layout/AppShell";
import type { Checkin } from "@/lib/types";

const statusStyle: Record<string, string> = {
  approved: "bg-green-100 border-green-500 text-green-700",
  flagged: "bg-yellow-100 border-yellow-500 text-yellow-800",
  rejected: "bg-red-100 border-red-500 text-red-700",
  appealed: "bg-blue-100 border-blue-500 text-blue-700",
};

const APPEAL_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;

function errorText(err: any, fallback: string): string {
  const detail = err?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

export default function CheckinDetailPage() {
  const { courseId, checkinId } = useParams<{ courseId: string; checkinId: string }>();
  const [checkin, setCheckin] = useState<Checkin | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const { data } = await api.get<Checkin>(`/checkins/${checkinId}`);
        setCheckin(data);
      } catch (err: any) {
        setError(errorText(err, "Failed to load this check-in."));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [checkinId]);

  const canAppeal =
    !!checkin &&
    (checkin.status === "flagged" || checkin.status === "rejected") &&
    !checkin.appealed_at &&
    Date.now() - new Date(checkin.checked_in_at).getTime() < APPEAL_WINDOW_MS;

  async function handleAppeal() {
    if (!reason.trim()) {
      setError("Please explain why you are appealing.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const { data } = await api.post<Checkin>(`/checkins/${checkinId}/appeal`, {
        appeal_reason: reason,
      });
      setCheckin(data);
      setShowForm(false);
    } catch (err: any) {
      setError(errorText(err, "Could not send your appeal."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell>
      <div className="flex justify-center pt-12">
        <div className="max-w-md w-full">
          <Link href={`/courses/${courseId}`} className="text-sm text-blue-600 underline">
            ← Back to check-ins
          </Link>
          <h1 className="text-2xl font-bold mt-3 mb-6">Check-in result</h1>

          {error && <div className="alert-error">{error}</div>}
          {loading && <p className="text-gray-500">Loading...</p>}

          {checkin && (
            <>
              <div
                className={`border-l-4 p-4 mb-4 ${
                  statusStyle[checkin.status] ?? "bg-gray-100 border-gray-400"
                }`}
              >
                <p className="font-bold capitalize">{checkin.status}</p>
                <p className="text-sm">{checkin.session_name ?? "Session"}</p>
                <p className="text-sm">{new Date(checkin.checked_in_at).toLocaleString()}</p>
              </div>

              <div className="card-panel !max-w-none mb-4 text-sm space-y-1">
                <p>Risk score: {checkin.risk_score.toFixed(2)}</p>
                <p>Distance from venue: {Math.round(checkin.distance_from_venue_meters)} m</p>
                {checkin.location_accuracy_meters != null && (
                  <p>Location accuracy: about {Math.round(checkin.location_accuracy_meters)} m</p>
                )}
                {checkin.liveness_passed != null && (
                  <p>Liveness: {checkin.liveness_passed ? "Passed" : "Failed"}</p>
                )}
                {checkin.face_match_passed != null && (
                  <p>Face match: {checkin.face_match_passed ? "Passed" : "Failed"}</p>
                )}
                {checkin.risk_factors.length > 0 && (
                  <p>Factors: {checkin.risk_factors.map((f) => f.type).join(", ")}</p>
                )}
              </div>

              {checkin.review_notes && (
                <div className="card-panel !max-w-none mb-4 text-sm">
                  <p className="font-semibold">Instructor notes</p>
                  <p className="text-gray-600">{checkin.review_notes}</p>
                </div>
              )}

              {checkin.appeal_reason && (
                <div className="card-panel !max-w-none mb-4 text-sm">
                  <p className="font-semibold">Your appeal</p>
                  <p className="text-gray-600">{checkin.appeal_reason}</p>
                </div>
              )}

              {canAppeal && !showForm && (
                <button className="btn-secondary" onClick={() => setShowForm(true)}>
                  Appeal this result
                </button>
              )}

              {showForm && (
                <div className="card-panel !max-w-none">
                  <label htmlFor="reason" className="field-label">
                    Why should this be reviewed?
                  </label>
                  <textarea
                    id="reason"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    maxLength={2000}
                    rows={4}
                    className="input-field mb-3"
                  />
                  <div className="flex items-center gap-3">
                    <button
                      className="btn-primary !w-auto"
                      onClick={handleAppeal}
                      disabled={submitting}
                    >
                      {submitting ? "Sending..." : "Send appeal"}
                    </button>
                    <button
                      className="text-gray-600 underline text-sm"
                      onClick={() => setShowForm(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}