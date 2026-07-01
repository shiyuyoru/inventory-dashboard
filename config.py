"""Shared business defaults for the inventory dashboard.

Keep these values aligned with the current production logic unless the
business rules intentionally change.
"""

APP_VERSION = "v5.4.06"

PRODUCT_RECOMMEND_STRONG_SALES = 100
PRODUCT_RECOMMEND_NORMAL_SALES = 50
PRODUCT_RECOMMEND_TEST_SALES = 20

REFUND_RISK_LOW = 0.05
REFUND_RISK_MEDIUM = 0.15
REFUND_RISK_HIGH = 0.30

HOT_COLOR_RATIO = 0.20
STABLE_COLOR_RATIO = 0.60
FORCED_WEAK_COLOR_RATIO = 0.20

MAX_COLOR_POOL_BASE = 18
WEAK_COLOR_MAX_RATIO_DIVISOR = 2

ORDER_CO_PURCHASE_WEIGHT = 1.0
PACKAGE_CO_PURCHASE_WEIGHT = 1.5

COMBO_STRATEGY_WEIGHTS = {
    "均衡铺货优先": {"sales": 0.20, "balance": 0.35, "co": 0.25, "weak": 0.10, "diff": 0.10},
    "共购优先": {"sales": 0.25, "balance": 0.15, "co": 0.45, "weak": 0.05, "diff": 0.10},
    "销量转化优先": {"sales": 0.45, "balance": 0.10, "co": 0.30, "weak": 0.05, "diff": 0.10},
}

PHASE_COMBO_WEIGHTS = {
    "首批试单": {"sales": 0.55, "balance": 0.10, "co": 0.25, "weak": 0.00, "diff": 0.10},
    "成熟复购": COMBO_STRATEGY_WEIGHTS["均衡铺货优先"],
}

PHASE_ALLOW_WEAK = {
    "首批试单": False,
    "成熟复购": True,
}
