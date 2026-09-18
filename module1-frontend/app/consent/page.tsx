"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { AppShell } from "@/components/ui/layout/AppShell";

export default function ConsentPage() {
  const router = useRouter();
  const [cameraConsent, setCameraConsent] = useState(false);
  const [locationConsent, setLocationConsent] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleContinue() {
    setIsSubmitting(true);
    setError("");

    try {
      await api.put("/users/me", {
        camera_consent: cameraConsent,
        geolocation_consent: locationConsent,
      });
      router.push("/");
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Failed to save consent.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AppShell>
      <div className="flex justify-center pt-12">
        <div className="max-w-md w-full">
          <h1 className="text-2xl font-bold mb-6">Permissions</h1>
          <p className="text-gray-600 mb-6">
            SAIV uses your camera and location during check-in to verify your
            identity and confirm you&apos;re physically present. You&apos;ll
            be asked to grant browser access when you actually check in.
          </p>
          <p className="text-gray-400 mb-6">
            You can revoke browser settings anytime via &apos;Privacy & Security&apos; tab.
          </p>

          {error && <div className="alert-error">{error}</div>}

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
                Used to verify your identity during check-in. No photos or
                video are stored.
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

          <button
            className="btn-primary"
            onClick={handleContinue}
            disabled={isSubmitting}
          >
            {isSubmitting ? "Saving..." : "Save Settings"}
          </button>

          <div
            className="flex gap-3 self-center mt-6"
          >
            <button
              className="btn-secondary"
              onClick={() => router.push("/privacy")}
            >
                Privacy & Security
            </button>

            <button
              className="text-gray-600 underline text-sm self-center whitespace-nowrap"
              onClick={() => router.push("/")}>
                Skip for now
            </button>
          </div>
        </div>
      </div>
    </AppShell>
  );
}