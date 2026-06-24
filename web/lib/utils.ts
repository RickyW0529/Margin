/** Shared frontend utilities: class merging and value formatting helpers. */

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes with conflict resolution. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Format an ISO timestamp as MM/DD HH:mm. */
export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

/** Format an ISO timestamp as yyyy/MM/dd. */
export function formatDateShort(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(parsed);
}

/** Format a numeric score with one decimal. */
export function formatScore(value: number | null | undefined): string {
  if (value == null) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 1,
  }).format(value);
}

/** Format a 0-1 ratio as a percentage. */
export function formatPercent(value: number | null | undefined): string {
  if (value == null) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", {
    style: "percent",
    maximumFractionDigits: 0,
  }).format(value);
}

/** Format a signed percentage (already in percent units, e.g. 23.1 -> +23.1%). */
export function formatSignedPercent(value: number | null | undefined): string {
  if (value == null) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 1,
  }).format(value)}%`;
}

/** Format a generic number with configurable decimals. */
export function formatNumber(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value == null) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: digits,
  }).format(value);
}
