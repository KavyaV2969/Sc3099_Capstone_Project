import localforage from "localforage";
import { api } from "./api";

const DEVICE_KEY = "saiv_device_id";
const KEYPAIR_KEY = "saiv_device_keypair";

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

export async function getKeyPair(): Promise<CryptoKeyPair | null> {
  if (!globalThis.crypto?.subtle) return null; // WebCrypto needs https or localhost
  const existing = await localforage.getItem<CryptoKeyPair>(KEYPAIR_KEY);
  if (existing) return existing;
  const pair = await crypto.subtle.generateKey(
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["sign", "verify"]
  );
  await localforage.setItem(KEYPAIR_KEY, pair);
  return pair;
}

async function publicKeyPem(): Promise<string | undefined> {
  const pair = await getKeyPair();
  if (!pair) return undefined;
  const spki = await crypto.subtle.exportKey("spki", pair.publicKey);
  const b64 = btoa(String.fromCharCode(...new Uint8Array(spki)));
  return `-----BEGIN PUBLIC KEY-----\n${b64.match(/.{1,64}/g)!.join("\n")}\n-----END PUBLIC KEY-----`;
}

export async function registerDevice(): Promise<{ id: string; fingerprint: string }> {
  const fingerprint = getDeviceId();
  const { data } = await api.post("/devices/register", {
    device_fingerprint: fingerprint,
    device_name: "Web browser",
    platform: "web",
    public_key: await publicKeyPem(),
  });
  return { id: data.id, fingerprint };
}

function toBase64(buf: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

export async function signCheckin(deviceId: string, body: Record<string, unknown>) {
  const pair = await getKeyPair();
  if (!pair) return null; // no WebCrypto (plain http on a phone): skip the proof

  const { data } = await api.post(`/devices/${deviceId}/challenge`, body);
  const payload = Uint8Array.from(atob(data.signing_payload), (c) => c.charCodeAt(0));
  const signature = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    pair.privateKey,
    payload
  );
  return {
    device_challenge_id: data.challenge_id as string,
    device_signature: toBase64(signature),
  };
}