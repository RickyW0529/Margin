"use client";

/**
 * @fileoverview Expand persisted Agent artifacts inside chat answers.
 */

import { useEffect, useState } from "react";

import {
  ArtifactDetailView,
  formatArtifactType,
} from "@/components/agent-artifact-renderers";
import {
  fetchAgentArtifact,
  type AgentArtifactDetail,
  type AgentArtifactSummary,
} from "@/lib/api";
import type { UiLanguage } from "@/lib/i18n";

type AgentArtifactPanelProps = {
  artifacts: AgentArtifactSummary[];
  fetchArtifact?: (artifactId: string) => Promise<AgentArtifactDetail>;
  language: UiLanguage;
};

type ArtifactState =
  | { detail: AgentArtifactDetail; status: "loaded" }
  | { status: "error" }
  | { status: "loading" };

/** Renders expandable persisted Context Store artifacts for one assistant answer. */
export function AgentArtifactPanel({
  artifacts,
  fetchArtifact = fetchAgentArtifact,
  language,
}: AgentArtifactPanelProps) {
  const [artifactState, setArtifactState] = useState<Record<string, ArtifactState>>(
    {},
  );

  useEffect(() => {
    if (typeof window === "undefined" || artifacts.length === 0) {
      return () => undefined;
    }
    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      setArtifactState((current) => {
        const next = { ...current };
        for (const artifact of artifacts) {
          if (!next[artifact.artifact_id]) {
            next[artifact.artifact_id] = { status: "loading" };
          }
        }
        return next;
      });
      for (const artifact of artifacts) {
        void fetchArtifact(artifact.artifact_id)
          .then((detail) => {
            if (cancelled) {
              return;
            }
            setArtifactState((current) => ({
              ...current,
              [artifact.artifact_id]: { detail, status: "loaded" },
            }));
          })
          .catch(() => {
            if (cancelled) {
              return;
            }
            setArtifactState((current) => ({
              ...current,
              [artifact.artifact_id]: { status: "error" },
            }));
          });
      }
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [artifacts, fetchArtifact]);

  if (artifacts.length === 0) {
    return null;
  }

  return (
    <div className="mt-5 grid gap-3">
      {artifacts.map((artifact) => {
        const state = artifactState[artifact.artifact_id] ?? { status: "loading" };
        return (
          <section
            key={artifact.artifact_id}
            className="overflow-hidden rounded-md border border-border bg-card text-foreground"
          >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-3 py-2">
              <div className="grid gap-0.5">
                <h3 className="text-sm font-medium">
                  {formatArtifactType(artifact.artifact_type, language)}
                </h3>
                <p className="text-xs text-muted-foreground">
                  {artifact.producer_agent}
                </p>
              </div>
              <code className="max-w-full truncate rounded border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground">
                {artifact.payload_hash}
              </code>
            </div>
            <div className="p-3">
              {state.status === "loading" ? (
                <p className="text-sm text-muted-foreground">
                  {language === "zh" ? "正在载入产物..." : "Loading artifact..."}
                </p>
              ) : state.status === "error" ? (
                <p className="text-sm text-negative" role="alert">
                  {language === "zh"
                    ? "产物载入失败"
                    : "Failed to load artifact"}
                </p>
              ) : (
                <ArtifactDetailView detail={state.detail} language={language} />
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
