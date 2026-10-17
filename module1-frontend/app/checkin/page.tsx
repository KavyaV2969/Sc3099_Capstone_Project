"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { getLocationFix, type LocationFix } from "@/lib/geolocation";
import { registerDevice } from "@/lib/device";
import { AppShell } from "@/components/ui/layout/AppShell";
import type { Session } from "@/lib/types";

interface CheckinResult {
  status: string; // approved | flagged | rejected
  risk_score: number;
  distance_from_venue_meters: number;
  risk_factors: { type: string }[];
}

function errorText(err: any, fallback: string): string {
  const detail = err?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

function CheckinContent() {
  const router = useRouter();
  const sessionId = useSearchParams().get("session");

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [streamActive, setStreamActive] = useState(false);
  const [photo, setPhoto] = useState<string | null>(null);
  const [location, setLocation] = useState<LocationFix | null>(null);
  const [locating, setLocating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<CheckinResult | null>(null);
  const [error, setError] = useState("");

  const needsPhoto =
    !!session && (session.require_liveness_check || session.require_face_match);

  const returnUrl = encodeURIComponent(`/checkin?session=${sessionId}`);
  const locationDeniedUrl = `/permission-denied?type=location&return=${returnUrl}`;
  const cameraDeniedUrl = `/permission-denied?type=camera&return=${returnUrl}`;

  // Load the session and check app-level consent
  useEffect(() => {
    async function load() {
      if (!sessionId) {
        setError("No session selected.");
        setLoading(false);
        return;
      }
      try {
        const [{ data: sessionData }, { data: user }] = await Promise.all([
          api.get<Session>(`/sessions/${sessionId}`),
          api.get("/users/me"),
        ]);
        if (!user.geolocation_consent) {
          router.replace(locationDeniedUrl);
          return;
        }
        if (
          (sessionData.require_liveness_check || sessionData.require_face_match) &&
          !user.camera_consent
        ) {
          router.replace(cameraDeniedUrl);
          return;
        }
        setSession(sessionData);
      } catch (err: any) {
        setError(errorText(err, "Could not load this session."));
      } finally {
        setLoading(false);
      }
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Release the camera when leaving the page
  useEffect(() => () => stopCamera(), []);

  async function startCamera() {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user" },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        setStreamActive(true);
      }
    } catch (err: any) {
      setError(
        err.name === "NotAllowedError"
          ? "Your browser has blocked camera access. Click the camera icon in the address bar to allow it, then try again."
          : "Could not access the camera."
      );
    }
  }

  function stopCamera() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setStreamActive(false);
  }

  function takePhoto() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    setPhoto(canvas.toDataURL("image/jpeg", 0.9));
    stopCamera(); // release the camera as soon as the photo is taken
  }

  async function handleGetLocation() {
    setLocating(true);
    setError("");
    try {
      setLocation(await getLocationFix());
    } catch (err: any) {
      if (err?.code === 1) {
        router.push(locationDeniedUrl); // browser blocked location
        return;
      }
      setError(
        err?.code === 3
          ? "Getting your location timed out. Please try again."
          : "Could not get your location. Please try again."
      );
    } finally {
      setLocating(false);
    }
  }

  async function handleCheckIn() {
    if (needsPhoto && !photo) {
      setError("Please take a photo first.");
      return;
    }
    if (!location) {
      setError("Please get your location first.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const fingerprint = await registerDevice();
      const { data } = await api.post<CheckinResult>("/checkins/", {
        session_id: sessionId,
        latitude: location.latitude,
        longitude: location.longitude,
        location_accuracy_meters: location.accuracy,
        device_fingerprint: fingerprint,
        liveness_challenge_response: photo ? photo.split(",")[1] : undefined,
      });
      setResult(data);
      setPhoto(null); // don't keep the image after submitting
    } catch (err: any) {
      setError(errorText(err, "Check-in failed. Please try again."));
    } finally {
      setSubmitting(false);
    }
  }

  const statusStyle: Record<string, string> = {
    approved: "bg-green-100 border-green-500 text-green-700",
    flagged: "bg-yellow-100 border-yellow-500 text-yellow-800",
    rejected: "bg-red-100 border-red-500 text-red-700",
  };

  const ready = (!needsPhoto || !!photo) && !!location;

  return (
    <AppShell>
      <div className="flex justify-center pt-12">
        <div className="max-w-md w-full">
          <h1 className="text-2xl font-bold mb-4">Check In</h1>

          {loading && <p className="text-gray-500">Loading...</p>}
          {error && <div className="alert-error">{error}</div>}

          {!loading && session && !result && (
            <>
              <div className="mb-4">
                <p className="text-sm text-gray-500">{session.course_code}</p>
                <h2 className="text-lg font-semibold">{session.course_name}</h2>
                <p className="text-sm text-gray-600">
                  {session.name} · {session.venue_name}
                </p>
              </div>

              {needsPhoto && (
                <div className="card-panel !max-w-none mb-4">
                  <h3 className="font-semibold mb-1">1. Face photo</h3>
                  <p className="text-sm text-gray-600 mb-3">
                    Look straight at the camera. This photo is used to verify
                    it&apos;s really you, and it isn&apos;t stored.
                  </p>

                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    className="w-full rounded-lg bg-gray-200 mb-3"
                    style={{ display: streamActive ? "block" : "none" }}
                  />
                  <canvas ref={canvasRef} className="hidden" />
                  {photo && (
                    <img
                      src={photo}
                      alt="Your check-in photo"
                      className="w-full rounded-lg mb-3"
                    />
                  )}

                  {!streamActive && !photo && (
                    <button className="btn-primary" onClick={startCamera}>
                      Start Camera
                    </button>
                  )}
                  {streamActive && (
                    <button className="btn-primary" onClick={takePhoto}>
                      Take Photo
                    </button>
                  )}
                  {photo && (
                    <button
                      className="btn-secondary"
                      onClick={() => {
                        setPhoto(null);
                        startCamera();
                      }}
                    >
                      Retake
                    </button>
                  )}
                </div>
              )}

              <div className="card-panel !max-w-none mb-4">
                <h3 className="font-semibold mb-1">
                  {needsPhoto ? "2" : "1"}. Your location
                </h3>
                <p className="text-sm text-gray-600 mb-3">
                  We compare your location with the classroom to confirm you&apos;re
                  there.
                </p>

                {location && (
                  <div className="bg-gray-50 rounded-lg p-3 mb-3 text-sm">
                    <p>Latitude: {location.latitude.toFixed(5)}</p>
                    <p>Longitude: {location.longitude.toFixed(5)}</p>
                    <p className="text-gray-500">
                      Accuracy: about {Math.round(location.accuracy)} m
                    </p>
                  </div>
                )}

                <button
                  className={location ? "btn-secondary" : "btn-primary"}
                  onClick={handleGetLocation}
                  disabled={locating}
                >
                  {locating
                    ? "Getting location..."
                    : location
                    ? "Refresh Location"
                    : "Get My Location"}
                </button>
              </div>

              <button
                className="btn-primary"
                onClick={handleCheckIn}
                disabled={submitting || !ready}
              >
                {submitting ? "Checking in..." : "Check In Now"}
              </button>
            </>
          )}

          {result && (
            <div>
              <div
                className={`border-l-4 p-4 mb-4 ${
                  statusStyle[result.status] ?? "bg-gray-100 border-gray-400"
                }`}
              >
                <p className="font-bold capitalize">{result.status}</p>
                <p className="text-sm">
                  Risk score: {result.risk_score.toFixed(2)} · Distance from venue:{" "}
                  {Math.round(result.distance_from_venue_meters)} m
                </p>
                {result.risk_factors.length > 0 && (
                  <p className="text-sm mt-1">
                    Factors: {result.risk_factors.map((f) => f.type).join(", ")}
                  </p>
                )}
              </div>
              <button className="btn-primary" onClick={() => router.push("/")}>
                Back to Home
              </button>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

export default function CheckinPage() {
  return (
    <Suspense fallback={null}>
      <CheckinContent />
    </Suspense>
  );
}