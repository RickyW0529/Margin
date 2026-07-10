"""WebSearch Provider — configurable web search provider.

Implements specs 03 §3 interface contract and architecture §6.2.1 WebSearch Provider
with news compliance requirements.

Corresponds to plans 0302:
  0302.1 WebSearchProvider integration — user-configured API key.
  0302.2 Search result snapshot — persist query/URL/title/snippet/crawl time/
      original content snapshot hash.
  0302.3 Compliance boundary enforcement — do not bypass robots, paywalls,
      or anti-scraping; do not include copyright-restricted full text in open
      source sample data.
  0302.4 Original content verification — only enter evidence library when the
      result resolves to accessible original content or a compliant snapshot.

Compliance constraints (architecture §6.2.1):
- The user supplies their own API key.
- The system persists the search query, returned URL, title, snippet, crawl time,
  and original content snapshot hash.
- A result enters the RAG evidence library only when it resolves to accessible
  original content or a compliant snapshot.
- Do not bypass robots.txt, login walls, paywalls, or anti-scraping mechanisms.
- Do not submit copyright-restricted full text to open source sample data.
- L4/L5 sources may only trigger investigation or provide auxiliary explanation;
  they cannot alone change research or portfolio state.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from margin.core.provider import (
    BaseProvider,
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.documents.markdown import DoclingMarkdownConverter
from margin.documents.pipeline import DocumentNormalizationPipeline, DocumentPipelineRequest
from margin.news.acquirer import (
    ComplianceError,
    Downloader,
    SnapshotStore,
    SourceRegistry,
)
from margin.news.models import (
    DocumentEvent,
    RawSnapshot,
    SourceLevel,
    compute_content_hash,
    make_document_event,
    utc_now,
)

if TYPE_CHECKING:
    from margin.documents.markdown import MarkdownConversionResult
    from margin.documents.pipeline import DocumentPipelineResult
    from margin.news.repository import NewsRepository


def _domain(url: str) -> str:
    """Return the normalized host for a URL.

    Args:
        url: str: .

    Returns:
        str: .
    """
    return urlparse(url).netloc.lower()


def _matches_domain(domain: str, candidates: tuple[str, ...]) -> bool:
    """Return whether domain equals or belongs to one of the candidates.

    Args:
        domain: str: .
        candidates: tuple[str, ...]: .

    Returns:
        bool: .
    """
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def _title_from_conversion(
    conversion: MarkdownConversionResult,
    fallback: str,
) -> str:
    """Return a readable title from a Markdown conversion result.

    Args:
        conversion: MarkdownConversionResult: .
        fallback: str: .

    Returns:
        str: .
    """
    metadata = conversion.json_document or {}
    for key in ("title", "name"):
        title = _clean_title_candidate(metadata.get(key))
        if title:
            return title

    for line in conversion.markdown.splitlines():
        if line.lstrip().startswith("#"):
            title = _clean_title_candidate(line.lstrip("# ").strip())
            if title:
                return title

    for line in conversion.markdown.splitlines():
        title = _clean_title_candidate(line)
        if title:
            return title
    return fallback


def _title_from_pipeline_result(
    result: DocumentPipelineResult,
    fallback: str,
) -> str:
    """Return a readable title from final JSON, conversion metadata, or Markdown.

    Args:
        result: DocumentPipelineResult: .
        fallback: str: .

    Returns:
        str: .
    """
    title = _clean_title_candidate(result.final_json.get("title"))
    if title:
        return title
    title = _title_from_conversion(result.conversion, "")
    if title:
        return title
    for line in result.final_markdown.splitlines():
        if line.lstrip().startswith("#"):
            title = _clean_title_candidate(line.lstrip("# ").strip())
            if title:
                return title
    return fallback


def _clean_title_candidate(value: Any) -> str:
    """Normalize and reject non-business titles such as temp filenames.

    Args:
        value: Any: .

    Returns:
        str: .
    """
    if not isinstance(value, str):
        return ""
    title = value.strip()
    if not title:
        return ""
    lowered = title.lower()
    if re.fullmatch(r"tmp[_-]?[a-z0-9]+", lowered):
        return ""
    if re.fullmatch(r"\d{1,12}", title):
        return ""
    return title


# ---------------------------------------------------------------------------
# Search result models
# ---------------------------------------------------------------------------


class SearchResult(BaseModel):
    """A single web search result.."""

    url: str
    title: str
    snippet: str
    source_level: SourceLevel = SourceLevel.L4
    has_accessible_original: bool = False
    content_hash: str | None = None
    snapshot_id: str | None = None

    model_config = {"frozen": True}


class SearchQueryRecord(BaseModel):
    """Search query record (architecture §6.2.1: persist query/URL/title/snippet/."""

    query_id: str
    query: str
    results: tuple[SearchResult, ...] = Field(default_factory=tuple)
    searched_at: datetime = Field(default_factory=utc_now)
    api_provider: str
    result_count: int = 0

    model_config = {"frozen": True}


class SearchResultQualityPolicy:
    """Filter and rank WebSearch results before original-content acquisition.."""

    OFFICIAL_DOMAINS = (
        "cninfo.com.cn",
        "szse.cn",
        "sse.com.cn",
        "bse.cn",
        "csrc.gov.cn",
        "gov.cn",
    )
    TRUSTED_NEWS_DOMAINS = (
        "stcn.com",
        "cls.cn",
        "21jingji.com",
        "nbd.com.cn",
        "jiemian.com",
        "caixin.com",
        "yicai.com",
        "xinhuanet.com",
        "cnfin.com",
        "zqrb.cn",
        "cs.com.cn",
        "sfccn.com",
        "ifnews.com",
        "csteelnews.com",
        "wallstreetcn.com",
    )
    SECONDARY_DISCLOSURE_DOMAINS = (
        "data.eastmoney.com",
        "emweb.eastmoney.com",
        "gg.cfi.cn",
        "vip.stock.finance.sina.com.cn",
        "money.finance.sina.com.cn",
    )
    LOW_QUALITY_DOMAINS = (
        "xueqiu.com",
        "futunn.com",
        "moomoo.com",
        "finance.yahoo.com",
        "yahoo.com",
        "investing.com",
        "tradingview.com",
        "fupanwang.com",
        "q.stock.sohu.com",
        "stockpage.10jqka.com.cn",
        "basic.10jqka.com.cn",
        "quote.cfi.cn",
        "stock.finance.sina.com.cn",
        "stock.quote.stockstar.com",
    )
    LOW_QUALITY_TEXT_TERMS = (
        "股票股价",
        "股价",
        "走势",
        "行情",
        "行情走势",
        "实时行情",
        "走势图",
        "报价",
        "股吧",
        "讨论",
        "操盘必读",
        "F10",
        "公司资料",
        "股票最新价格",
        "历史市盈率",
        "目标价",
        "评级",
        "研究报告",
        "研报",
        "价值分析",
        "技术分析",
        "买入",
        "卖出",
        "行情首页",
    )
    EVENT_TERMS = (
        "公告",
        "业绩",
        "年报",
        "年度报告",
        "季报",
        "季度报告",
        "半年报",
        "一季报",
        "三季报",
        "预告",
        "快报",
        "监管",
        "诉讼",
        "处罚",
        "合同",
        "中标",
        "回购",
        "减持",
        "增持",
        "持股",
        "投资者关系",
        "调研",
        "权益分派",
        "分红",
        "重组",
        "停牌",
        "复牌",
        "项目",
        "收购",
        "出售",
        "质押",
        "产能",
        "进展",
        "风险",
    )
    COMMON_QUERY_TERMS = EVENT_TERMS + (
        "site",
        "最新",
        "重大事项",
        "重大",
        "新闻",
        "公司",
    )
    TICKER_RE = re.compile(r"(?<!\d)(\d{6})(?:\.(?:SZ|SH|BJ))?(?!\d)", re.I)

    def filter_and_rank(
        self,
        results: tuple[SearchResult, ...],
        *,
        query: str,
        max_results: int,
    ) -> tuple[SearchResult, ...]:
        """Return acquisition-worthy results sorted by quality.

        Args:
            results: tuple[SearchResult, ...]: .
            query: str: .
            max_results: int: .

        Returns:
            tuple[SearchResult, ...]: .
        """
        target_terms = self._target_terms(query)
        scored: list[tuple[int, int, SearchResult]] = []
        for index, result in enumerate(results):
            score = self._score(result, target_terms=target_terms)
            if score is None:
                continue
            scored.append((score, index, result))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(
            self._with_policy_source_level(result) for _, _, result in scored[:max_results]
        )

    def _with_policy_source_level(self, result: SearchResult) -> SearchResult:
        """Return a result with source level derived from its domain.

        Args:
            result: SearchResult: .

        Returns:
            SearchResult: .
        """
        domain = _domain(result.url)
        source_level = result.source_level
        if _matches_domain(domain, self.OFFICIAL_DOMAINS):
            source_level = SourceLevel.L1
        return result.model_copy(update={"source_level": source_level})

    def _score(
        self,
        result: SearchResult,
        *,
        target_terms: tuple[str, ...],
    ) -> int | None:
        """Process _score.

        Args:
            result: SearchResult: .
            target_terms: tuple[str, ...]: .

        Returns:
            int | None: .
        """
        domain = _domain(result.url)
        text = f"{result.title} {result.snippet} {result.url}"
        lowered_text = text.lower()

        if _looks_garbled(result.title) or _looks_garbled(result.snippet):
            return None
        official = _matches_domain(domain, self.OFFICIAL_DOMAINS)
        trusted = _matches_domain(domain, self.TRUSTED_NEWS_DOMAINS)
        secondary = _matches_domain(domain, self.SECONDARY_DISCLOSURE_DOMAINS)
        low_quality_domain = _matches_domain(domain, self.LOW_QUALITY_DOMAINS)
        event_like = any(term in text for term in self.EVENT_TERMS)
        has_target_context = bool(target_terms)
        target_matched = not target_terms or any(
            term and term.lower() in lowered_text for term in target_terms
        )
        low_quality_text = any(term.lower() in lowered_text for term in self.LOW_QUALITY_TEXT_TERMS)

        if not target_matched:
            return None
        if low_quality_domain:
            return None
        if low_quality_text and not (official or trusted or secondary):
            return None
        if has_target_context and not event_like and not (official or trusted):
            return None

        score = 0
        if official:
            score += 60
        elif trusted:
            score += 40
        elif secondary:
            score += 25
        if event_like:
            score += 20
        if target_matched:
            score += 10
        if result.url.lower().endswith(".pdf") and official:
            score += 10
        if low_quality_text:
            score -= 20
        return score

    def _target_terms(self, query: str) -> tuple[str, ...]:
        """Process _target_terms.

        Args:
            query: str: .

        Returns:
            tuple[str, ...]: .
        """
        ticker_match = self.TICKER_RE.search(query)
        terms: list[str] = []
        if ticker_match:
            terms.append(ticker_match.group(1))
        cleaned = re.sub(r"site:\S+", " ", query)
        cleaned = cleaned.replace("（", " ").replace("）", " ")
        cleaned = cleaned.replace("(", " ").replace(")", " ")
        for raw_token in re.split(r"\s+", cleaned):
            token = raw_token.strip("：:，,。;；")
            if not token or self.TICKER_RE.fullmatch(token):
                continue
            if not any("\u4e00" <= char <= "\u9fff" for char in token):
                continue
            if any(common in token for common in self.COMMON_QUERY_TERMS):
                continue
            terms.append(token)
            break
        return tuple(dict.fromkeys(terms))


def _looks_garbled(text: str) -> bool:
    """Return whether text looks like mojibake or private-use glyph garbage.

    Args:
        text: str: .

    Returns:
        bool: .
    """
    if not text:
        return False
    meaningful = [char for char in text if not char.isspace()]
    if not meaningful:
        return False
    if "�" in text:
        return True
    private_or_control = 0
    readable = 0
    for char in meaningful:
        category = unicodedata.category(char)
        if category == "Co" or (category.startswith("C") and char not in "\t\n\r"):
            private_or_control += 1
            continue
        if "\u4e00" <= char <= "\u9fff" or char.isascii() or category.startswith(("P", "S", "N")):
            readable += 1
    return private_or_control > 0 or readable / max(len(meaningful), 1) < 0.55


class VerifiedContent(BaseModel):
    """Accessible original content and its immutable snapshot metadata.."""

    result: SearchResult
    snapshot: RawSnapshot
    document_id: str
    title: str
    content: str

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# WebSearch Provider
# ---------------------------------------------------------------------------


class WebSearchProvider(BaseProvider):
    """WebSearch Provider — configurable web search provider.."""

    def __init__(
        self,
        name: str = "websearch",
        secret_ref: str = "websearch_api_key",
        search_func: Any = None,
    ) -> None:
        """Initialize the web search provider.

        Args:
            name: str: .
            secret_ref: str: .
            search_func: Any: .

        Returns:
            None: .
        """
        self._secret_ref = secret_ref
        self._api_key: str | None = None
        self._search_func = search_func
        self._descriptor = ProviderDescriptor(
            name=name,
            version="1.0.0",
            provider_type=ProviderType.WEB_SEARCH,
            capabilities=["search"],
            secret_refs=[secret_ref],
            config={"license": "User-configured API key"},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return the provider descriptor.

        Returns:
            ProviderDescriptor: .
        """
        return self._descriptor

    def set_api_key(self, api_key: str) -> None:
        """Set the API key (injected by Registry after ``resolve_secrets``).

        Args:
            api_key: str: .

        Returns:
            None: .
        """
        self._api_key = api_key

    def configure_secrets(self, secrets: dict[str, str]) -> None:
        """Configure the API key through the standard ProviderRegistry hook.

        Args:
            secrets: dict[str, str]: .

        Returns:
            None: .
        """
        api_key = secrets.get(self._secret_ref)
        if api_key:
            self.set_api_key(api_key)

    @property
    def api_key_configured(self) -> bool:
        """Return whether the configured secret reference has been resolved.

        Returns:
            bool: .
        """
        return bool(self._api_key)

    def set_search_func(self, search_func: Any) -> None:
        """Set the search function (enables swapping search APIs).

        Args:
            search_func: Any: .

        Returns:
            None: .
        """
        self._search_func = search_func

    def healthcheck(self) -> HealthCheckResult:
        """Check whether the provider is ready to serve search requests.

        Returns:
            HealthCheckResult: .
        """
        if self._search_func is None:
            return HealthCheckResult(
                provider_name=self._descriptor.name,
                status=ProviderStatus.DEGRADED,
                checked_at=utc_now(),
                message="No search function configured",
            )
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=utc_now(),
            message="search function configured",
        )

    def search(
        self,
        query: str,
        max_results: int = 10,
        source_level: SourceLevel = SourceLevel.L4,
    ) -> SearchQueryRecord:
        """Execute a search and return the query record.

        Args:
            query: str: .
            max_results: int: .
            source_level: SourceLevel: .

        Returns:
            SearchQueryRecord: .
        """
        import uuid

        if self._search_func is None:
            raise RuntimeError("No search function configured")

        raw_results = self._search_func(query, max_results=max_results)

        results: list[SearchResult] = []
        for raw in raw_results[:max_results]:
            results.append(
                SearchResult(
                    url=raw.get("url", ""),
                    title=raw.get("title", ""),
                    snippet=raw.get("snippet", ""),
                    source_level=source_level,
                    has_accessible_original=False,
                )
            )

        return SearchQueryRecord(
            query_id=f"sq_{uuid.uuid4().hex[:12]}",
            query=query,
            results=tuple(results),
            api_provider=self._descriptor.name,
            result_count=len(results),
        )


# ---------------------------------------------------------------------------
# 0302.3 / 0302.4 compliance boundary enforcement and original content
# verification
# ---------------------------------------------------------------------------


class ComplianceChecker:
    """Compliance boundary checker (architecture §6.2.1).."""

    BLOCKED_DOMAINS: set[str] = set()

    PAYWALL_INDICATORS = [
        "subscribe to read",
        "subscribe to continue",
        "premium content",
        "登录后查看",
        "付费阅读",
    ]

    @staticmethod
    def check_url(url: str) -> None:
        """Check whether the URL belongs to a blocked domain.

        Args:
            url: str: .

        Returns:
            None: .
        """
        from urllib.parse import urlparse

        domain = urlparse(url).netloc.lower()
        for blocked in ComplianceChecker.BLOCKED_DOMAINS:
            if blocked in domain:
                raise ComplianceError(f"URL '{url}' is in blocked domain list: {blocked}")

    @staticmethod
    def check_content_for_paywall(content: str) -> bool:
        """Check whether the content contains paywall indicators.

        Args:
            content: str: .

        Returns:
            bool: .
        """
        lower = content.lower()
        return any(indicator in lower for indicator in ComplianceChecker.PAYWALL_INDICATORS)

    @staticmethod
    def check_http_status(status: int) -> None:
        """Check the HTTP status code; 401/403 trigger compliance rejection.

        Args:
            status: int: .

        Returns:
            None: .
        """
        if status in (401, 403):
            raise ComplianceError(
                f"HTTP {status}: access denied — login wall or paywall, not bypassed"
            )


class OriginalContentVerifier:
    """Original content verifier (architecture §6.2.1: 0302.4).."""

    def __init__(
        self,
        registry: SourceRegistry,
        snapshot_store: SnapshotStore,
        markdown_converter: Any | None = None,
        normalization_pipeline: Any | None = None,
    ) -> None:
        """Initialize the verifier with a downloader backed by the registry and.

        Args:
            registry: SourceRegistry: .
            snapshot_store: SnapshotStore: .
            markdown_converter: Any | None: .
            normalization_pipeline: Any | None: .

        Returns:
            None: .
        """
        self._downloader = Downloader(registry, snapshot_store)
        self._snapshot_store = snapshot_store
        self._compliance = ComplianceChecker
        self._normalization_pipeline = normalization_pipeline or DocumentNormalizationPipeline(
            converter=markdown_converter or DoclingMarkdownConverter()
        )

    def verify_and_snapshot(
        self,
        result: SearchResult,
    ) -> VerifiedContent | None:
        """Verify that a search result resolves to accessible original content.

        Args:
            result: SearchResult: .

        Returns:
            VerifiedContent | None: .
        """
        try:
            self._compliance.check_url(result.url)
            snapshot = self._downloader.download("websearch", result.url)
            content = self._snapshot_store.read_snapshot(snapshot)
            if content is None:
                return None

            text = content.decode("utf-8", errors="replace")
            if self._compliance.check_content_for_paywall(text):
                self._snapshot_store.delete(snapshot)
                return None

            document_id = f"doc_{snapshot.snapshot_id}"
            normalized = self._normalization_pipeline.normalize(
                DocumentPipelineRequest(
                    content=content,
                    document_id=document_id,
                    source_url=result.url,
                    content_type=snapshot.content_type,
                )
            )
            original_content = str(normalized.final_markdown or "").strip()
            if not original_content:
                return None

            title = _title_from_pipeline_result(
                normalized,
                result.title,
            )
            if not title:
                title = _title_from_conversion(
                    normalized.conversion,
                    result.title,
                )

            verified_result = result.model_copy(
                update={
                    "has_accessible_original": True,
                    "content_hash": snapshot.content_hash,
                    "snapshot_id": snapshot.snapshot_id,
                }
            )
            return VerifiedContent(
                result=verified_result,
                snapshot=snapshot,
                document_id=document_id,
                title=title,
                content=original_content,
            )
        except Exception:  # noqa: BLE001 - acquisition failures must not admit partial evidence
            return None

    def verify_batch(
        self,
        results: list[SearchResult],
    ) -> list[VerifiedContent | None]:
        """Verify a batch of search results.

        Args:
            results: list[SearchResult]: .

        Returns:
            list[VerifiedContent | None]: .
        """
        verified: list[VerifiedContent | None] = []
        for result in results:
            verified.append(self.verify_and_snapshot(result))
        return verified


# ---------------------------------------------------------------------------
# 0302 integration: WebSearch service
# ---------------------------------------------------------------------------


class WebSearchService:
    """WebSearch service — integrates provider, compliance checks, and original."""

    def __init__(
        self,
        provider: WebSearchProvider,
        registry: SourceRegistry,
        snapshot_store: SnapshotStore,
        repository: NewsRepository | None = None,
        quality_policy: SearchResultQualityPolicy | None = None,
        markdown_converter: Any | None = None,
        normalization_pipeline: Any | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            provider: WebSearchProvider: .
            registry: SourceRegistry: .
            snapshot_store: SnapshotStore: .
            repository: NewsRepository | None: .
            quality_policy: SearchResultQualityPolicy | None: .
            markdown_converter: Any | None: .
            normalization_pipeline: Any | None: .

        Returns:
            None: .
        """
        self._provider = provider
        self._verifier = OriginalContentVerifier(
            registry,
            snapshot_store,
            markdown_converter=markdown_converter,
            normalization_pipeline=normalization_pipeline,
        )
        self._repository = repository
        self._quality_policy = quality_policy or SearchResultQualityPolicy()

    def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> SearchQueryRecord:
        """Execute a search and return the query record.

        Args:
            query: str: .
            max_results: int: .

        Returns:
            SearchQueryRecord: .
        """
        return self._provider.search(query, max_results=max_results)

    def search_and_acquire(
        self,
        query: str,
        max_results: int = 10,
        source_level: SourceLevel = SourceLevel.L4,
        searched_at: datetime | None = None,
    ) -> tuple[SearchQueryRecord, list[DocumentEvent]]:
        """Search and acquire original content, returning the query record and.

        Args:
            query: str: .
            max_results: int: .
            source_level: SourceLevel: .
            searched_at: datetime | None: .

        Returns:
            tuple[SearchQueryRecord, list[DocumentEvent]]: .
        """
        record = self._provider.search(query, max_results=max_results, source_level=source_level)
        filtered_results = self._quality_policy.filter_and_rank(
            record.results,
            query=query,
            max_results=max_results,
        )
        record = record.model_copy(
            update={
                "results": filtered_results,
                "result_count": len(filtered_results),
            }
        )
        if searched_at is not None:
            record = record.model_copy(update={"searched_at": searched_at})
        if self._repository is not None:
            self._repository.add_search_record(record)

        verified = self._verifier.verify_batch(record.results)

        events: list[DocumentEvent] = []
        audited_results: list[SearchResult] = []
        for result, verified_content in zip(record.results, verified, strict=True):
            if verified_content is None:
                audited_results.append(result)
                continue

            audited_result = verified_content.result
            audited_results.append(audited_result)
            event = make_document_event(
                source_url=audited_result.url,
                source_name=self._provider.descriptor.name,
                source_level=audited_result.source_level,
                title=verified_content.title or audited_result.title,
                content=verified_content.content,
                content_hash=compute_content_hash(verified_content.content),
                doc_type="news",
                published_at=verified_content.snapshot.downloaded_at,
                available_at=verified_content.snapshot.downloaded_at,
                snapshot_id=verified_content.snapshot.snapshot_id,
                snapshot_hash=verified_content.snapshot.content_hash,
                document_id=verified_content.document_id,
            )
            events.append(event)
            if self._repository is not None:
                self._repository.add_snapshot(verified_content.snapshot)
                self._repository.add_document_event(
                    event,
                    publishable=True,
                )

        audited_record = record.model_copy(update={"results": tuple(audited_results)})
        if self._repository is not None:
            self._repository.add_search_record(audited_record)
        return audited_record, events
