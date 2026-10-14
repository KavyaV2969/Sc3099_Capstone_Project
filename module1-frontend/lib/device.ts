import { api } from "./api";

const DEVICE_KEY = "saiv_device_id";

function randomHex(bytes: number): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  return Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function getDeviceId(): string {
  try {
    const existing = localStorage.getItem(DEVICE_KEY);
    if (existing) return existing;
    const id = randomHex(32);
    localStorage.setItem(DEVICE_KEY, id);
    return id;
  } catch {
    return randomHex(32);
  }
}

export async function registerDevice(): Promise<string> {
  const fingerprint = getDeviceId();
  await api.post("/devices/register", {
    device_fingerprint: fingerprint,
    device_name: "Web browser",
    platform: "web",
  });
  return fingerprint;
}