"use client";

import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { AppShell } from "@/components/ui/layout/AppShell";

function PermissionDeniedContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const type = searchParams.get("type");
  const returnTo = searchParams.get("return") || "/";

  const [cameraConsent, setCameraConsent] = useState(false);
  const [locationConsent, setLocationConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadCurrentConsent() {
      try {
        const { data } = await api.get("/users/me");
        setCameraConsent(data.camera_consent);
        setLocationConsent(data.geolocation_consent);
      } catch (err) {
        // if this fails, just leave checkboxes at default false
      } finally {
        setLoading(false);
      }
    }
    loadCurrentConsent();
  }, []);

  async function handleSave() {
    setIsSubmitting(true);
    setError("");
    try {
      await api.put("/users/me", {
        camera_consent: cameraConsent,
        geolocation_consent: locationConsent,
      });
      router.push(returnTo);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Failed to save consent.");
    } finally {
      setIsSubmitting(false);
    }
  }

  const title = type === "location" ? "Location Access Needed" : "Camera Access Needed";
  const explanation =
    type === "location"
      ? "SAIV checks your location against the classroom to confirm you're physically present when you check in. Without location access, you won't be able to check in to sessions."
      : "SAIV uses your camera to verify your identity, helping prevent proxy attendance. Without camera access, you won't be able to enroll your face or check in to sessions.";

  return (
    <AppShell>
      <div className="flex justify-center pt-12">
        <div className="max-w-md w-full">
          <h1 className="text-2xl font-bold mb-4">{title}</h1>
          <p className="text-gray-600 mb-6">
            It looks like {type === "location" ? "location" : "camera"} access was
            denied in your browser. {explanation}
          </p>

          <p className="text-sm text-gray-500 mb-4">
            You can update your permissions below, then allow access again when
            prompted by your browser.
          </p>

          {error && <div className="alert-error">{error}</div>}

          {!loading && (
            <>
              <label className="flex items-start gap-3 mb-4 card-panel !max-w-none">
                <input
                  type="checkbox"
                  checked={cameraConsent}
                  onChange={(e) => setCameraConsent(e.target.checked)}
                  className="mt-1"
                />
                <span>
                  <span className="font-semibold block">Camera</span>
                  <span className="text-sm text-gray-600">
                    Used to verify your identity during check-in.
                  </span>
                </span>
              </label>

              <label className="flex items-start gap-3 mb-6 card-panel !max-w-none">
                <input
                  type="checkbox"
                  checked={locationConsent}
                  onChange={(e) => setLocationConsent(e.target.checked)}
                  className="mt-1"
                />
                <span>
                  <span className="font-semibold block">Location</span>
                  <span className="text-sm text-gray-600">
                    Used to confirm you&apos;re physically present when you check in.
                  </span>
                </span>
              </label>

              <div className="flex items-center gap-3">
                <button className="btn-primary !w-auto" onClick={handleSave} disabled={isSubmitting}>
                  {isSubmitting ? "Saving..." : "Save & Try Again"}
                </button>
                <button
                  className="text-gray-600 underline text-sm whitespace-nowrap"
                  onClick={() => router.push("/")}
                >
                  Back to Home
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}

export default function PermissionDeniedPage() {
  return (
    <Suspense fallback={null}>
      <PermissionDeniedContent />
    </Suspense>
  );
}