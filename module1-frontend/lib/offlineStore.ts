import localforage from "localforage";

export const offlineStore = localforage.createInstance({ name: "saiv-offline" });

export async function clearOfflineData(): Promise<void> {
  await offlineStore.clear();
}

export function warmRoutes(urls: string[]): void {
  urls.forEach((u) => {
    fetch(u, { headers: { Accept: "text/html" } }).catch(() => {});
  });
}