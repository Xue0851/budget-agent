"""B 部分：理性角色。

理性角色负责读取预算结果与既有事实，输出机会成本、重复需求、
可替代性与反对理由。核心原则：只引用传入的预算数字，绝不自己算数。

关键函数拆分：
1. _load_prompt          —— 加载提示词模板。
2. _build_context        —— 组装角色输入上下文（预算结果 + 已有物品 + 需求）。
3. _validate_no_fabricated_numbers —— 校验模型输出未凭空产生新数字。
4. run                   —— 对外入口，调用模型并返回 Argument。

模型调用通过 model_client 抽象层完成；本模块不直接依赖具体模型实现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "rational.md"


class Argument:
    """理性角色输出的结构化论点（对应方案文档第 6 节 Argument）。"""

    def __init__(
        self,
        role: str,
        stance: str,
        claims: List[str],
        evidence_ids: Optional[List[str]] = None,
        unknowns: Optional[List[str]] = None,
    ) -> None:
        self.role = role
        self.stance = stance
        self.claims = claims
        self.evidence_ids = evidence_ids or []
        self.unknowns = unknowns or []

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "stance": self.stance,
            "claims": list(self.claims),
            "evidence_ids": list(self.evidence_ids),
            "unknowns": list(self.unknowns),
        }


def _load_prompt() -> str:
    """加载 rational.md 提示词模板。"""
    return PROMPT_PATH.read_text(encoding="utf-8")


def _build_context(
    budget_result: Dict[str, Any],
    need_reason: str,
    owned_similar_items: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """组装理性角色的输入上下文。

    只传入已计算好的预算数字，不在此处做任何计算。
    """
    return {
        "budget_result": budget_result,
        "need_reason": need_reason,
        "owned_similar_items": owned_similar_items or [],
    }


def _validate_no_fabricated_numbers(
    raw_output: str,
    allowed_numbers: List[int],
) -> List[str]:
    """校验模型输出，标记疑似凭空产生的数字。

    思路：提取输出中的整数，若出现不在 allowed_numbers 且
    绝对值较大的金额类数字，则标记为 unknown，供上层复核。

    说明：这里是保守的启发式校验；真实金额判定可结合证据 ID 进一步收紧。
    第一版以「不阻断、只标记」为主，避免误伤正常文本。
    """
    import re

    unknowns: List[str] = []
    # 匹配 100 及以上的整数（避免把「第一」「第二」等序数误判为金额）
    found = [int(m) for m in re.findall(r"\b\d{3,}\b", raw_output)]
    allowed_set = set(allowed_numbers)
    for num in found:
        if num not in allowed_set and num % 10 == 0 and num >= 100:
            # 疑似金额：能被 10 整除且不小于 100，且不在传入数字中
            unknowns.append(f"疑似凭空数字: {num}")
    return unknowns


class RationalAgent:
    """理性角色 agent。

    model_client: 一个带 generate(prompt) -> str 的可调用对象，
                  由 A 提供（真实模型或 FakeModel）。
    """

    def __init__(self, model_client: Any) -> None:
        self.model_client = model_client
        self.prompt_template = _load_prompt()

    def run(self, context: Dict[str, Any]) -> Argument:
        """执行理性角色分析，返回结构化 Argument。"""
        budget = context["budget_result"]
        need_reason = context.get("need_reason", "")
        owned = context.get("owned_similar_items", [])

        # 1. 组装允许出现的预算数字，供事后校验
        allowed_numbers = [
            budget.get("essential_total_cents", 0),
            budget.get("discretionary_cents", 0),
            budget.get("remaining_cash_cents", 0),
        ]

        # 2. 拼装完整 prompt
        prompt = (
            f"{self.prompt_template}\n\n"
            f"## 本次输入\n"
            f"需求理由：{need_reason}\n"
            f"已有同类商品：{owned or '无'}\n"
            f"预算结果：{budget}\n"
        )

        # 3. 调用模型
        raw_output = self.model_client.generate(prompt)

        # 4. 校验是否凭空产生数字
        unknowns = _validate_no_fabricated_numbers(
            raw_output, [n for n in allowed_numbers if n is not None]
        )

        # 5. 第一版：claims 暂以模型原始输出分段，待 D 的统一解析接入
        claims = [line.strip() for line in raw_output.splitlines() if line.strip()]

        return Argument(
            role="rational",
            stance="against",
            claims=claims,
            evidence_ids=[],  # 由上层依据证据 ID 关联后填充
            unknowns=unknowns,
        )
