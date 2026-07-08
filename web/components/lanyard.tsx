"use client";

/**
 * @fileoverview Lightweight Agent lanyard badge used by the collaboration feed.
 */

import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

type LanyardVisualState =
  | "active"
  | "completed"
  | "failed"
  | "pending"
  | "queued"
  | "waiting";

type LanyardProps = {
  backImage?: string | null;
  className?: string;
  compact?: boolean;
  fov?: number;
  frontImage?: string | null;
  gravity?: [number, number, number];
  imageFit?: "cover" | "contain";
  label: string;
  lanyardImage?: string | null;
  lanyardWidth?: number;
  name: string;
  position?: [number, number, number];
  state: LanyardVisualState;
  transparent?: boolean;
};

/** Renders a hanging role badge with the same public props as the 3D lanyard. */
export default function Lanyard({
  backImage = null,
  className,
  compact = false,
  fov = 20,
  frontImage = null,
  gravity = [0, -40, 0],
  imageFit = "cover",
  label,
  lanyardImage = null,
  lanyardWidth = 1,
  name,
  position = [0, 0, 20],
  state,
  transparent = true,
}: LanyardProps) {
  const tone = lanyardTone(state);
  const style = {
    "--lanyard-band-width": `${Math.max(2, lanyardWidth * 6)}px`,
    "--lanyard-drop-distance": `${Math.min(72, Math.abs(gravity[1]) * 1.2)}px`,
    "--lanyard-image-fit": imageFit,
    "--lanyard-perspective": `${Math.max(12, fov) * 12}px`,
    "--lanyard-z-depth": `${position[2]}px`,
    backgroundColor: transparent ? "transparent" : "var(--card)",
  } as CSSProperties & Record<string, string>;

  return (
    <div
      className={cn(
        "lanyard-wrapper",
        compact ? "lanyard-wrapper-compact" : "",
        state === "active" || state === "waiting" ? "lanyard-wrapper-live" : "",
        className,
      )}
      data-state={state}
      style={style}
    >
      <div
        aria-label={`${label} ${name}`}
        className="lanyard-band"
        data-testid={`agent-lanyard-band-${label}`}
        style={
          lanyardImage
            ? { backgroundImage: `url(${lanyardImage})` }
            : undefined
        }
      />
      <div
        className={cn(
          "lanyard-card",
          tone.card,
          state === "active" || state === "waiting"
            ? "lanyard-card-drop"
            : "",
        )}
        data-testid={`agent-lanyard-${label}`}
      >
        <div
          className={cn("lanyard-card-face", frontImage ? "" : tone.face)}
          style={
            frontImage
              ? {
                  backgroundImage: `url(${frontImage})`,
                  backgroundSize: imageFit,
                }
              : undefined
          }
        >
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
          <strong className="mt-1 line-clamp-2 text-center text-xs font-semibold text-foreground">
            {name}
          </strong>
        </div>
        {backImage ? (
          <div
            aria-hidden="true"
            className="lanyard-card-back"
            style={{ backgroundImage: `url(${backImage})`, backgroundSize: imageFit }}
          />
        ) : null}
      </div>
    </div>
  );
}

function lanyardTone(state: LanyardVisualState) {
  if (state === "completed") {
    return {
      card: "border-positive-soft bg-positive-soft",
      face: "bg-white/70",
    };
  }
  if (state === "active") {
    return {
      card: "border-accent/30 bg-accent/10 shadow-[0_10px_30px_rgba(0,112,243,0.18)]",
      face: "bg-white",
    };
  }
  if (state === "waiting" || state === "queued") {
    return {
      card: "border-caution-soft bg-caution-soft",
      face: "bg-white/75",
    };
  }
  if (state === "failed") {
    return {
      card: "border-negative-soft bg-negative-soft",
      face: "bg-white/75",
    };
  }
  return {
    card: "border-border bg-muted/60 opacity-70",
    face: "bg-card",
  };
}
