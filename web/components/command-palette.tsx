"use client";

import {
  MessageCircle,
  MonitorUp,
  Search,
  Settings,
  Settings2,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useLanguage } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type CommandItem = {
  href: string;
  label: string;
  group: string;
  icon: React.ElementType;
  keywords?: string;
};

/** Global Cmd/Ctrl+K navigation palette. */
export function CommandPalette() {
  const router = useRouter();
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const items = useMemo<CommandItem[]>(
    () => [
      {
        href: "/",
        label: t("navAsk"),
        group: "Navigate",
        icon: MessageCircle,
        keywords: "chat home ask qna",
      },
      {
        href: "/dashboard",
        label: t("navDashboard"),
        group: "Navigate",
        icon: MonitorUp,
        keywords: "recommend candidates",
      },
      {
        href: "/settings",
        label: t("navSettings"),
        group: "Navigate",
        icon: Settings,
        keywords: "config",
      },
      {
        href: "/settings/providers",
        label: t("settingsProviders"),
        group: "Settings",
        icon: Settings2,
        keywords: "llm secret api key",
      },
      {
        href: "/settings/data",
        label: t("settingsData"),
        group: "Settings",
        icon: Settings2,
      },
      {
        href: "/settings/schedule",
        label: t("settingsSchedule"),
        group: "Settings",
        icon: Settings2,
      },
      {
        href: "/settings/strategy",
        label: t("settingsStrategy"),
        group: "Settings",
        icon: Settings2,
      },
    ],
    [t],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return items;
    }
    return items.filter((item) =>
      `${item.label} ${item.group} ${item.keywords ?? ""}`
        .toLowerCase()
        .includes(q),
    );
  }, [items, query]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        const nextOpen = !open;
        setOpen(nextOpen);
        setActiveIndex(0);
        if (!nextOpen) {
          setQuery("");
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const run = (href: string) => {
    setOpen(false);
    setQuery("");
    router.push(href);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        setActiveIndex(0);
        if (!next) {
          setQuery("");
        }
      }}
    >
      <DialogContent className="max-w-lg gap-0 overflow-hidden p-0">
        <DialogHeader className="sr-only">
          <DialogTitle>Command palette</DialogTitle>
          <DialogDescription>Jump to pages quickly</DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2 border-b border-border/80 px-4">
          <Search className="size-4 text-muted-foreground" />
          <Input
            autoFocus
            className="h-12 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
            placeholder={t("languageLabel") === "Language" ? "Search…" : "搜索页面…"}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex((index) =>
                  Math.min(index + 1, Math.max(filtered.length - 1, 0)),
                );
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex((index) => Math.max(index - 1, 0));
              } else if (event.key === "Enter" && filtered[activeIndex]) {
                event.preventDefault();
                run(filtered[activeIndex].href);
              }
            }}
          />
          <kbd className="hidden rounded-md border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground sm:inline">
            esc
          </kbd>
        </div>
        <div className="max-h-80 overflow-y-auto p-2">
          {filtered.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-muted-foreground">
              No results
            </p>
          ) : (
            filtered.map((item, index) => {
              const Icon = item.icon;
              return (
                <button
                  key={`${item.href}-${item.label}`}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition-colors",
                    index === activeIndex
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/70 hover:text-foreground",
                  )}
                  type="button"
                  onClick={() => run(item.href)}
                  onMouseEnter={() => setActiveIndex(index)}
                >
                  <Icon className="size-4 shrink-0 opacity-70" />
                  <span className="min-w-0 flex-1 truncate font-medium text-foreground">
                    {item.label}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {item.group}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
