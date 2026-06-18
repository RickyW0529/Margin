"""Secret 管理器 — API Key 走本地引用，不明文存配置（架构 §22 安全设计）。

对应 spec 01 §3：Provider 必须记录 Secret 的本地引用。
对应 plan 0101.3：Secret 引用与审计日志。
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class SecretNotFoundError(KeyError):
    """Secret 引用未找到。"""


class SecretManager:
    """基于引用的 Secret 管理。

    支持两种来源（按优先级）：
    1. 环境变量（``MARGIN_SECRET_<REF>``）
    2. 本地 Secret 文件（``~/.margin/secrets/<ref>`` 或自定义目录）

    ProviderDescriptor 的 ``secret_refs`` 列表中的每个引用名，
    通过 ``resolve()`` 获取真实凭据值。配置文件中只存引用名，不存明文。
    """

    def __init__(
        self,
        secrets_dir: Path | None = None,
        env_prefix: str = "MARGIN_SECRET_",
    ) -> None:
        self._secrets_dir = secrets_dir or Path.home() / ".margin" / "secrets"
        self._env_prefix = env_prefix
        self._cache: dict[str, str] = {}

    def resolve(self, ref: str) -> str:
        """根据引用名解析 Secret 值。

        Args:
            ref: Secret 引用名（如 ``tushare_token``）。

        Returns:
            Secret 值字符串。

        Raises:
            SecretNotFoundError: 引用名在环境变量和文件中均未找到。
        """
        if ref in self._cache:
            return self._cache[ref]

        env_key = f"{self._env_prefix}{ref.upper()}"
        value = os.environ.get(env_key)
        if value is not None:
            self._cache[ref] = value
            return value

        file_path = self._secrets_dir / ref
        if file_path.is_file():
            value = file_path.read_text(encoding="utf-8").strip()
            self._cache[ref] = value
            return value

        raise SecretNotFoundError(
            f"Secret '{ref}' not found: env {env_key} unset and {file_path} missing"
        )

    def has(self, ref: str) -> bool:
        """检查 Secret 引用是否可解析。"""
        try:
            self.resolve(ref)
            return True
        except SecretNotFoundError:
            return False

    def list_refs(self) -> list[str]:
        """列出所有可解析的 Secret 引用名（不含值）。"""
        refs: set[str] = set()

        for key, value in os.environ.items():
            if key.startswith(self._env_prefix) and value:
                ref = key[len(self._env_prefix) :].lower()
                refs.add(ref)

        if self._secrets_dir.is_dir():
            for f in self._secrets_dir.iterdir():
                if f.is_file():
                    refs.add(f.name)

        return sorted(refs)


class SecretRefInfo(BaseModel):
    """Secret 引用信息（用于展示，不含值）。"""

    ref: str
    resolvable: bool
