"""B 部分：预算计算测试。

覆盖方案文档第 2.1 节与分工表中 B 的验收要求：
余额充足 / 余额不足 / 刚好够用 / 固定支出 / 预留金为 0 / 缺字段，
以及「负数不截断为 0」等关键边界。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 将 src 加入路径，便于直接运行 pytest
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from budget_agent.tools.budget import (  # noqa: E402
    BudgetResult,
    calc_discretionary,
    calc_essential_total,
    calc_remaining_cash,
    calculate_budget,
    is_within_budget,
    validate_profile,
)


def _profile(**overrides) -> dict:
    """构造一份完整合法的输入，便于用 overrides 定制单个字段。"""
    base = {
        "cash_cents": 120000,          # 1200 元
        "days_remaining": 20,
        "daily_essential_cents": 4000,  # 40 元
        "fixed_expenses_cents": 0,
        "reserve_cents": 10000,         # 100 元
        "owned_similar_items": [],
    }
    base.update(overrides)
    return base


# ---------- 贯穿示例（方案文档 2.1）自测 ----------

def test_documented_example_discretionary():
    """文档贯穿示例：余额1200、20天、每日40、无固定、预留100 -> 可自由支配300元。"""
    p = _profile()
    result = calculate_budget(p)
    assert result.essential_total_cents == 80000   # 20*4000 + 0
    assert result.discretionary_cents == 30000     # 120000-80000-10000


# ---------- 各基础公式 ----------

def test_calc_essential_total():
    assert calc_essential_total(20, 4000, 0) == 80000
    assert calc_essential_total(10, 3000, 5000) == 35000


def test_calc_discretionary_negative_not_truncated():
    """可自由支配预算为负时，如实返回负数，不截断为 0。"""
    assert calc_discretionary(10000, 80000, 10000) == -80000


def test_calc_remaining_cash():
    assert calc_remaining_cash(120000, 65000) == 55000


def test_is_within_budget():
    # 购买后现金 55000 >= 基本支出80000 + 预留10000 ? 否
    assert is_within_budget(55000, 80000, 10000) is False
    assert is_within_budget(90000, 80000, 10000) is True


# ---------- 验收边界 ----------

def test_sufficient_balance():
    p = _profile()
    result = calculate_budget(p, payable_cents=20000)  # 买 200 元
    assert result.within_budget is True


def test_insufficient_balance():
    p = _profile(cash_cents=50000)  # 只剩 500 元
    result = calculate_budget(p, payable_cents=30000)  # 买 300 元
    # 基本支出 80000 + 预留 10000 = 90000 > 购买后 20000
    assert result.within_budget is False
    assert result.discretionary_cents == 50000 - 80000 - 10000  # -40000
    assert result.discretionary_cents < 0  # 负数被保留


def test_exactly_enough_boundary():
    """刚好够用：购买后现金恰好等于 基本支出 + 预留金。"""
    # 基本支出 = 20*4000 = 80000，预留 10000，共需 90000
    # 现金 120000，买 30000 -> 剩余 90000，恰好通过
    p = _profile(cash_cents=120000)
    result = calculate_budget(p, payable_cents=30000)
    assert result.remaining_cash_cents == 90000
    assert result.within_budget is True


def test_fixed_expenses_included():
    p = _profile(fixed_expenses_cents=5000)  # 额外固定支出 50 元
    result = calculate_budget(p)
    assert result.essential_total_cents == 85000  # 80000 + 5000


def test_reserve_zero_is_legal():
    p = _profile(reserve_cents=0)  # 显式 0
    result = calculate_budget(p)
    assert "reserve_cents" not in result.missing_fields
    assert result.discretionary_cents == 120000 - 80000 - 0


def test_missing_field_reported_not_treated_as_zero():
    """缺字段：必须记入 missing_fields，且不得被当作 0 参与计算。"""
    p = _profile()
    del p["daily_essential_cents"]  # 缺失，而非显式 0
    result = calculate_budget(p)
    assert "daily_essential_cents" in result.missing_fields


def test_explicit_zero_not_missing():
    """显式传 0 与缺失要区分开。"""
    p = _profile(daily_essential_cents=0)  # 显式 0
    result = calculate_budget(p)
    assert "daily_essential_cents" not in result.missing_fields


def test_validate_profile_negative_value_reported():
    p = _profile(cash_cents=-100)
    missing = validate_profile(p)
    assert "cash_cents" in missing


def test_validate_profile_bool_rejected():
    p = _profile(days_remaining=True)  # bool 是 int 子类，需排除
    missing = validate_profile(p)
    assert "days_remaining" in missing


def test_result_to_dict():
    result = calculate_budget(_profile())
    d = result.to_dict()
    # 未给 payable：remaining = cash = 120000，>= 基本支出80000 + 预留10000，故通过
    assert d["within_budget"] is True
    assert set(d.keys()) == {
        "essential_total_cents",
        "discretionary_cents",
        "remaining_cash_cents",
        "within_budget",
        "missing_fields",
    }
