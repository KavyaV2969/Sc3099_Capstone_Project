"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { AppShell } from "@/components/ui/layout/AppShell";
import { getDeviceId } from "@/lib/device";
import type { Device } from "@/lib/types";

export default function PrivacyPage() {
  const [cameraConsent, setCameraConsent] = useState(false);
  const [locationConsent, setLocationConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [devices, setDevices] = useState<Device[]>([]);
  const [devicesLoading, setDevicesLoading] = useState(true);
  const [thisDeviceId, setThisDeviceId] = useState("");

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

  useEffect(() => {
    setThisDeviceId(getDeviceId());
    async function loadDevices() {
      try {
        const { data } = await api.get<Device[]>("/devices/my-devices");
        setDevices(data.filter((d) => d.is_active));
      } catch (err: any) {
        setError(err?.response?.data?.detail ?? "Failed to load your devices.");
      } finally {
        setDevicesLoading(false);
      }
    }
    loadDevices();
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

  async function handleRemoveDevice(id: string) {
  if (!confirm("Remove this device? You'll need an admin to trust it again after your next check-in.")) return;
  try {
    await api.delete(`/devices/${id}`);
    setDevices((prev) => prev.filter((d) => d.id !== id));
  } catch (err: any) {
    setError(err?.response?.data?.detail ?? "Failed to remove the device.");
  }
}

  return (
    <AppShell>
      <div className="flex justify-center">
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

              <div className="card-panel !max-w-none mb-6">
                <h2 className="text-lg font-semibold mb-3">Your devices</h2>
                  {devicesLoading ? (
                    <p className="text-gray-500">Loading devices...</p>
                  ) : devices.length === 0 ? (
                    <p className="text-sm text-gray-500">
                      No devices yet. This browser is added the first time you check in.
                    </p>
                  ) : (
                    devices.map((d) => (
                      <div key={d.id} className="card-panel !max-w-none mb-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-semibold">{d.device_name ?? "Unnamed device"}</span>
                          {d.device_fingerprint === thisDeviceId && (
                            <span className="text-xs bg-blue-100 text-blue-700 rounded-full px-2 py-0.5">
                              This device
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-gray-600 capitalize">
                          {d.platform ?? "unknown"} · {d.is_trusted ? "Trusted" : "Not trusted"}
                        </p>
                        <p className="text-sm text-gray-500">
                          Last used: {d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : "never"}
                          <button
                            className="text-red-600 underline text-sm mt-2"
                            onClick={() => handleRemoveDevice(d.id)}
                          >
                            Remove
                          </button>
                          {" · "}
                          {d.total_checkins} check-ins
                        </p>
                      </div>
                    ))
                  )}
              </div>
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}