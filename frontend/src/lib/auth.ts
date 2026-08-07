const TOKEN_KEY = "access_token";
const REFRESH_KEY = "refresh_token";
// Marks which storage backend the current session's tokens live in, so a
// page reload knows where to look without the caller having to pass
// rememberMe around everywhere.
const REMEMBER_KEY = "auth_remember";

// Remember-me on (default, matches "stay signed in" products like ChatGPT):
// tokens go in localStorage and survive closing the browser entirely.
// Remember-me off: tokens go in sessionStorage, so closing the last tab of
// the browser ends the session even though the user never explicitly logged
// out - exactly what "don't remember me" should mean.
function storage(): Storage {
  return localStorage.getItem(REMEMBER_KEY) === "false" ? sessionStorage : localStorage;
}

export function getToken(): string | null {
  return storage().getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  storage().setItem(TOKEN_KEY, token);
}

export function getRefreshToken(): string | null {
  return storage().getItem(REFRESH_KEY);
}

export function setRefreshToken(token: string): void {
  storage().setItem(REFRESH_KEY, token);
}

export function setTokens(access: string, refresh: string, rememberMe = true): void {
  // The remember-me flag itself always lives in localStorage (it has to be
  // readable before we know which storage to check), and is set BEFORE the
  // tokens so storage() already resolves correctly for the two writes below.
  localStorage.setItem(REMEMBER_KEY, String(rememberMe));
  setToken(access);
  setRefreshToken(refresh);
}

export function clearTokens(): void {
  // Clear both backends unconditionally - if remember-me was toggled between
  // logins, a stale token could otherwise be left behind in the other one.
  for (const s of [localStorage, sessionStorage]) {
    s.removeItem(TOKEN_KEY);
    s.removeItem(REFRESH_KEY);
  }
  localStorage.removeItem(REMEMBER_KEY);
}

export function isAuthenticated(): boolean {
  return Boolean(getToken());
}
