import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import api from "@/lib/api";
import { clearTokens, getRefreshToken, getToken, setTokens } from "@/lib/auth";
import type { AuthTokens, User } from "@/types";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string, rememberMe?: boolean) => Promise<User>;
  register: (data: {
    email: string;
    username: string;
    password: string;
    full_name?: string;
  }) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

// A real context (not a bare hook every caller instantiates independently)
// is what makes login/logout visible everywhere at once: the sidebar's
// logout button, ProtectedRoute's redirect check, and the profile page's
// user display all read the SAME state, so clearing it in one place is
// immediately reflected in all the others instead of each tracking its own
// stale copy until its own next remount.
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Runs once, on app boot - this is "automatic session restoration": if a
  // token is already in storage (remember-me from a prior visit, or just
  // still-open from earlier this session), it's validated against the
  // server rather than trusted blindly. An expired access token still
  // succeeds here, transparently, via the axios response interceptor's
  // refresh-and-retry (see lib/api.ts) - so this single call also covers
  // "seamless re-authentication" without any extra logic on this end.
  const refreshUser = useCallback(async () => {
    if (!getToken()) {
      setIsLoading(false);
      return;
    }
    try {
      const { data } = await api.get<User>("/auth/me");
      setUser(data);
    } catch {
      clearTokens();
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  const login = useCallback(async (email: string, password: string, rememberMe = true) => {
    const { data } = await api.post<AuthTokens>("/auth/login", { email, password });
    setTokens(data.access_token, data.refresh_token, rememberMe);
    const me = await api.get<User>("/auth/me");
    setUser(me.data);
    return me.data;
  }, []);

  const register = useCallback(
    async (data: { email: string; username: string; password: string; full_name?: string }) => {
      const response = await api.post<User>("/auth/register", data);
      return response.data;
    },
    []
  );

  const logout = useCallback(async () => {
    // Best-effort: the backend revokes this refresh token so it can't be
    // replayed after logout (see AuthService.logout) - only the CURRENT
    // session/device, not every session the user is logged into elsewhere,
    // same as ChatGPT's own "log out" (as opposed to "log out of all
    // devices"). Local tokens are cleared regardless of whether this call
    // succeeds - a network blip shouldn't be able to trap the user in a
    // "logged in" state client-side. Nothing here touches chats, threads,
    // or memories - those are server-side rows scoped to the account, not
    // to the session being ended.
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      try {
        await api.post("/auth/logout", { refresh_token: refreshToken });
      } catch {
        // Ignore - clearing local tokens below is what actually logs the
        // user out of this device; server-side revocation is defense in
        // depth, not something the user should be blocked on.
      }
    }
    clearTokens();
    setUser(null);
  }, []);

  const value: AuthContextValue = {
    user,
    isLoading,
    isAuthenticated: Boolean(user),
    login,
    register,
    logout,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
