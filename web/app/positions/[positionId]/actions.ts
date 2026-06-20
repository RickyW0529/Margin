/**
 * @fileoverview Server actions for position monitoring and review.
 * Handles position evaluation updates and manual review submissions.
 */

"use server";

import { revalidatePath } from "next/cache";

import {
  createPositionReview,
  evaluatePositionMonitoring,
  type ReviewDecision,
} from "@/lib/api";

/**
 * Submits an updated monitoring evaluation for a position.
 * @param positionId - The position identifier.
 * @param formData - Form values containing portfolio_id, price, exposure, and failure flags.
 */
export async function evaluatePositionAction(
  positionId: string,
  formData: FormData,
) {
  const portfolioId = requiredText(formData, "portfolio_id");

  await evaluatePositionMonitoring(positionId, {
    portfolio_id: portfolioId,
    current_price: optionalNumber(formData, "current_price"),
    evidence_refs: splitList(optionalText(formData, "evidence_refs")),
    model_rank_delta: optionalNumber(formData, "model_rank_delta"),
    industry_exposure: optionalNumber(formData, "industry_exposure"),
    strategy_failure: formData.get("strategy_failure") === "on",
  });

  revalidatePath(`/positions/${positionId}`);
}

/**
 * Creates a manual review record for a position.
 * @param positionId - The position identifier.
 * @param formData - Form values containing portfolio_id, decision, rationale, and optional alert_id.
 */
export async function createPositionReviewAction(
  positionId: string,
  formData: FormData,
) {
  const portfolioId = requiredText(formData, "portfolio_id");
  const rationale = requiredText(formData, "rationale");

  await createPositionReview(positionId, {
    portfolio_id: portfolioId,
    alert_id: optionalText(formData, "alert_id"),
    decision: reviewDecision(formData),
    rationale,
  });

  revalidatePath(`/positions/${positionId}`);
}

function requiredText(formData: FormData, key: string): string {
  const value = optionalText(formData, key);
  if (!value) {
    throw new Error(`${key} is required`);
  }
  return value;
}

function optionalText(formData: FormData, key: string): string | null {
  const value = formData.get(key);
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function optionalNumber(formData: FormData, key: string): number | null {
  const value = optionalText(formData, key);
  if (!value) {
    return null;
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function splitList(value: string | null): string[] {
  if (!value) {
    return [];
  }
  return value
    .split(/[\s,;，；]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function reviewDecision(formData: FormData): ReviewDecision {
  const value = optionalText(formData, "decision");
  if (
    value === "hold" ||
    value === "reduce" ||
    value === "exit" ||
    value === "watch" ||
    value === "ignore"
  ) {
    return value;
  }
  return "watch";
}
