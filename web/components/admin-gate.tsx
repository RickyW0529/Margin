"use client";

/**
 * @fileoverview Global admin unlock gate rendered in the top bar.
 *
 * Mutating Margin endpoints require a local admin bearer token plus a CSRF
 * token. Instead of spreadsheets of input forms across settings pages, this
 * single floating control lets the user unlock admin mode once for the whole
 * browser. It also offers a one-click "use dev defaults" button in
 * development so local stacks boot without copy-pasting tokens.
 */

import { useState, useSyncExternalStore } from "react";

import {
  clearAdminSession,
  getAdminSession,
  hasAdminSession,
  setAdminSession,
} from "@/lib/admin-session";

/** Reads the dev-default hint flag exposed to the browser bundle. */
const DEV_HINT_DEFAULTS =
  process.env.NEXT_PUBLIC_MARGIN_DEV_ADMIN_HINT === "1";

const ADMIN_EVENT = "margin-admin-session";

function subscribe(callback: () => void) {
  if (typeof window === "undefined") {
    return () => {};
  }
  window.addEventListener("storage", callback);
  window.addEventListener(ADMIN_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(ADMIN_EVENT, callback);
  };
}

function getSnapshot(): boolean {
  return hasAdminSession();
}

function getServerSnapshot(): boolean {
  return false;
}

function notifyChange() {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new Event(ADMIN_EVENT));
}

/** Props for the AdminGate component. */
export type AdminGateProps = {
  /** Optional callback invoked whenever the unlocked state changes. */
  onSessionChange?: () => void;
};

/** Floating admin unlock control shown in the application top bar. */
export function AdminGate({ onSessionChange }: AdminGateProps = {}) {
  const unlocked = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );
  const [open, setOpen] = useState(false);
  const [adminToken, setAdminToken] = useState("");
  const [csrfToken, setCsrfToken] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function applySession() {
    if (adminToken.trim().length === 0 || csrfToken.trim().length === 0) {
      setError("请填写管理员 token 与 CSRF token");
      return;
    }
    setAdminSession(adminToken, csrfToken, remember);
    notifyChange();
    setOpen(false);
    setError(null);
    setAdminToken("");
    setCsrfToken("");
    onSessionChange?.();
  }

  function fillDevDefaults() {
    setAdminToken("dev-admin-token");
    setCsrfToken("dev-csrf-token");
    setError(null);
  }

  function unlock() {
    const existing = getAdminSession();
    if (existing) {
      clearAdminSession();
      notifyChange();
      onSessionChange?.();
      return;
    }
    setOpen(true);
  }

  if (unlocked) {
    return (
      <button
        type="button"
        className="admin-gate admin-gate-unlocked"
        onClick={unlock}
        title="已解锁管理员模式，点击清除"
      >
        <span aria-hidden="true">●</span> 已解锁
      </button>
    );
  }

  return (
    <>
      <button
        type="button"
        className="admin-gate admin-gate-locked"
        onClick={() => setOpen(true)}
        title="解锁管理员模式以执行写操作"
      >
        <span aria-hidden="true">○</span> 未解锁
      </button>
      {open ? (
        <div
          className="admin-gate-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="admin-gate-title"
        >
          <div className="admin-gate-card">
            <div className="admin-gate-header">
              <h2 id="admin-gate-title">解锁管理员模式</h2>
              <button
                type="button"
                className="admin-gate-close"
                aria-label="关闭"
                onClick={() => setOpen(false)}
              >
                ×
              </button>
            </div>
            <p className="admin-gate-help">
              写密钥、测试 Provider、启动估值发现等操作需要本地管理员凭据。仅在当前浏览器保存，不会进入服务端或代码仓库。
            </p>
            <label className="form-field">
              <span>Admin API token</span>
              <input
                aria-label="Admin API token"
                autoComplete="off"
                onChange={(event) => setAdminToken(event.target.value)}
                type="password"
                value={adminToken}
              />
            </label>
            <label className="form-field">
              <span>CSRF token</span>
              <input
                aria-label="CSRF token"
                autoComplete="off"
                onChange={(event) => setCsrfToken(event.target.value)}
                type="password"
                value={csrfToken}
              />
            </label>
            <label className="checkbox-field">
              <input
                checked={remember}
                onChange={(event) => setRemember(event.target.checked)}
                type="checkbox"
              />
              <span>记住本次会话（localStorage）</span>
            </label>
            {error ? <p className="form-error">{error}</p> : null}
            {DEV_HINT_DEFAULTS ? (
              <button
                type="button"
                className="secondary-button"
                onClick={fillDevDefaults}
              >
                填入 dev 默认 token
              </button>
            ) : null}
            <div className="admin-gate-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={() => setOpen(false)}
              >
                取消
              </button>
              <button
                type="button"
                className="primary-button"
                onClick={applySession}
              >
                解锁
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}