import axios, {
  AxiosError,
  type InternalAxiosRequestConfig,
} from "axios";
import { StorageKeys, getItem, setItem, clearAuthStorage } from "./storage";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: BASE_URL,
});

// Attach the access token to every outgoing request, if we have one
api.interceptors.request.use((config) => {
  const token = getItem(StorageKeys.accessToken);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// If a request comes back 401, try to refresh once, then retry it
let isRefreshing = false;
let pendingRequests: Array<(token: string | null) => void> = [];

function onRefreshed(token: string | null) {
  pendingRequests.forEach((callback) => callback(token));
  pendingRequests = [];
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    const isUnauthorized = error.response?.status === 401;
    const isAuthEndpoint = originalRequest?.url?.includes("/auth/");

    if (!isUnauthorized || isAuthEndpoint || originalRequest._retry) {
      return Promise.reject(error);
    }

    originalRequest._retry = true;

    if (isRefreshing) {
      // Another request already triggered a refresh — wait for it
      return new Promise((resolve, reject) => {
        pendingRequests.push((token) => {
          if (token) {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            resolve(api(originalRequest));
          } else {
            reject(error);
          }
        });
      });
    }

    isRefreshing = true;
    try {
      const refreshToken = getItem(StorageKeys.refreshToken);
      if (!refreshToken) throw new Error("no refresh token");

      const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {
        refresh_token: refreshToken,
      });

      setItem(StorageKeys.accessToken, data.access_token);
      setItem(StorageKeys.refreshToken, data.refresh_token);
      onRefreshed(data.access_token);

      originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
      return api(originalRequest);
    } catch (refreshError) {
      onRefreshed(null);
      clearAuthStorage();
      window.location.href = "/login";
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  }
);