"""B 部分：预算计算工具。

负责依据统一业务规则（方案文档 2.1 节）计算预算结果。

约定：
- 所有金额使用整数"分"（cents），界面层再转换为"元"。
- 缺失的关键字段必须写入 missing_fields，不能默认当作 0。
- 可自由支配预算为负时如实返回负数，不得截断为 0。

关键函数拆分：
1. validate_profile          —— 校验输入，收集缺失/非法字段。
2. calc_essential_total      —— 计算基本支出。
3. calc_discretionary        —— 计算可自由支配预算。
4. calc_remaining_cash       —— 计算购买后现金。
5. is_within_budget          —— 判断预算是否通过。
6. calculate_budget          —— 对外统一入口，组装 BudgetResult。
"""

from __future__ import annotations

from typing import List, Optional

# 与 A 协商的 schemas.py 字段名保持一致；若尚未定稿，以本模块注释为准。
# 这里刻意不依赖 Pydantic，避免 A 未交付 schemas.py 时无法独立运行；
# A 交付后可在 registry 层用 Pydantic 二次校验。


class BudgetResult:
    """预算计算结果（对应方案文档第 6 节的 BudgetResult）。"""

    def __init__(
        self,
        essential_total_cents: int,
        discretionary_cents: int,
        remaining_cash_cents: int,
        within_budget: bool,
        missing_fields: Optional[List[str]] = None,
    ) -> None:
        self.essential_total_cents = essential_total_cents
        self.discretionary_cents = discretionary_cents
        self.remaining_cash_cents = remaining_cash_cents
        self.within_budget = within_budget
        self.missing_fields = missing_fields or []

    def to_dict(self) -> dict:
        return {
            "essential_total_cents": self.essential_total_cents,
            "discretionary_cents": self.discretionary_cents,
            "remaining_cash_cents": self.remaining_cash_cents,
            "within_budget": self.within_budget,
            "missing_fields": list(self.missing_fields),
        }

    def __repr__(self) -> str:  # 便于调试
        return f"BudgetResult({self.to_dict()})"


def validate_profile(profile: dict) -> List[str]:
    """校验输入，返回缺失/非法的关键字段名列表。

    关键点：区分「字段缺失(None/未传)」与「字段显式为 0」。
    - 缺失 -> 记入 missing_fields，不得当作 0 参与计算。
    - 显式 0（如 reserve_cents=0）-> 合法，正常计算。
    """
    missing: List[str] = []

    # 必须为整数的金额/数量字段
    required_int_fields = [
        "cash_cents",
        "days_remaining",
        "daily_essential_cents",
        "fixed_expenses_cents",
        "reserve_cents",
    ]

    for field in required_int_fields:
        value = profile.get(field)
        if value is None:
            missing.append(field)
        elif not isinstance(value, int) or isinstance(value, bool):
            # bool 是 int 子类，需排除；非法类型同样视为缺失
            missing.append(field)
        elif value < 0:
            # 负数金额/天数非法，标记出来，不静默吞掉
            missing.append(field)

    return missing


def calc_essential_total(
    days_remaining: int,
    daily_essential_cents: int,
    fixed_expenses_cents: int,
) -> int:
    """计算基本支出。

    基本支出 = 剩余天数 × 每日基本开支 + 剩余固定支出
    """
    return days_remaining * daily_essential_cents + fixed_expenses_cents


def calc_discretionary(
    cash_cents: int,
    essential_total_cents: int,
    reserve_cents: int,
) -> int:
    """计算可自由支配预算。

    可自由支配预算 = 当前现金 - 基本支出 - 预留金
    注意：可能为负，如实返回，不截断为 0。
    """
    return cash_cents - essential_total_cents - reserve_cents


def calc_remaining_cash(cash_cents: int, payable_cents: int) -> int:
    """计算购买后现金。

    购买后现金 = 当前现金 - 方案实际支付金额
    """
    return cash_cents - payable_cents


def is_within_budget(
    remaining_cash_cents: int,
    essential_total_cents: int,
    reserve_cents: int,
) -> bool:
    """判断预算是否通过。

    预算通过 = 购买后现金 >= 基本支出 + 预留金
    """
    return remaining_cash_cents >= essential_total_cents + reserve_cents


def calculate_budget(
    profile: dict,
    payable_cents: Optional[int] = None,
) -> BudgetResult:
    """对外统一入口，组装 BudgetResult。

    参数：
        profile: 用户输入快照，包含 cash_cents / days_remaining /
                 daily_essential_cents / fixed_expenses_cents /
                 reserve_cents 等字段。
        payable_cents: 方案实际支付金额（分）。若为 None，说明尚未有
                       优惠方案，remaining_cash_cents 与 within_budget
                       仅按「未购买」口径计算（即 remaining = cash）。

    返回：BudgetResult
    """
    missing = validate_profile(profile)

    # 若有缺失字段，先按现有值计算能算的部分，同时把缺失字段暴露给上层，
    # 由上层决定是否补充输入（对应「未填写关键字段时询问补充」）。
    # 这里对缺失字段用 0 占位以便不抛异常，但会通过 missing_fields 明确告知。
    cash = profile.get("cash_cents", 0) or 0
    days = profile.get("days_remaining", 0) or 0
    daily = profile.get("daily_essential_cents", 0) or 0
    fixed = profile.get("fixed_expenses_cents", 0) or 0
    reserve = profile.get("reserve_cents", 0) or 0

    essential = calc_essential_total(days, daily, fixed)
    discretionary = calc_discretionary(cash, essential, reserve)

    if payable_cents is None:
        # 尚无支付方案：购买后现金暂按未支付处理
        remaining = cash
    else:
        remaining = calc_remaining_cash(cash, payable_cents)

    within = is_within_budget(remaining, essential, reserve)

    return BudgetResult(
        essential_total_cents=essential,
        discretionary_cents=discretionary,
        remaining_cash_cents=remaining,
        within_budget=within,
        missing_fields=missing,
    )
