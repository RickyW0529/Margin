"use client";

/**
 * @fileoverview Local recent-question store for the chat sidebar.
 */

import { useSyncExternalStore } from "react";

const STORAGE_KEY = "margin-recent-questions";
const CHANGE_EVENT = "margin-recent-questions-change";
const MAX_RECENT = 12;
const EMPTY_RECENT_QUESTIONS: RecentQuestion[] = [];
let lastRaw: string | null = null;
let lastSnapshot: RecentQuestion[] = EMPTY_RECENT_QUESTIONS;

export type RecentQuestion = {
  id: string;
  text: string;
  createdAt: string;
};

export function addRecentQuestion(text: string) {
  if (typeof window === "undefined") {
    return;
  }
  const trimmed = text.trim();
  if (!trimmed) {
    return;
  }
  const current = readRecentQuestions();
  const withoutDuplicate = current.filter((item) => item.text !== trimmed);
  const next = [
    {
      id: `rq_${Date.now().toString(36)}`,
      text: trimmed,
      createdAt: new Date().toISOString(),
    },
    ...withoutDuplicate,
  ].slice(0, MAX_RECENT);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function useRecentQuestions(): RecentQuestion[] {
  return useSyncExternalStore(
    subscribe,
    readRecentQuestions,
    getServerRecentQuestions,
  );
}

function subscribe(callback: () => void) {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) {
      callback();
    }
  };
  window.addEventListener(CHANGE_EVENT, callback);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, callback);
    window.removeEventListener("storage", onStorage);
  };
}

function readRecentQuestions(): RecentQuestion[] {
  if (typeof window === "undefined") {
    return EMPTY_RECENT_QUESTIONS;
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (raw === lastRaw) {
    return lastSnapshot;
  }
  lastRaw = raw;
  if (!raw) {
    lastSnapshot = EMPTY_RECENT_QUESTIONS;
    return lastSnapshot;
  }
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      lastSnapshot = EMPTY_RECENT_QUESTIONS;
      return lastSnapshot;
    }
    lastSnapshot = parsed.filter(isRecentQuestion).slice(0, MAX_RECENT);
    return lastSnapshot;
  } catch {
    lastSnapshot = EMPTY_RECENT_QUESTIONS;
    return lastSnapshot;
  }
}

function getServerRecentQuestions(): RecentQuestion[] {
  return EMPTY_RECENT_QUESTIONS;
}

function isRecentQuestion(value: unknown): value is RecentQuestion {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.text === "string" &&
    typeof candidate.createdAt === "string"
  );
}
