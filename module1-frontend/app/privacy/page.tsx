"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { AppShell } from "@/components/ui/layout/AppShell";

export default function PrivacyPage() {
  const [cameraConsent, setCameraConsent] = useState(false);
  const [locationConsent, setLocationConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadConsent() {
      try {
        const { data } = await api.get("/users/me");
        setCameraConsent(data.camera_consent);
        setLocationConsent(data.geolocation_consent);
      } catch (err: any) {
        setError(err?.response?.data?.detail ?? "Failed to load your settings.");
      } finally {
        setLoading(false);
      }
    }
    loadConsent();
  }, []);

  async function handleCameraToggle(checked: boolean) {
    setCameraConsent(checked);
    setError("");
    try {
      await api.put("/users/me", { camera_consent: checked });
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Failed to update camera setting.");
      setCameraConsent(!checked);
    }
  }

  async function handleLocationToggle(checked: boolean) {
    setLocationConsent(checked);
    setError("");
    try {
      await api.put("/users/me", { geolocation_consent: checked });
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Failed to update location setting.");
      setLocationConsent(!checked);
    }
  }

  return (
    <AppShell>
      <div className="flex justify-center pt-12">
        <div className="max-w-md w-full">
          <h1 className="text-2xl font-bold mb-6">Privacy & Security</h1>

          {error && <div className="alert-error">{error}</div>}

          {loading ? (
            <p className="text-gray-500">Loading...</p>
          ) : (
            <>
              <div className="card-panel !max-w-none mb-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-semibold">Camera</span>
                  <label className="switch">
                    <input
                      type="checkbox"
                      checked={cameraConsent}
                      onChange={(e) => handleCameraToggle(e.target.checked)}
                    />
                    <span className="switch-track"></span>
                    <span className="switch-thumb"></span>
                  </label>
                </div>
                <p className="text-sm text-gray-600">
                  Used to verify your identity during check-in. No photos or
                  video are stored.
                </p>
              </div>

              <div className="card-panel !max-w-none mb-6">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-semibold">Location</span>
                  <label className="switch">
                    <input
                      type="checkbox"
                      checked={locationConsent}
                      onChange={(e) => handleLocationToggle(e.target.checked)}
                    />
                    <span className="switch-track"></span>
                    <span className="switch-thumb"></span>
                  </label>
                </div>
                <p className="text-sm text-gray-600">
                  Used to confirm you&apos;re physically present when you
                  check in.
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}