/**
 * @fileoverview Question-first home page for the Margin workspace.
 */

import { HomeResearchPage } from "@/components/home-research-page";

export const dynamic = "force-dynamic";

/** Home page focused on natural-language research questions. */
export default async function HomePage() {
  return <HomeResearchPage />;
}
