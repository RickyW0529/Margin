"use client";

/**
 * @fileoverview Activity-line Agent collaboration progress for dashboard refreshes.
 */

import { Check, Clock3, LoaderCircle, XCircle } from "lucide-react";

import type { ResearchRunDetailV2 } from "@/lib/api";
import {
  buildRefreshRunNodes,
  isRefreshRunTerminalState,
  type RefreshRunNode,
  type RefreshRunNodeState,
} from "@/lib/refresh-run-graph";
import { cn, formatDate } from "@/lib/utils";

type AgentConversationItem = {
  id: string;
  label: string;
  message: string;
  owner: string;
  breakpoint: string | null;
  state: RefreshRunNodeState;
  time: string | null;
};

type AgentCollaborationFeedProps = {
  run: ResearchRunDetailV2 | null;
};

/** Renders Agent progress as a compact collaboration timeline. */
export function AgentCollaborationFeed({ run }: AgentCollaborationFeedProps) {
  const items = visibleConversationItems(buildConversationItems(run), run);

  return (
    <div
      className="max-h-[68vh] overflow-y-auto rounded-lg border border-border bg-muted/20 p-4"
      data-testid="agent-collaboration-feed"
    >
      <div className="grid">
        {items.map((item, index) => (
          <AgentActivityRow
            isLast={index === items.length - 1}
            item={item}
            key={item.id}
          />
        ))}
      </div>
    </div>
  );
}

function AgentActivityRow({
  isLast,
  item,
}: {
  isLast: boolean;
  item: AgentConversationItem;
}) {
  const tone = bubbleTone(item.state);
  return (
    <article
      className="relative grid grid-cols-[2rem_minmax(0,1fr)] gap-3 pb-5 last:pb-0"
      data-agent-state={item.state}
      data-testid={`agent-activity-${item.id}`}
    >
      <div className="relative flex justify-center">
        {!isLast ? (
          <span
            aria-hidden="true"
            className="absolute top-8 h-[calc(100%-0.25rem)] w-px bg-border"
          />
        ) : null}
        <span
          className={cn(
            "relative z-10 grid size-8 place-items-center rounded-full shadow-sm",
            tone.icon,
          )}
        >
          <StateIcon state={item.state} />
        </span>
      </div>
      <div className={cn("min-w-0 rounded-lg border bg-card p-3", tone.border)}>
        <div className="flex flex-wrap items-start gap-2">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-foreground">
              {agentDisplayName(item.owner)}
            </h3>
            <p className="truncate text-xs text-muted-foreground">{item.label}</p>
          </div>
          <span className={cn("ml-auto rounded-full px-2.5 py-1 text-xs", tone.badge)}>
            {stateText(item.state)}
          </span>
        </div>
        <p className="mt-3 text-sm leading-relaxed text-foreground">{item.message}</p>
        {item.breakpoint ? (
          <p className="mt-2 text-xs text-caution">
            {humanizeBreakpoint(item.breakpoint)}
          </p>
        ) : null}
        {item.time ? (
          <p className="mt-2 text-[11px] text-muted-foreground">{formatDate(item.time)}</p>
        ) : null}
      </div>
    </article>
  );
}

function buildConversationItems(run: ResearchRunDetailV2 | null): AgentConversationItem[] {
  const nodes = buildRefreshRunNodes(run);
  return nodes.map(nodeToConversationItem);
}

function nodeToConversationItem(node: RefreshRunNode): AgentConversationItem {
  return {
    id: node.id,
    label: node.label,
    breakpoint: node.errorCode,
    message: messageForNode(node),
    owner: node.owner,
    state: node.state,
    time: node.finishedAt ?? node.startedAt,
  };
}

function visibleConversationItems(
  items: AgentConversationItem[],
  run: ResearchRunDetailV2 | null,
): AgentConversationItem[] {
  if (!run || isRefreshRunTerminalState(run.status)) {
    return items;
  }
  const activeIndex = items.findIndex(
    (item) =>
      item.state === "active" ||
      item.state === "waiting" ||
      item.state === "queued",
  );
  if (activeIndex >= 0) {
    return items.slice(0, Math.min(items.length, activeIndex + 2));
  }
  const firstPendingIndex = items.findIndex((item) => item.state === "pending");
  if (firstPendingIndex >= 0) {
    return items.slice(0, Math.min(items.length, firstPendingIndex + 1));
  }
  return items;
}

function messageForNode(node: RefreshRunNode): string {
  if (node.state === "completed") {
    return `${agentDisplayName(node.owner)} 已完成「${node.label}」。`;
  }
  if (node.state === "active" || node.state === "queued") {
    return `${agentDisplayName(node.owner)} 正在处理「${node.label}」。`;
  }
  if (node.state === "waiting") {
    return node.errorCode
      ? `${agentDisplayName(node.owner)} 在「${node.label}」等待重试。`
      : `${agentDisplayName(node.owner)} 正在等待外部资源恢复。`;
  }
  if (node.state === "failed") {
    return `${agentDisplayName(node.owner)} 在「${node.label}」中失败。`;
  }
  return `${agentDisplayName(node.owner)} 等待接收「${node.label}」任务。`;
}

function humanizeBreakpoint(code: string): string {
  return code.replace(/[_-]+/g, " ").trim();
}

function agentDisplayName(owner: string): string {
  const labels: Record<string, string> = {
    Dashboard: "Dashboard",
    DataInspectionAgent: "数据检查",
    EarningsCatalystWorker: "财报催化 Worker",
    MainAgent: "主 Agent",
    MLQuantWorker: "ML 量化 Worker",
    NewsAcquisitionAgent: "新闻研报",
    QuantAgent: "量化",
    RecommendationFusionWorker: "融合 Worker",
    ResearchPublisher: "推荐发布",
    StockAnalystAgent: "股票分析",
  };
  return labels[owner] ?? owner;
}

function StateIcon({ state }: { state: RefreshRunNodeState }) {
  if (state === "completed") {
    return <Check className="size-3.5" />;
  }
  if (state === "failed") {
    return <XCircle className="size-3.5" />;
  }
  if (state === "active" || state === "waiting") {
    return <LoaderCircle className="size-3.5 animate-spin" />;
  }
  return <Clock3 className="size-3.5" />;
}

function stateText(state: RefreshRunNodeState): string {
  if (state === "completed") {
    return "已完成";
  }
  if (state === "active") {
    return "进行中";
  }
  if (state === "waiting") {
    return "等待中";
  }
  if (state === "queued") {
    return "已接收";
  }
  if (state === "failed") {
    return "失败";
  }
  return "未开始";
}

function bubbleTone(state: RefreshRunNodeState) {
  if (state === "completed") {
    return {
      badge: "bg-positive-soft text-positive",
      border: "border-positive-soft",
      icon: "bg-positive text-white",
    };
  }
  if (state === "active") {
    return {
      badge: "bg-accent/10 text-accent",
      border: "border-accent/30",
      icon: "bg-accent text-white",
    };
  }
  if (state === "waiting" || state === "queued") {
    return {
      badge: "bg-caution-soft text-caution",
      border: "border-caution-soft",
      icon: "bg-caution text-white",
    };
  }
  if (state === "failed") {
    return {
      badge: "bg-negative-soft text-negative",
      border: "border-negative-soft",
      icon: "bg-negative text-white",
    };
  }
  return {
    badge: "bg-muted text-muted-foreground",
    border: "border-border",
    icon: "bg-muted-foreground text-white",
  };
}
