"use client";

/**
 * @fileoverview Lightweight UI language state for the local workspace.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

export type UiLanguage = "zh" | "en";

type LanguageContextValue = {
  language: UiLanguage;
  setLanguage: (language: UiLanguage) => void;
  t: (key: TranslationKey) => string;
};

const STORAGE_KEY = "margin-ui-language";
const LANGUAGE_CHANGE_EVENT = "margin-language-change";

const LanguageContext = createContext<LanguageContextValue | null>(null);

export const TEXT = {
  zh: {
    navAsk: "问答",
    navDashboard: "今日推荐",
    navSettings: "设置",
    navRecent: "最近",
    navRecentEmpty: "暂无最近研究",
    dashboardTitle: "今日推荐",
    dashboardEmpty: "今日暂无推荐。",
    dashboardCount: "推荐",
    dashboardAvgConfidence: "平均置信度",
    dashboardNeedsReview: "需复核",
    dashboardRisk: "风险",
    dashboardConfidence: "置信度",
    dashboardQuantScore: "量化评分",
    dashboardDiscount: "估值折价",
    dashboardDetail: "查看详情",
    dashboardDataComplete: "数据完整",
    dashboardDataMissing: "数据待补齐",
    refreshStart: "启动今日研究",
    refreshRunning: "Agent 研究中",
    refreshLatest: "最近一次 Agent 任务",
    refreshGraphTitle: "Agent 协作进度",
    refreshOpenGraph: "打开 Agent 进度",
    refreshCloseGraph: "收起 Agent 进度",
    refreshLoading: "加载中",
    languageLabel: "语言",
    languageZh: "中文",
    languageEn: "English",
    homeTitle: "今天想研究什么？",
    homeBrandLink: "Margin",
    chatLabel: "投资研究问题",
    chatPlaceholder: "今日推荐股票是什么？",
    chatFollowupPlaceholder: "继续追问",
    chatSend: "发送",
    chatAttach: "添加",
    chatReadonly: "研究智能体只读回答，不触发交易",
    chatThinking: "我先读取当前推荐和分析数据。",
    chatReadingData: "正在读取推荐列表",
    chatDisclaimer: "Margin 也可能会犯错。请核查重要信息。",
    chatError: "暂时无法回答，请稍后再试。",
    chatTrace: "调用记录",
    chatReferences: "参考",
    settingsEyebrow: "设置",
    settingsTitle: "设置",
    settingsProviders: "密钥配置",
    settingsProvidersDesc: "模型、搜索、数据源密钥",
    settingsData: "数据配置",
    settingsDataDesc: "采集窗口与滚动策略",
    settingsScope: "研究范围",
    settingsScopeDesc: "股票池、指数池与指标视图",
    settingsSchedule: "自动研究计划",
    settingsScheduleDesc: "每日自动刷新时间",
    settingsStrategy: "策略配置",
    settingsStrategyDesc: "评分规则、阈值与提示词",
    scheduleTitle: "自动研究计划",
    scheduleBack: "返回设置",
    scheduleCardTitle: "自动研究计划",
    scheduleCardEyebrow: "定时研究",
    scheduleEnabled: "已开启",
    scheduleDisabled: "已关闭",
    scheduleTaskName: "每日股票分析",
    scheduleTaskDesc: "到点后由 MainAgent 调度数据检查、量化分析、新闻获取、股票分析和最终复核。",
    scheduleNext: "下次运行",
    scheduleLast: "上次触发",
    scheduleToggle: "开启每日自动研究",
    scheduleTime: "运行时间",
    scheduleSave: "保存计划",
    scheduleSaved: "计划已保存",
    scheduleError: "保存失败，请检查 API 服务状态。",
    scheduleInvalidTime: "请输入有效时间。",
    evidenceTitle: "证据摘要",
    evidenceEmpty: "暂无证据",
    evidenceCount: "条",
    evidenceLevel: "来源可信度",
    evidenceTechnical: "技术定位",
    evidenceLocator: "定位",
    evidenceSnapshot: "快照",
    evidencePit: "时间点",
    evidenceLinked: "已关联本股票",
    evidenceNeedsReview: "需要人工复核关联股票",
    evidenceOriginal: "原文",
    detailRecommendation: "推荐详情",
    detailConclusion: "研究结论",
    detailConfidence: "置信度",
    detailNoConclusion: "暂无结论",
    detailAiStatus: "智能体状态",
    detailScope: "研究范围",
    detailSnapshot: "快照",
    detailValuation: "价值估算",
    detailValuationReady: "已形成",
    detailValuationMissing: "未形成",
    detailMargin: "安全边际",
    detailValuationState: "当前状态",
    detailValuationUnavailable: "暂未形成估值结论",
    detailIntrinsicValue: "内在价值",
    detailValuationMissingReason: "需要股票分析师完成估值复核后才会展示安全边际。",
    detailQuantTitle: "量化视图",
    detailScreeningStatus: "筛选状态",
    detailDataStatus: "数据状态",
    detailFinalScore: "最终分数",
    detailNoFactors: "暂无因子快照。",
    detailTrendTitle: "关键趋势",
    detailTrendSeries: "条序列",
    detailNoTrends: "暂无趋势数据",
    detailRiskTitle: "风险与复核",
    detailNoRisk: "暂无明显风险标记。",
    detailGuardrailAllow: "研究允许",
    currentStateEyebrow: "状态",
    currentStateTitle: "本轮复核与当前结论",
    currentReview: "本轮复核",
    effectiveAssessment: "当前有效结论",
    currentNoAssessment: "暂无",
    currentNoReason: "本轮未记录延期或拒绝原因",
    currentWorkflow: "工作流",
    freshnessFresh: "有效",
    freshnessStale: "已过期",
    freshnessDeferred: "延期",
    freshnessUnknown: "未知",
  },
  en: {
    navAsk: "Ask",
    navDashboard: "Today",
    navSettings: "Settings",
    navRecent: "Recent",
    navRecentEmpty: "No recent research",
    dashboardTitle: "Today",
    dashboardEmpty: "No recommendations today.",
    dashboardCount: "Recommendations",
    dashboardAvgConfidence: "Average confidence",
    dashboardNeedsReview: "Needs review",
    dashboardRisk: "Risk",
    dashboardConfidence: "Confidence",
    dashboardQuantScore: "Quant score",
    dashboardDiscount: "Valuation discount",
    dashboardDetail: "View detail",
    dashboardDataComplete: "Data complete",
    dashboardDataMissing: "Data incomplete",
    refreshStart: "Start today's research",
    refreshRunning: "Agent research running",
    refreshLatest: "Latest Agent task",
    refreshGraphTitle: "Agent collaboration progress",
    refreshOpenGraph: "Open Agent progress",
    refreshCloseGraph: "Close Agent progress",
    refreshLoading: "Loading",
    languageLabel: "Language",
    languageZh: "中文",
    languageEn: "English",
    homeTitle: "What do you want to research today?",
    homeBrandLink: "Margin",
    chatLabel: "Investment research question",
    chatPlaceholder: "What are today's recommended stocks?",
    chatFollowupPlaceholder: "Ask a follow-up",
    chatSend: "Send",
    chatAttach: "Add",
    chatReadonly: "Read-only research answer. No trades are triggered.",
    chatThinking: "I am reading the current recommendations and analysis data.",
    chatReadingData: "Reading recommendation data",
    chatDisclaimer: "Margin can make mistakes. Check important information.",
    chatError: "Unable to answer right now. Please try again later.",
    chatTrace: "Trace",
    chatReferences: "References",
    settingsEyebrow: "Settings",
    settingsTitle: "Settings",
    settingsProviders: "Provider keys",
    settingsProvidersDesc: "Models, search, and data source keys",
    settingsData: "Data settings",
    settingsDataDesc: "Collection window and rolling policy",
    settingsScope: "Research scope",
    settingsScopeDesc: "Universe, indexes, and indicator views",
    settingsSchedule: "Automation",
    settingsScheduleDesc: "Daily research schedule",
    settingsStrategy: "Strategy settings",
    settingsStrategyDesc: "Scoring rules, thresholds, and prompts",
    scheduleTitle: "Automation",
    scheduleBack: "Back to settings",
    scheduleCardTitle: "Automation",
    scheduleCardEyebrow: "Scheduled research",
    scheduleEnabled: "Enabled",
    scheduleDisabled: "Disabled",
    scheduleTaskName: "Daily stock analysis",
    scheduleTaskDesc: "At the scheduled time, MainAgent coordinates data checks, quant analysis, news acquisition, stock analysis, and final review.",
    scheduleNext: "Next run",
    scheduleLast: "Last triggered",
    scheduleToggle: "Enable daily research",
    scheduleTime: "Run time",
    scheduleSave: "Save",
    scheduleSaved: "Saved",
    scheduleError: "Save failed. Check the API service status.",
    scheduleInvalidTime: "Enter a valid time.",
    evidenceTitle: "Evidence summary",
    evidenceEmpty: "No evidence yet",
    evidenceCount: "items",
    evidenceLevel: "Source level",
    evidenceTechnical: "Technical locator",
    evidenceLocator: "Locator",
    evidenceSnapshot: "Snapshot",
    evidencePit: "Point in time",
    evidenceLinked: "Linked to this stock",
    evidenceNeedsReview: "Needs manual stock-link review",
    evidenceOriginal: "Source",
    detailRecommendation: "Recommendation detail",
    detailConclusion: "Research conclusion",
    detailConfidence: "Confidence",
    detailNoConclusion: "No conclusion yet",
    detailAiStatus: "Agent status",
    detailScope: "Scope",
    detailSnapshot: "Snapshot",
    detailValuation: "Value estimate",
    detailValuationReady: "Ready",
    detailValuationMissing: "Not ready",
    detailMargin: "Margin of safety",
    detailValuationState: "Current state",
    detailValuationUnavailable: "No value estimate yet",
    detailIntrinsicValue: "Intrinsic value",
    detailValuationMissingReason: "The stock analyst must complete valuation review before margin of safety is shown.",
    detailQuantTitle: "Quant view",
    detailScreeningStatus: "Screening status",
    detailDataStatus: "Data status",
    detailFinalScore: "Final score",
    detailNoFactors: "No factor snapshot yet.",
    detailTrendTitle: "Key trends",
    detailTrendSeries: "series",
    detailNoTrends: "No trend data yet",
    detailRiskTitle: "Risks and review",
    detailNoRisk: "No notable risk flags.",
    detailGuardrailAllow: "Research allowed",
    currentStateEyebrow: "State",
    currentStateTitle: "Current review and effective conclusion",
    currentReview: "Current review",
    effectiveAssessment: "Effective conclusion",
    currentNoAssessment: "None",
    currentNoReason: "No deferral or rejection reason was recorded.",
    currentWorkflow: "Workflow",
    freshnessFresh: "Fresh",
    freshnessStale: "Stale",
    freshnessDeferred: "Deferred",
    freshnessUnknown: "Unknown",
  },
} as const;

export type TranslationKey = keyof typeof TEXT.zh;

export function LanguageProvider({ children }: { children: ReactNode }) {
  const language = useSyncExternalStore(
    subscribeLanguage,
    getLanguageSnapshot,
    getServerLanguageSnapshot,
  );

  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  }, [language]);

  const value = useMemo<LanguageContextValue>(
    () => ({
      language,
      setLanguage(nextLanguage) {
        window.localStorage.setItem(STORAGE_KEY, nextLanguage);
        window.dispatchEvent(new Event(LANGUAGE_CHANGE_EVENT));
        document.documentElement.lang = nextLanguage === "zh" ? "zh-CN" : "en";
      },
      t(key) {
        return TEXT[language][key];
      },
    }),
    [language],
  );

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

function subscribeLanguage(onStoreChange: () => void): () => void {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(LANGUAGE_CHANGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(LANGUAGE_CHANGE_EVENT, onStoreChange);
  };
}

function getLanguageSnapshot(): UiLanguage {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "en" || stored === "zh" ? stored : "zh";
}

function getServerLanguageSnapshot(): UiLanguage {
  return "zh";
}

export function useLanguage(): LanguageContextValue {
  const value = useContext(LanguageContext);
  if (value === null) {
    throw new Error("useLanguage must be used within LanguageProvider");
  }
  return value;
}
