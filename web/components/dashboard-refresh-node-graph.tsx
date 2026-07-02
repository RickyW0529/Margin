"use client";

/**
 * @fileoverview React Flow node graph for the latest dashboard refresh run.
 */

import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  Check,
  Clock3,
  LoaderCircle,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useMemo } from "react";

import type { ResearchRunDetailV2 } from "@/lib/api";
import {
  buildRefreshRunNodes,
  type RefreshRunNode,
  type RefreshRunNodeState,
} from "@/lib/refresh-run-graph";
import { cn, formatDate } from "@/lib/utils";

type RefreshFlowNodeData = RefreshRunNode & {
  order: number;
};
type RefreshFlowNode = Node<RefreshFlowNodeData, "refreshStatus">;

const nodeTypes = {
  refreshStatus: RefreshStatusNode,
};

const STATE_ICONS: Record<RefreshRunNodeState, LucideIcon> = {
  active: LoaderCircle,
  completed: Check,
  failed: XCircle,
  pending: Clock3,
  queued: Clock3,
  waiting: Clock3,
};

type DashboardRefreshNodeGraphProps = {
  run: ResearchRunDetailV2 | null;
};

/** Renders the newest refresh run as a fixed-step React Flow graph. */
export function DashboardRefreshNodeGraph({
  run,
}: DashboardRefreshNodeGraphProps) {
  const stableNodeTypes = useMemo(() => nodeTypes, []);
  const graphNodes = buildRefreshRunNodes(run);
  const nodes = graphNodes.map(toFlowNode);
  const edges = graphNodes.slice(0, -1).map((node, index) =>
    toFlowEdge(node, graphNodes[index + 1]),
  );

  return (
    <div className="h-[420px] overflow-hidden rounded-lg border border-border bg-muted/20">
      <ReactFlow
        colorMode="light"
        edgesFocusable={false}
        elementsSelectable={false}
        edges={edges}
        fitView
        fitViewOptions={{ maxZoom: 1.05, padding: 0.18 }}
        maxZoom={1.3}
        minZoom={0.45}
        nodes={nodes}
        nodesConnectable={false}
        nodesDraggable={false}
        nodesFocusable={false}
        nodeTypes={stableNodeTypes}
        panOnDrag
        panOnScroll
        proOptions={{ hideAttribution: true }}
        zoomOnDoubleClick={false}
        zoomOnScroll={false}
      >
        <Background
          color="var(--border)"
          gap={18}
          size={1}
          variant={BackgroundVariant.Dots}
        />
        <Controls position="bottom-right" showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

function RefreshStatusNode({ data }: NodeProps<RefreshFlowNode>) {
  const tone = stateTone(data.state);
  const Icon = STATE_ICONS[data.state];
  const pulse = data.state === "active" || data.state === "waiting";

  return (
    <div
      aria-label={`${data.label}，${stateText(data.state)}`}
      className={cn(
        "w-[172px] rounded-lg border bg-card px-3 py-2.5 shadow-sm transition",
        tone.container,
        pulse ? "animate-pulse ring-2" : "",
      )}
      data-node-state={data.state}
      data-testid={`refresh-node-${data.id}`}
    >
      <Handle
        className="opacity-0"
        isConnectable={false}
        position={Position.Left}
        type="target"
      />
      <div className="flex items-start gap-2.5">
        <span
          className={cn(
            "grid size-7 shrink-0 place-items-center rounded-full",
            tone.icon,
          )}
        >
          <Icon className="size-3.5" />
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="tabular text-[10px] font-medium text-muted-foreground">
              {String(data.order + 1).padStart(2, "0")}
            </span>
            <strong className={cn("truncate text-sm font-semibold", tone.text)}>
              {data.label}
            </strong>
          </div>
          <p className={cn("mt-1 text-xs", tone.text)}>
            {stateText(data.state)}
          </p>
          <p className="mt-1 truncate text-[11px] text-muted-foreground">
            {data.errorCode ?? data.status}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {formatNodeTime(data)}
          </p>
        </div>
      </div>
      <Handle
        className="opacity-0"
        isConnectable={false}
        position={Position.Right}
        type="source"
      />
    </div>
  );
}

function toFlowNode(node: RefreshRunNode, index: number): RefreshFlowNode {
  const column = index % 4;
  const row = Math.floor(index / 4);
  return {
    data: { ...node, order: index },
    id: node.id,
    position: {
      x: column * 240,
      y: row * 136,
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    type: "refreshStatus",
  };
}

function toFlowEdge(source: RefreshRunNode, target: RefreshRunNode): Edge {
  const active = source.state === "active" || target.state === "active";
  const completed = source.state === "completed" && target.state === "completed";
  return {
    animated: active,
    id: `${source.id}-${target.id}`,
    markerEnd: {
      color: completed ? "var(--positive)" : "var(--muted-foreground)",
      type: MarkerType.ArrowClosed,
    },
    source: source.id,
    style: {
      stroke: active
        ? "var(--accent)"
        : completed
          ? "var(--positive)"
          : "var(--border)",
      strokeWidth: active ? 2.5 : 1.5,
    },
    target: target.id,
    type: "smoothstep",
  };
}

function stateTone(state: RefreshRunNodeState) {
  if (state === "completed") {
    return {
      container: "border-positive-soft bg-positive-soft",
      icon: "bg-positive text-white",
      text: "text-positive",
    };
  }
  if (state === "active") {
    return {
      container: "border-accent/30 bg-accent/10 ring-accent/20",
      icon: "bg-accent text-white",
      text: "text-accent",
    };
  }
  if (state === "waiting") {
    return {
      container: "border-caution-soft bg-caution-soft ring-caution/20",
      icon: "bg-caution text-white",
      text: "text-caution",
    };
  }
  if (state === "queued") {
    return {
      container: "border-caution-soft bg-caution-soft",
      icon: "bg-caution text-white",
      text: "text-caution",
    };
  }
  if (state === "failed") {
    return {
      container: "border-negative-soft bg-negative-soft",
      icon: "bg-negative text-white",
      text: "text-negative",
    };
  }
  return {
    container: "border-border bg-muted/70",
    icon: "bg-muted-foreground text-white",
    text: "text-muted-foreground",
  };
}

function stateText(state: RefreshRunNodeState): string {
  if (state === "completed") {
    return "已完成";
  }
  if (state === "active") {
    return "运行中";
  }
  if (state === "waiting") {
    return "等待中";
  }
  if (state === "queued") {
    return "排队中";
  }
  if (state === "failed") {
    return "失败";
  }
  return "未开始";
}

function formatNodeTime(node: RefreshFlowNodeData): string {
  if (node.finishedAt) {
    return `完成 ${formatDate(node.finishedAt)}`;
  }
  if (node.state === "queued" && node.startedAt) {
    return `入队 ${formatDate(node.startedAt)}`;
  }
  if (node.startedAt) {
    return `开始 ${formatDate(node.startedAt)}`;
  }
  return "等待调度";
}
