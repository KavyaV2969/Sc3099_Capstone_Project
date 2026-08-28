export const StorageKeys = {
  accessToken: "access_token",
  refreshToken: "refresh_token",
} as const;

type StorageKey = (typeof StorageKeys)[keyof typeof StorageKeys];

const AUTH_EVENT_NAME = "saiv:auth-state-changed";

function safeGet(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string) {
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    // ignore
  }
}

function safeRemove(key: string) {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // ignore
  }
}

function emitAuthStateChanged() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(AUTH_EVENT_NAME));
}

export function getItem(key: StorageKey): string | null {
  if (typeof window === "undefined") return null;
  return safeGet(key);
}

export function setItem(key: StorageKey, value: string) {
  if (typeof window === "undefined") return;
  safeSet(key, value);
  emitAuthStateChanged();
}

export function removeItem(key: StorageKey) {
  if (typeof window === "undefined") return;
  safeRemove(key);
  emitAuthStateChanged();
}

export function hasAccessToken(): boolean {
  return !!getItem(StorageKeys.accessToken);
}

export function clearAuthStorage() {
  removeItem(StorageKeys.accessToken);
  removeItem(StorageKeys.refreshToken);
}

export function subscribeToAuthStateChange(callback: () => void) {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(AUTH_EVENT_NAME, callback);
  return () => window.removeEventListener(AUTH_EVENT_NAME, callback);
}