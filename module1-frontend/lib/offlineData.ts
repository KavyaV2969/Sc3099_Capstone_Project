import { api } from "./api";
import { offlineStore } from "./offlineStore";

// Online: fetch and save. Offline (no response at all): return the saved copy.
// Real errors such as 401 or 404 still throw, so they aren't hidden.
export async function cachedGet<T>(
  url: string,
  params?: Record<string, unknown>
): Promise<{ data: T; stale: boolean }> {
  const key = url + (params ? "?" + JSON.stringify(params) : "");
  try {
    const { data } = await api.get<T>(url, { params });
    await offlineStore.setItem(key, data);
    return { data, stale: false };
  } catch (err: any) {
    if (!err?.response) {
      const saved = await offlineStore.getItem<T>(key);
      if (saved !== null) return { data: saved, stale: true };
    }
    throw err;
  }
}