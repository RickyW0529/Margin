/**
 * @fileoverview Server action for submitting feedback on a research item.
 */

"use server";

import { revalidatePath } from "next/cache";

import { createResearchItemFeedback, type FeedbackType } from "@/lib/api";

/**
 * Records feedback for a research item and refreshes the item page.
 * @param itemId - The research item identifier.
 * @param formData - Form values containing feedback_type and an optional comment.
 */
export async function createResearchFeedbackAction(
  itemId: string,
  formData: FormData,
) {
  await createResearchItemFeedback(itemId, {
    feedback_type: feedbackType(formData),
    comment: optionalText(formData, "comment") ?? "",
  });

  revalidatePath(`/research/items/${itemId}`);
}

function optionalText(formData: FormData, key: string): string | null {
  const value = formData.get(key);
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function feedbackType(formData: FormData): FeedbackType {
  const value = optionalText(formData, "feedback_type");
  if (
    value === "accept" ||
    value === "reject" ||
    value === "watch" ||
    value === "comment"
  ) {
    return value;
  }
  return "comment";
}
