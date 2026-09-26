"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { AppShell } from "@/components/ui/layout/AppShell";

export default function EnrollFacePage() {
  const router = useRouter();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [streamActive, setStreamActive] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string; quality_score: number } | null>(null);
  const [error, setError] = useState("");
  const [hasConsent, setHasConsent] = useState<boolean | null>(null);

  useEffect(() => {
    async function checkConsent() {
      try {
        const { data } = await api.get("/users/me");
        setHasConsent(data.camera_consent);
      } catch {
        setHasConsent(false);
      }
    }
    checkConsent();
  }, []);

  useEffect(() => {
    return () => {
      stopCamera();
    };
  }, []);

  async function startCamera() {
    if (!hasConsent) {
      router.push("/permission-denied?type=camera&return=/enroll-face");
      return;
    }

    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        setStreamActive(true);
      }
    } catch (err: any) {
      if (err.name === "NotAllowedError") {
        setError(
          "Your browser has blocked camera access. Click the camera icon in your address bar to allow it, then try again."
        );
      } else {
        setError("Could not access camera. Please check your device and try again.");
      }
    }
  }

  function stopCamera() {
    const stream = videoRef.current?.srcObject as MediaStream | null;
    stream?.getTracks().forEach((track) => track.stop());
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setStreamActive(false);
  }

  async function captureAndEnroll() {
    if (!videoRef.current || !canvasRef.current) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx?.drawImage(video, 0, 0, canvas.width, canvas.height);

    const imageDataUrl = canvas.toDataURL("image/jpeg", 0.9);

    stopCamera();

    setIsSubmitting(true);
    setError("");
    try {
      const { data } = await api.post("/users/me/face/enroll", { image: imageDataUrl });
      setResult(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Face enrollment failed. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AppShell>
      <div className="flex justify-center pt-12">
        <div className="max-w-md w-full text-center">
          <h1 className="text-2xl font-bold mb-4">Face Enrollment</h1>

          <p className="text-gray-600 mb-6">
            We&apos;ll capture a photo of your face to create a secure reference for
            future check-ins. This lets SAIV verify it&apos;s really you attending
            class, helping prevent proxy attendance. Your photo is converted into a
            one-way template — the original image is never stored.
          </p>

          {error && <div className="alert-error">{error}</div>}

          {result ? (
            <div>
              <div className="bg-green-100 border-l-4 border-green-500 text-green-700 p-3 text-sm mb-4 text-left">
                {result.message} (quality: {(result.quality_score * 100).toFixed(0)}%)
              </div>
              <button className="btn-primary" onClick={() => router.push("/")}>
                Continue to Home
              </button>
            </div>
          ) : (
            <>
              <p className="text-gray-600 mb-4">
                Position your face in frame and capture a clear photo.
              </p>

              <video
                ref={videoRef}
                autoPlay
                playsInline
                className="w-full rounded-lg bg-gray-200 mb-4"
                style={{ display: streamActive ? "block" : "none" }}
              />
              <canvas ref={canvasRef} className="hidden" />

              {!streamActive ? (
                <button className="btn-primary" onClick={startCamera}>
                  Start Camera
                </button>
              ) : (
                <button className="btn-primary" onClick={captureAndEnroll} disabled={isSubmitting}>
                  {isSubmitting ? "Enrolling..." : "Capture & Enroll"}
                </button>
              )}
            </>
          )}
          <button
              className="text-gray-600 underline text-sm self-center whitespace-nowrap"
              onClick={() => {
                stopCamera();
                router.push("/")
              }}>
                Skip for now
          </button>
        </div>
      </div>
    </AppShell>
  );
}