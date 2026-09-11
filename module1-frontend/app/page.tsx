/**
 * SAIV Student Frontend - Module 1
 *
 * This is the skeleton implementation for the Student Frontend PWA.
 * Students must implement the check-in interface with camera access,
 * geolocation, and device binding.
 */

"use client";
import { clearAuthStorage, hasAccessToken } from "@/lib/storage";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { AppShell } from "@/components/ui/layout/AppShell";
import type { Session } from "@/lib/types";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: "2-digit" });
}

function canCheckIn(session: Session): boolean {
  const now = new Date();
  const opens = new Date(session.checkin_opens_at);
  const closes = new Date(session.checkin_closes_at);
  return session.status === "active" && now >= opens && now <= closes;
}

export default function Home() {
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!hasAccessToken()) {
      router.push("/login");
      return;
    }
    setChecked(true);

    async function loadActiveSessions() {
      try {
        const { data } = await api.get<Session[]>("/sessions/my-sessions");
        setSessions(data.filter((s) => s.status === "active"));
      } catch (err: any) {
        setError(err?.response?.data?.detail ?? "Failed to load sessions");
      } finally {
        setLoading(false);
      }
    }
    loadActiveSessions()
  }, [router]);

  if (!checked) {
    return null
  }

  return (
    <AppShell>
      <h1 className="text-2xl font-bold mb-6">Active Sessions</h1>

      {error && <div className="alert-error">{error}</div>}
      {loading && <p className="text-gray-500">Loading sessions...</p>}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
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
              {canCheckIn(session) ? "Check In" : "Not open"}
            </button>
          </div>
        ))}

        {!loading && sessions.length === 0 && (
          <p className="text-gray-500">No active sessions right now.</p>
        )}
      </div>
    </AppShell>
  );

      {/* ================================================================== */}
      {/* TODO: Implement the following features                             */}
      {/* ================================================================== */}

      {/* ------------------------------------------------------------------ */}
      {/* Authentication                                                     */}
      {/* ------------------------------------------------------------------ */}
      {/* - Login form with email/password                                   */}
      {/* - Registration form                                                */}
      {/* - JWT token storage (secure, HttpOnly where possible)              */}
      {/* - Auto-refresh token logic                                         */}

      {/* ------------------------------------------------------------------ */}
      {/* Camera Access                                                      */}
      {/* ------------------------------------------------------------------ */}
      {/* - WebRTC camera stream                                             */}
      {/* - Liveness challenge UI (blink, head turn prompts)                 */}
      {/* - Frame capture for face verification                              */}
      {/* - Consent flow before camera access                                */}

      {/* ------------------------------------------------------------------ */}
      {/* Geolocation                                                        */}
      {/* ------------------------------------------------------------------ */}
      {/* - Geolocation API integration                                      */}
      {/* - Explicit consent before location access                          */}
      {/* - GPS coordinates sent with check-in                               */}
      {/* - Error handling for denied permissions                            */}

      {/* ------------------------------------------------------------------ */}
      {/* Device Binding                                                     */}
      {/* ------------------------------------------------------------------ */}
      {/* - ECDSA key pair generation (Web Crypto API)                       */}
      {/* - Public key rotation on each session                              */}
      {/* - Device fingerprinting                                            */}
      {/* - Secure key storage                                               */}

      {/* ------------------------------------------------------------------ */}
      {/* PWA Features                                                       */}
      {/* ------------------------------------------------------------------ */}
      {/* - Service worker for offline support                               */}
      {/* - PWA manifest                                                     */}
      {/* - Offline check-in queue with sync                                 */}
      {/* - LocalForage for persistent storage                               */}

      {/* ------------------------------------------------------------------ */}
      {/* Check-in Flow                                                      */}
      {/* ------------------------------------------------------------------ */}
      {/* 1. Select active session                                           */}
      {/* 2. Grant camera permission (with consent)                          */}
      {/* 3. Complete liveness challenge                                     */}
      {/* 4. Grant location permission (with consent)                        */}
      {/* 5. Submit check-in to backend                                      */}
      {/* 6. Display success/failure with risk score                         */}
}
