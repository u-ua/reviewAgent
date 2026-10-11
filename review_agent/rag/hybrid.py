"""轻量 BM25 与 Reciprocal Rank Fusion，用于规则库的混合检索。"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import replace
from typing import Sequence

from .models import RetrievedRule


TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]*|[\u4e00-\u9fff]+")

# 跨语言词法归一化不是按评测样本绑定 rule_id，而是将常见安全概念补成英文检索词。
SECURITY_TERMS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("授权", "越权", "权限", "归属", "属于当前用户", "所有权"), "authorization access control ownership object level IDOR"),
    (("认证", "登录", "身份凭证"), "authentication identity credential login"),
    (("注入", "拼接", "SQL"), "injection SQL query concatenation parameterized"),
    (("跨站", "XSS", "innerHTML", "转义"), "cross site scripting XSS output encoding HTML"),
    (("命令", "shell", "os.system"), "OS command shell injection execution"),
    (("上传", "文件类型", "扩展名"), "file upload extension content type signature"),
    (("内网", "元数据", "SSRF"), "server side request forgery SSRF internal metadata URL"),
    (("外部实体", "XXE"), "XML external entity XXE"),
    (("反序列化", "pickle"), "unsafe deserialization pickle"),
    (("证书", "TLS", "主机名验证"), "TLS certificate hostname verification"),
    (("密钥", "密码", "凭据", "令牌"), "secret password credential token key"),
    (("日志", "换行符"), "logging log injection newline sensitive data"),
    (("重定向",), "open redirect URL allowlist"),
    (("CSRF", "跨站请求伪造"), "cross site request forgery CSRF token SameSite"),
)


def expand_security_query(query: str) -> str:
    lower = query.lower()
    additions = [terms for triggers, terms in SECURITY_TERMS if any(trigger.lower() in lower for trigger in triggers)]
    return " ".join([query, *additions])


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN.finditer(text.lower()):
        value = match.group(0)
        if re.fullmatch(r"[\u4e00-\u9fff]+", value):
            # 中文同时保留连续片段和二元字，英文官方文档主要依赖上面的概念扩展。
            tokens.append(value)
            tokens.extend(value[index:index + 2] for index in range(max(0, len(value) - 1)))
        else:
            tokens.append(value)
    return tokens


class BM25RuleIndex:
    def __init__(self, documents: Sequence[RetrievedRule], *, k1: float = 1.5, b: float = 0.75):
        self.documents = list(documents)
        self.k1 = k1
        self.b = b
        self.tokens = [tokenize(f"{item.rule_id} {item.title} {item.text}") for item in self.documents]
        self.lengths = [len(values) for values in self.tokens]
        self.average_length = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        self.term_frequencies = [Counter(values) for values in self.tokens]
        document_frequency: Counter[str] = Counter()
        for values in self.tokens:
            document_frequency.update(set(values))
        count = len(self.documents)
        self.idf = {
            term: math.log(1.0 + (count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def search(self, query: str, *, limit: int = 50) -> list[RetrievedRule]:
        if limit < 1:
            return []
        query_terms = tokenize(expand_security_query(query))
        scored: list[RetrievedRule] = []
        for index, item in enumerate(self.documents):
            score = 0.0
            length = self.lengths[index]
            frequencies = self.term_frequencies[index]
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                norm = frequency + self.k1 * (
                    1.0 - self.b + self.b * length / (self.average_length or 1.0)
                )
                score += self.idf.get(term, 0.0) * frequency * (self.k1 + 1.0) / norm
            if score > 0:
                scored.append(replace(item, score=score))
        # 先按规则去重再截断，否则一个长 Cheat Sheet 的多个高分分块会挤掉其他规则。
        return unique_rule_results(scored)[:limit]


def unique_rule_results(results: Sequence[RetrievedRule]) -> list[RetrievedRule]:
    unique: list[RetrievedRule] = []
    seen: set[str] = set()
    for item in sorted(results, key=lambda value: value.score, reverse=True):
        if item.rule_id not in seen:
            seen.add(item.rule_id)
            unique.append(item)
    return unique


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[RetrievedRule]],
    *,
    limit: int = 5,
    rank_constant: int = 60,
    weights: Sequence[float] | None = None,
) -> list[RetrievedRule]:
    active_weights = list(weights) if weights is not None else [1.0] * len(rankings)
    if len(active_weights) != len(rankings) or any(weight <= 0 for weight in active_weights):
        raise ValueError("RRF weights 必须与 rankings 等长且均为正数")
    scores: dict[str, float] = {}
    representatives: dict[str, RetrievedRule] = {}
    for ranking, weight in zip(rankings, active_weights, strict=True):
        for rank, item in enumerate(unique_rule_results(ranking), start=1):
            scores[item.rule_id] = scores.get(item.rule_id, 0.0) + weight / (rank_constant + rank)
            representatives.setdefault(item.rule_id, item)
    ordered = sorted(scores, key=lambda rule_id: (-scores[rule_id], rule_id))
    return [replace(representatives[rule_id], score=scores[rule_id]) for rule_id in ordered[:limit]]
