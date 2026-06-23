/**
 * @fileoverview Browser-only admin session helpers for the Margin web client.
 *
 * The Margin backend protects mutating endpoints with a local admin bearer
 * token plus a CSRF token (see `require_local_admin`). Rather than embedding
 * these secrets in the client bundle, the UI prompts the user once per browser
 * and stores them in `localStorage` under stable keys. This keeps the tokens
 * out of the compiled bundle and survives page refreshes, while remaining
 * scoped to a single origin/device.
 */

const ADMIN_TOKEN_KEY = "margin.adminApiToken";
const CSRF_TOKEN_KEY = "margin.csrfToken";
const ADMIN_REMEMBER_KEY = "margin.adminSessionRemember";

/** Safe view of the locally stored admin session. */
export type AdminSession = {
  adminToken: string;
  csrfToken: string;
};

/** Returns true when both admin tokens are present in `localStorage`. */
export function hasAdminSession(): boolean {
  return readRawTokens().adminToken.length > 0 && readRawTokens().csrfToken.length > 0;
}

/** Returns a copy of the admin session, or null when not configured. */
export function getAdminSession(): AdminSession | null {
  const { adminToken, csrfToken } = readRawTokens();
  if (adminToken.length === 0 || csrfToken.length === 0) {
    return null;
  }
  return { adminToken, csrfToken };
}

/** Persists the admin/CSRF tokens and the "remember session" preference. */
export function setAdminSession(
  adminToken: string,
  csrfToken: string,
  remember = true,
): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(ADMIN_TOKEN_KEY, adminToken.trim());
  window.localStorage.setItem(CSRF_TOKEN_KEY, csrfToken.trim());
  window.localStorage.setItem(ADMIN_REMEMBER_KEY, remember ? "1" : "0");
}

/** Removes the admin session tokens and preference flag from `localStorage`. */
export function clearAdminSession(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(ADMIN_TOKEN_KEY);
  window.localStorage.removeItem(CSRF_TOKEN_KEY);
  window.localStorage.removeItem(ADMIN_REMEMBER_KEY);
}

/**
 * Reads the admin tokens from `localStorage`, falling back to `sessionStorage`
 * so previously configured sessions (under the legacy keys) keep working.
 */
function readRawTokens(): { adminToken: string; csrfToken: string } {
  if (typeof window === "undefined") {
    return { adminToken: "", csrfToken: "" };
  }
  const lsAdmin = window.localStorage.getItem(ADMIN_TOKEN_KEY) ?? "";
  const lsCsrf = window.localStorage.getItem(CSRF_TOKEN_KEY) ?? "";
  const ssAdmin = window.sessionStorage.getItem(ADMIN_TOKEN_KEY) ?? "";
  const ssCsrf = window.sessionStorage.getItem(CSRF_TOKEN_KEY) ?? "";
  return {
    adminToken: lsAdmin.length > 0 ? lsAdmin : ssAdmin,
    csrfToken: lsCsrf.length > 0 ? lsCsrf : ssCsrf,
  };
}