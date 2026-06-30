import sys
import types
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fake_streamlit = types.SimpleNamespace(
    cache_data=lambda *args, **kwargs: (lambda func: func),
    warning=lambda *args, **kwargs: None,
)
sys.modules.setdefault("streamlit", fake_streamlit)

import sea_freight as sf  # noqa: E402


class SeaFreightCoreTests(unittest.TestCase):
    def test_color_slash_codes(self):
        codes, issue = sf.parse_color_codes_from_spec("Color: 004/014")
        self.assertFalse(issue)
        self.assertEqual(codes, ["004", "014"])

    def test_color_joined_codes_with_expected_count(self):
        codes, issue = sf.parse_color_codes_from_spec("Color: 004014", expected_count=2)
        self.assertFalse(issue)
        self.assertEqual(codes, ["004", "014"])

    def test_english_color_name_needs_review(self):
        codes, issue = sf.parse_color_codes_from_spec("Color: Green-8 strands")
        self.assertTrue(issue)
        self.assertEqual(codes, [])

    def test_date_filter_includes_end_date(self):
        df = pd.DataFrame({
            "付款时间": [
                "2026-06-25 10:00:00",
                "2026-06-26 23:59:00",
                "2026-06-27 00:01:00",
            ],
            "收货人国家": ["法国", "法国", "法国"],
            "SKU": ["401001", "401002", "401003"],
            "产品规格": ["颜色:001 尺寸:100mm", "颜色:002 尺寸:100mm", "颜色:003 尺寸:100mm"],
            "单个产品数量": [1, 1, 1],
            "退款金额": [0, 0, 0],
            "订单号": ["o1", "o2", "o3"],
            "包裹号": ["p1", "p2", "p3"],
        })
        loaded = sf._load_orders_from_df(df)
        ctx = {
            "df": loaded[0],
            "sku_col": loaded[1],
            "qty_col": loaded[2],
            "refund_col": loaded[3],
            "country_col": loaded[4],
            "name_col": loaded[6],
            "store_col": loaded[7],
            "spec_col": loaded[8],
            "merch_sku_col": loaded[9],
        }
        orders = sf.prepare_orders(
            ctx["df"], ctx["sku_col"], ctx["qty_col"], ctx["refund_col"], ctx["country_col"],
            ctx["name_col"], ctx["store_col"], ctx["spec_col"], ctx["merch_sku_col"],
            True, False, pd.Timestamp("2026-06-25"), pd.Timestamp("2026-06-26")
        )
        self.assertEqual(set(orders["_order"]), {"o1", "o2"})

    def test_product_refund_rate_not_amplified_after_explode(self):
        orders = pd.DataFrame({
            "_product": ["LW401", "LW401", "LW401", "LW401"],
            "_brand": ["LW"] * 4,
            "_size": ["100mm"] * 4,
            "_color": ["001", "002", "003", "004"],
            "_qty": [1, 1, 1, 1],
            "_fr_qty": [1, 1, 1, 1],
            "_it_qty": [0, 0, 0, 0],
            "_is_fr": [True] * 4,
            "_is_it": [False] * 4,
            "_refund_flag": [1, 1, 1, 0],
            "_row_id": [10, 10, 10, 11],
            "_order": ["o1", "o1", "o1", "o2"],
            "_pkg": ["p1", "p1", "p1", "p2"],
            "_time": pd.to_datetime(["2026-06-01"] * 4),
        })
        result = sf.product_analysis(orders)
        self.assertEqual(result.loc[0, "退款风险"], "50.0%")

    def test_excluded_color_never_appears_in_combos(self):
        orders, sizes, colors = self._combo_fixture()
        _, df = sf.generate_product_combos(
            orders, sizes, colors, combo_size=4, max_combos=8,
            allow_color_repeat=True, excluded_colors=["003"], phase="成熟复购"
        )
        self.assertTrue(all("003" not in str(v).split("、") for v in df["推荐组合色号"]))

    def test_four_piece_combo_keeps_co_purchase_structures(self):
        orders, sizes, colors = self._combo_fixture()
        _, df = sf.generate_product_combos(
            orders, sizes, colors, combo_size=4, max_combos=8,
            allow_color_repeat=True, excluded_colors=[], phase="成熟复购"
        )
        combo_types = set(df["组合类型"])
        self.assertIn("2+2共购", combo_types)
        self.assertIn("3+1带货", combo_types)

    def test_first_batch_excludes_weak_colors(self):
        orders, sizes, colors = self._combo_fixture()
        weak_colors = self._weak_colors(orders, colors)
        self.assertTrue(weak_colors)
        _, df = sf.generate_product_combos(
            orders, sizes, colors, combo_size=4, max_combos=8,
            allow_color_repeat=True, excluded_colors=[], phase="首批试单"
        )
        self.assertFalse(df.empty)
        for value in df["推荐组合色号"]:
            combo_colors = set(str(value).split("、"))
            self.assertFalse(combo_colors & weak_colors)
        self.assertNotIn("铺货测试", set(df["组合类型"]))

    def test_mature_repurchase_allows_weak_colors(self):
        orders, sizes, colors = self._combo_fixture()
        weak_colors = self._weak_colors(orders, colors)
        _, df = sf.generate_product_combos(
            orders, sizes, colors, combo_size=4, max_combos=8,
            allow_color_repeat=True, excluded_colors=[], phase="成熟复购"
        )
        used_colors = set()
        for value in df["推荐组合色号"]:
            used_colors.update(str(value).split("、"))
        self.assertTrue(used_colors & weak_colors)

    def test_cache_key_changes_by_phase(self):
        first_key = sf.make_cache_key("combo", product="LW401", combo_size=4, phase="首批试单")
        mature_key = sf.make_cache_key("combo", product="LW401", combo_size=4, phase="成熟复购")
        self.assertNotEqual(first_key, mature_key)

    @staticmethod
    def _combo_fixture():
        rows = []
        groups = [
            ("o1", ["003", "007"]),
            ("o2", ["003", "007"]),
            ("o3", ["014", "019"]),
            ("o4", ["014", "019"]),
            ("o5", ["003", "007", "010"]),
            ("o6", ["003", "007", "010"]),
            ("o7", ["005", "016"]),
            ("o8", ["021", "014"]),
        ]
        for order_id, color_list in groups:
            for color in color_list:
                rows.append({
                    "_product": "LW401",
                    "_size": "100mm",
                    "_color": color,
                    "_qty": 1,
                    "_order": order_id,
                    "_pkg": "p" + order_id[1:],
                })
        orders = pd.DataFrame(rows)
        sizes = pd.DataFrame({
            "产品型号": ["LW401"],
            "尺寸": ["100mm"],
            "推荐状态": ["主推尺寸"],
        })
        colors = pd.DataFrame({
            "产品型号": ["LW401"] * 8,
            "色号": ["003", "007", "014", "019", "010", "005", "016", "021"],
            "总销量": [80, 65, 35, 25, 40, 22, 12, 8],
            "订单数": [8, 7, 5, 4, 5, 3, 2, 2],
            "颜色推荐分": [96, 88, 70, 55, 74, 48, 36, 28],
            "推荐尺寸覆盖数": [1] * 8,
        })
        return orders, sizes, colors

    @staticmethod
    def _weak_colors(orders, colors):
        co_map, _, _ = sf._build_combo_evidence(orders)
        tier_map, _, _ = sf._build_color_tiers(colors, co_map)
        return {color for color, tier in tier_map.items() if tier == "弱色"}


if __name__ == "__main__":
    unittest.main()
