import axios from "axios";
import { getToken, setToken, getRefreshToken, setRefreshToken, clearTokens } from "@/lib/auth";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8001/api/v1",
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor - attach auth token
api.interceptors.request.use(
  (config) => {
    const token = getToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor - handle 401 and token refresh
api.interceptors.response.use(
(response) => response,
  async (error) => {
    const originalRequest = error.config as any;
    // A 401 from the auth endpoints themselves means bad credentials, not a
    // stale session - let the login/register form show its own inline error
    // instead of treating it as an expired-token event.
    const isAuthEndpoint = /\/auth\/(login|register)(\?|$)/.test(originalRequest?.url ?? "");
    if (error.response?.status === 401 && !originalRequest._retry && !isAuthEndpoint) {
      originalRequest._retry = true;
      try {
        const refreshToken = getRefreshToken();
        if (!refreshToken) throw new Error("No refresh token");
        const { data } = await axios.post(
          `${import.meta.env.VITE_API_URL || "http://localhost:8001/api/v1"}/auth/refresh`,
          { refresh_token: refreshToken }
        );
        setToken(data.access_token);
        setRefreshToken(data.refresh_token);
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
        return api(originalRequest);
      } catch (refreshError) {
        clearTokens();
        window.location.href = "/login";
        return Promise.reject(refreshError);
      }
    }
    return Promise.reject(error);
  }
);

export default api;
