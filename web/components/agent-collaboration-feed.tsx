"use client";

/**
 * @fileoverview Chat-style Agent collaboration progress for dashboard refreshes.
 */

import { Check, Clock3, LoaderCircle, XCircle } from "lucide-react";

import Lanyard from "@/components/lanyard";
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
  progress: number;
  state: RefreshRunNodeState;
  status: string;
  time: string | null;
};

type AgentCollaborationFeedProps = {
  run: ResearchRunDetailV2 | null;
};

/** Renders Agent progress as a group-chat style collaboration timeline. */
export function AgentCollaborationFeed({ run }: AgentCollaborationFeedProps) {
  const items = visibleConversationItems(buildConversationItems(run), run);

  return (
    <div
      className="max-h-[68vh] overflow-y-auto rounded-lg border border-border bg-muted/20 p-4"
      data-testid="agent-collaboration-feed"
    >
      <div className="grid gap-4">
        {items.map((item) => (
          <AgentConversationBubble item={item} key={item.id} />
        ))}
      </div>
    </div>
  );
}

function AgentConversationBubble({ item }: { item: AgentConversationItem }) {
  const tone = bubbleTone(item.state);
  return (
    <article
      className={cn(
        "grid gap-3 rounded-lg border bg-card p-3 shadow-sm transition md:grid-cols-[112px_minmax(0,1fr)]",
        tone.border,
      )}
      data-agent-state={item.state}
      data-testid={`agent-message-${item.id}`}
    >
      <div className="grid justify-items-center">
        <Lanyard
          compact={item.state !== "active" && item.state !== "waiting"}
          gravity={[0, -40, 0]}
          label={shortAgentLabel(item.owner)}
          name={agentDisplayName(item.owner)}
          position={[0, 0, item.state === "active" ? 24 : 18]}
          state={item.state}
        />
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("grid size-7 place-items-center rounded-full", tone.icon)}>
            <StateIcon state={item.state} />
          </span>
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
        <div className="mt-3 rounded-lg bg-muted/70 px-3 py-2 text-sm leading-relaxed text-foreground">
          {item.message}
        </div>
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
            <span>{item.status}</span>
            <span>{item.time ? formatDate(item.time) : "--"}</span>
          </div>
          <div
            aria-label={`${item.label} progress`}
            aria-valuemax={100}
            aria-valuemin={0}
            aria-valuenow={item.progress}
            className="h-2 overflow-hidden rounded-full bg-muted"
            role="progressbar"
          >
            <div
              className={cn("h-full rounded-full transition-all duration-500", tone.bar)}
              style={{ width: `${item.progress}%` }}
            />
          </div>
        </div>
      </div>
    </article>
  );
}

function buildConversationItems(run: ResearchRunDetailV2 | null): AgentConversationItem[] {
  const nodes = buildRefreshRunNodes(run);
  const mainState = mainDispatchState(run, nodes);
  return [
    {
      id: "main_agent_dispatch",
      label: "任务分配",
      message:
        mainState === "completed"
          ? "MainAgent 已完成研究任务拆分，专家 Agent 正在按顺序协作。"
          : "MainAgent 正在读取任务范围并分配数据检查、量化、新闻和复核任务。",
      owner: "MainAgent",
      progress: progressForState(mainState),
      state: mainState,
      status: mainState === "completed" ? "assigned" : "dispatching",
      time: run ? null : null,
    },
    ...nodes.map(nodeToConversationItem),
  ];
}

function nodeToConversationItem(node: RefreshRunNode): AgentConversationItem {
  return {
    id: node.id,
    label: node.label,
    message: messageForNode(node),
    owner: node.owner,
    progress: progressForState(node.state),
    state: node.state,
    status: node.errorCode ?? node.status,
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

function mainDispatchState(
  run: ResearchRunDetailV2 | null,
  nodes: RefreshRunNode[],
): RefreshRunNodeState {
  if (!run) {
    return "pending";
  }
  if (nodes.some((node) => node.state !== "pending")) {
    return "completed";
  }
  return "active";
}

function messageForNode(node: RefreshRunNode): string {
  if (node.state === "completed") {
    return `${agentDisplayName(node.owner)} 已完成「${node.label}」。`;
  }
  if (node.state === "active" || node.state === "queued") {
    return `${agentDisplayName(node.owner)} 正在处理「${node.label}」。`;
  }
  if (node.state === "waiting") {
    return `${agentDisplayName(node.owner)} 正在等待外部资源或预算恢复。`;
  }
  if (node.state === "failed") {
    return `${agentDisplayName(node.owner)} 在「${node.label}」中遇到阻断。`;
  }
  return `${agentDisplayName(node.owner)} 等待接收「${node.label}」任务。`;
}

function progressForState(state: RefreshRunNodeState): number {
  if (state === "completed") {
    return 100;
  }
  if (state === "active") {
    return 68;
  }
  if (state === "waiting") {
    return 52;
  }
  if (state === "queued") {
    return 32;
  }
  if (state === "failed") {
    return 100;
  }
  return 6;
}

function agentDisplayName(owner: string): string {
  const labels: Record<string, string> = {
    Dashboard: "Dashboard",
    DataInspectionAgent: "数据检查 Agent",
    MainAgent: "主 Agent",
    NewsAcquisitionAgent: "新闻研报 Agent",
    QuantAgent: "量化 Agent",
    StockAnalystAgent: "股票分析 Agent",
  };
  return labels[owner] ?? owner;
}

function shortAgentLabel(owner: string): string {
  const labels: Record<string, string> = {
    Dashboard: "DB",
    DataInspectionAgent: "DI",
    MainAgent: "MA",
    NewsAcquisitionAgent: "NA",
    QuantAgent: "QA",
    StockAnalystAgent: "SA",
  };
  return labels[owner] ?? owner.slice(0, 2).toUpperCase();
}

function StateIcon({ state }: { state: RefreshRunNodeState }) {
  if (state === "completed") {
    return <Check className="size-3.5" />;
  }
  if (state === "failed") {
    return <XCircle className="size-3.5" />;
  }
  if (state === "active" || state === "waiting") {
    return <LoaderCircle className="size-3.5" />;
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
      bar: "bg-positive",
      border: "border-positive-soft",
      icon: "bg-positive text-white",
    };
  }
  if (state === "active") {
    return {
      badge: "bg-accent/10 text-accent",
      bar: "bg-accent",
      border: "border-accent/30",
      icon: "bg-accent text-white",
    };
  }
  if (state === "waiting" || state === "queued") {
    return {
      badge: "bg-caution-soft text-caution",
      bar: "bg-caution",
      border: "border-caution-soft",
      icon: "bg-caution text-white",
    };
  }
  if (state === "failed") {
    return {
      badge: "bg-negative-soft text-negative",
      bar: "bg-negative",
      border: "border-negative-soft",
      icon: "bg-negative text-white",
    };
  }
  return {
    badge: "bg-muted text-muted-foreground",
    bar: "bg-muted-foreground",
    border: "border-border",
    icon: "bg-muted-foreground text-white",
  };
}
