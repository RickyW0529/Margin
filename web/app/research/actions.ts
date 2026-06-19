"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { createResearchRun } from "@/lib/api";

export async function createResearchRunAction(formData: FormData) {
  const strategyId = requiredText(formData, "strategy_id");
  const versionId = requiredText(formData, "version_id");
  const portfolioId = optionalText(formData, "portfolio_id");
  const symbols = splitSymbols(optionalText(formData, "symbols"));

  const run = await createResearchRun({
    strategy_id: strategyId,
    version_id: versionId,
    portfolio_id: portfolioId,
    symbols: symbols.length > 0 ? symbols : null,
  });

  revalidatePath("/research");
  redirect(`/research/runs/${run.run_id}`);
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

function splitSymbols(value: string | null): string[] {
  if (!value) {
    return [];
  }
  return value
    .split(/[\s,;，；]+/)
    .map((symbol) => symbol.trim())
    .filter(Boolean);
}
