"use client";

/**
 * @fileoverview Global admin unlock gate rendered in the top bar.
 *
 * Mutating Margin endpoints require a local admin bearer token plus a CSRF
 * token. This single control lets the user unlock admin mode once for the
 * whole browser. Credentials live in localStorage and never enter the server
 * bundle or repository.
 */

import { useState, useSyncExternalStore } from "react";
import { ShieldAlert, ShieldCheck } from "lucide-react";

import {
  clearAdminSession,
  getAdminSession,
  hasAdminSession,
  setAdminSession,
} from "@/lib/admin-session";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

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

export type AdminGateProps = {
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

  function handleGateClick() {
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
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={handleGateClick}
        title="已解锁管理员模式，点击清除"
        className="gap-1.5"
      >
        <ShieldCheck className="size-3.5 text-positive" />
        已解锁
      </Button>
    );
  }

  return (
    <>
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() => setOpen(true)}
        title="解锁管理员模式以执行写操作"
        className="gap-1.5"
      >
        <ShieldAlert className="size-3.5 text-caution" />
        未解锁
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>解锁管理员模式</DialogTitle>
          </DialogHeader>
          <DialogDescription>
            写密钥、测试 Provider、启动估值发现等操作需要本地管理员凭据。仅在当前浏览器保存，不会进入服务端或代码仓库。
          </DialogDescription>
          <div className="grid gap-3 pt-1">
            <div className="grid gap-1.5">
              <Label htmlFor="admin-gate-token">Admin API token</Label>
              <Input
                id="admin-gate-token"
                type="password"
                autoComplete="off"
                value={adminToken}
                onChange={(event) => setAdminToken(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="admin-gate-csrf">CSRF token</Label>
              <Input
                id="admin-gate-csrf"
                type="password"
                autoComplete="off"
                value={csrfToken}
                onChange={(event) => setCsrfToken(event.target.value)}
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={remember}
                onChange={(event) => setRemember(event.target.checked)}
              />
              记住本次会话（localStorage）
            </label>
            {error ? (
              <p className="text-xs text-negative" role="alert">
                {error}
              </p>
            ) : null}
            {DEV_HINT_DEFAULTS ? (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={fillDevDefaults}
              >
                填入 dev 默认 token
              </Button>
            ) : null}
            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setOpen(false)}
              >
                取消
              </Button>
              <Button type="button" onClick={applySession}>
                解锁
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
