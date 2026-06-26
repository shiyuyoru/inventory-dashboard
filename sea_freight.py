"""
法国/意大利海托组合分析模块
数据源：店小秘订单导出表（非库存表）
"""
import streamlit as st
import pandas as pd
import re
import io
from itertools import combinations_with_replacement, combinations

# ============================================================
# 国家识别
# ============================================================
FR_KEYS = ["法国", "france", "fr"]
IT_KEYS = ["意大利", "italy", "it"]


def is_france(val):
    v = str(val).strip().lower()
    return any(k in v for k in FR_KEYS)


def is_italy(val):
    v = str(val).strip().lower()
    return any(k in v for k in IT_KEYS)


# ============================================================
# 产品/尺寸/颜色识别
# ============================================================
def extract_product(text):
    """从任意文本中提取 LW/DT 产品型号（显式格式）"""
    if pd.isna(text):
        return None
    m = re.search(r"\b(LW\d{3,4}|DT\d{3,5})\b", str(text).strip())
    return m.group(1) if m else None


def extract_product_from_sku(sku_val, store_account=""):
    """
    从数值 SKU + 店铺账号推断产品型号。
    规则：
    - D1 店铺 → DT 产品（提取 SKU 前缀作为产品标识）
    - 其他店铺 → LW 产品（SKU 前3位数字为型号，如 216xxx → LW216）
    - 纯数字且 >15 位的 SKU → 舍弃（平台 ID）
    """
    if pd.isna(sku_val):
        return None, None
    s = str(sku_val).strip()

    # 1. 先尝试显式 LW/DT 格式
    explicit = extract_product(s)
    if explicit:
        brand = "DT" if explicit.startswith("DT") else "LW"
        return explicit, brand

    # 2. 纯数字过滤：>15 位 → 舍弃
    if s.isdigit() and len(s) > 15:
        return None, None

    # 3. 判断品牌
    store_upper = str(store_account).strip().upper()
    if store_upper.startswith("D1"):
        brand = "DT"
    else:
        brand = "LW"

    # 4. 从数值 SKU 前缀提取型号
    if s.isdigit() and 5 <= len(s) <= 15:
        if brand == "LW":
            prefix = s[:3]
            return f"LW{prefix}", brand
        else:
            # DT/D1 使用 4 位前缀
            prefix = s[:4]
            return f"DT{prefix}", brand

    # 5. 包含换行的多 SKU 情况：取第一行
    if "\n" in s:
        first = s.split("\n")[0].strip()
        if first.isdigit() and len(first) > 15:
            return None, None
        if first.isdigit() and 5 <= len(first) <= 15:
            if brand == "LW":
                return f"LW{first[:3]}", brand
            else:
                return f"DT{first[:4]}", brand

    return None, None


def extract_size(text):
    """从 SKU/产品规格/商品名称中提取尺寸 mm"""
    if pd.isna(text):
        return None
    s = str(text).strip()
    m = re.search(r"Size:\s*(\d{2,3})\s*mm", s, re.IGNORECASE)
    if m:
        return f"{m.group(1)}mm"
    m = re.search(r"(\d{2,3})\s*mm", s, re.IGNORECASE)
    if m:
        return f"{m.group(1)}mm"
    return None


def extract_color(text):
    """从产品规格中提取色号，如 Color:004 → 004"""
    if pd.isna(text):
        return None
    s = str(text).strip()
    # 匹配 Color: 后跟 2-3 位数字（排除 mm 尺寸的情况）
    for m in re.finditer(r"Color:\s*(\d{2,3})\b", s, re.IGNORECASE):
        code = m.group(1)
        # 排除看起来像尺寸的情况（前面或后面紧跟 mm）
        before = s[max(0, m.start()-5):m.start()]
        if "mm" in before.lower():
            continue
        return code
    return None


# ============================================================
# 数据加载
# ============================================================
@st.cache_data
def load_orders(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes))
    # 列名标准化
    df.columns = df.columns.astype(str).str.strip()

    # 时间列：优先付款时间，缺失时回退到下单时间
    time_col_pay = None
    time_col_order = None
    for c in df.columns:
        if "付款时间" in c:
            time_col_pay = c
        if "下单时间" in c:
            time_col_order = c
    time_col = time_col_pay or time_col_order
    if time_col_pay:
        df["_time"] = pd.to_datetime(df[time_col_pay], errors="coerce")
        if time_col_order:
            order_t = pd.to_datetime(df[time_col_order], errors="coerce")
            df["_time"] = df["_time"].fillna(order_t)
    elif time_col_order:
        df["_time"] = pd.to_datetime(df[time_col_order], errors="coerce")

    # 国家列
    country_col = None
    for c in df.columns:
        if "收货人国家" in c:
            country_col = c
            break
    if country_col:
        df["_is_fr"] = df[country_col].apply(is_france)
        df["_is_it"] = df[country_col].apply(is_italy)
    else:
        df["_is_fr"] = False
        df["_is_it"] = False

    # SKU 列
    sku_col = None
    for c in df.columns:
        if c.strip() == "SKU":
            sku_col = c
            break
    if not sku_col:
        for c in df.columns:
            if "商品SKU" in c or "商品编码" in c:
                sku_col = c
                break
    if not sku_col:
        sku_col = "SKU"
        df[sku_col] = ""

    # 数量列
    qty_col = None
    for c in df.columns:
        if "单个产品数量" in c:
            qty_col = c
            break

    # 退款列
    refund_col = None
    for c in df.columns:
        if "退款金额" in c:
            refund_col = c
            break
    if refund_col:
        df[refund_col] = pd.to_numeric(df[refund_col], errors="coerce").fillna(0)

    # 产品名称
    name_col = None
    for c in df.columns:
        if "产品名称" in c:
            name_col = c
            break

    # 店铺账号
    store_col = None
    for c in df.columns:
        if "店铺账号" in c or "店铺" in c or "账号" in c:
            store_col = c
            break

    # 产品规格（可能包含尺寸/颜色信息）
    spec_col = None
    for c in df.columns:
        if "产品规格" in c or "规格" in c:
            spec_col = c
            break

    # 商品SKU（可能包含 LW/DT 前缀）
    merch_sku_col = None
    for c in df.columns:
        if "商品SKU" in c or "商品编码" in c:
            merch_sku_col = c
            break

    return df, sku_col, qty_col, refund_col, country_col, time_col, name_col, store_col, spec_col, merch_sku_col


# ============================================================
# 筛选 + 识别
# ============================================================
def prepare_orders(df, sku_col, qty_col, refund_col, country_col, name_col,
                   store_col, spec_col, merch_sku_col,
                   fr_only, it_only, min_date, max_date):
    """筛选法意订单，识别产品、尺寸、颜色"""
    orders = df.copy()

    # 时间筛选
    if "_time" in orders.columns:
        orders = orders[(orders["_time"] >= min_date) & (orders["_time"] <= max_date)]

    # 国家筛选
    if fr_only and it_only:
        orders = orders[orders["_is_fr"] | orders["_is_it"]]
    elif fr_only:
        orders = orders[orders["_is_fr"]]
    elif it_only:
        orders = orders[orders["_is_it"]]

    if orders.empty:
        return orders

    # ---- 产品识别（两遍学习法） ----
    # 前置函数：从纯数字 SKU 提取候选产品
    def guess_from_sku(sku_str, use_4digit=False):
        """从数值SKU提取产品型号"""
        s = str(sku_str).strip()
        if not s.isdigit(): return None
        if len(s) > 15 or len(s) < 5: return None
        if use_4digit:
            return f"DT{s[:4]}"
        return f"LW{s[:3]}"

    # 第一遍：非 D1 店铺 → 统一用 LW + 3位前缀
    products = {}
    brands = {}
    for idx, row in orders.iterrows():
        sku = row[sku_col]
        store = str(row[store_col]).strip().upper() if store_col else ""

        # 1) 显式匹配 LWxxx / DTxxxx
        explicit = extract_product(sku)
        if explicit:
            products[idx] = explicit
            brands[idx] = "DT" if explicit.startswith("DT") else "LW"
            continue

        # 2) 纯数字 >15位 → 丢弃
        s = str(sku).strip()
        if s.isdigit() and len(s) > 15:
            products[idx] = None
            brands[idx] = None
            continue

        # 3) 多行 SKU 取首行
        if "\n" in s:
            s = s.split("\n")[0].strip()

        # 4) 非 D1 店铺 → LW
        if not store.startswith("D1"):
            prod = guess_from_sku(s, use_4digit=False)
            products[idx] = prod
            brands[idx] = "LW" if prod else None
        else:
            # D1 店铺暂存，第二遍处理
            products[idx] = None
            brands[idx] = None

    # 构建已知 LW 产品集合（来自非 D1 店铺 + 显式 LW）
    known_lw_prefixes = set()
    for idx, prod in products.items():
        if prod and prod.startswith("LW"):
            known_lw_prefixes.add(prod[2:])  # 存储 "216", "546" 等前缀

    # 第二遍：处理 D1 店铺 + 未识别
    for idx, row in orders.iterrows():
        if products.get(idx) is not None:
            continue  # 已识别

        sku = row[sku_col]
        store = str(row[store_col]).strip().upper() if store_col else ""
        s = str(sku).strip()
        if "\n" in s:
            s = s.split("\n")[0].strip()

        if store.startswith("D1"):
            # D1 店铺：先看是否匹配已知 LW 前缀
            lw3 = guess_from_sku(s, use_4digit=False)
            if lw3 and lw3[2:] in known_lw_prefixes:
                products[idx] = lw3
                brands[idx] = "LW"
            else:
                dt4 = guess_from_sku(s, use_4digit=True)
                products[idx] = dt4
                brands[idx] = "DT" if dt4 else None
        else:
            # 非 D1 兜底
            prod = guess_from_sku(s, use_4digit=False)
            products[idx] = prod
            brands[idx] = "LW" if prod else None

    orders["_product"] = orders.index.map(products)
    orders["_brand"] = orders.index.map(brands)

    # 回退：从 merch_sku / spec / name 列尝试显式识别
    for fallback_col in [merch_sku_col, spec_col, name_col]:
        if fallback_col:
            mask = orders["_product"].isna()
            fallback_results = orders.loc[mask, fallback_col].apply(extract_product)
            orders.loc[mask, "_product"] = orders.loc[mask, "_product"].fillna(fallback_results)
            mask2 = orders["_brand"].isna()
            orders.loc[mask2, "_brand"] = orders.loc[mask2, "_product"].apply(
                lambda x: ("DT" if str(x).startswith("DT") else "LW") if pd.notna(x) else None
            )

    # 最终兜底：仍然缺失的用 3 位前缀
    still_missing = orders["_product"].isna()
    if still_missing.any():
        for idx in orders[still_missing].index:
            s = str(orders.loc[idx, sku_col]).strip()
            if "\n" in s:
                s = s.split("\n")[0].strip()
            if s.isdigit() and 5 <= len(s) <= 15:
                orders.loc[idx, "_product"] = f"LW{s[:3]}"
                orders.loc[idx, "_brand"] = "LW"

    # 过滤无产品
    orders = orders[orders["_product"].notnull()].copy()

    # ---- 尺寸识别（优先产品规格 → SKU → name） ----
    orders["_size"] = None
    if spec_col:
        orders["_size"] = orders[spec_col].apply(extract_size)
    mask = orders["_size"].isna()
    orders.loc[mask, "_size"] = orders.loc[mask, sku_col].apply(extract_size)
    if name_col:
        mask = orders["_size"].isna()
        orders.loc[mask, "_size"] = orders.loc[mask, name_col].apply(extract_size)

    # ---- 色号识别（优先产品规格 → SKU 尾部） ----
    orders["_color"] = None
    if spec_col:
        orders["_color"] = orders[spec_col].apply(extract_color)
    mask = orders["_color"].isna()
    orders.loc[mask, "_color"] = orders.loc[mask, sku_col].apply(
        lambda x: None if pd.isna(x) else (
            re.search(r"(\d{3})$", str(x).strip()) and re.search(r"(\d{3})$", str(x).strip()).group(1)
        )
    )

    # 数量
    if qty_col:
        orders["_qty"] = pd.to_numeric(orders[qty_col], errors="coerce").fillna(1)
    else:
        orders["_qty"] = 1

    # 退款标记
    if refund_col:
        orders["_has_refund"] = orders[refund_col] > 0
    else:
        orders["_has_refund"] = False

    # 订单号
    order_col = None
    for c in df.columns:
        if "订单号" in c and "包裹号" not in c:
            order_col = c
            break
    if order_col:
        orders["_order"] = orders[order_col].astype(str)

    # 包裹号
    pkg_col = None
    for c in df.columns:
        if "包裹号" in c:
            pkg_col = c
            break
    if pkg_col:
        orders["_pkg"] = orders[pkg_col].astype(str)

    return orders


# ============================================================
# 产品级分析
# ============================================================
def product_analysis(orders, product_combos=None):
    """产品级海托适合度分析"""
    if orders.empty:
        return pd.DataFrame()
    if product_combos is None:
        product_combos = {}

    rows = []
    for prod, grp in orders.groupby("_product"):
        fr_sales = grp[grp["_is_fr"]]["_qty"].sum()
        it_sales = grp[grp["_is_it"]]["_qty"].sum()
        total_sales = fr_sales + it_sales
        fr_orders = grp[grp["_is_fr"]]["_order"].nunique() if "_order" in grp.columns else 0
        it_orders = grp[grp["_is_it"]]["_order"].nunique() if "_order" in grp.columns else 0
        total_orders = fr_orders + it_orders
        n_sizes = grp["_size"].dropna().nunique()
        n_colors = grp["_color"].dropna().nunique()
        refund_rate = grp["_has_refund"].mean() if "_has_refund" in grp.columns else 0
        n_pkgs = grp["_pkg"].nunique() if "_pkg" in grp.columns else 0

        month_cover = 0
        if "_time" in grp.columns:
            month_cover = grp["_time"].dt.to_period("M").nunique()

        if total_sales >= 100 and n_sizes >= 2 and refund_rate < 0.15:
            level = "强烈推荐"
        elif total_sales >= 50:
            level = "推荐"
        elif total_sales >= 20:
            level = "可测试"
        else:
            level = "暂不推荐"

        reason = []
        if total_sales >= 100:
            reason.append("法意销量充足")
        if n_sizes >= 2:
            reason.append("多尺寸可组合")
        if refund_rate < 0.10:
            reason.append("退款风险低")

        rows.append({
            "产品型号": prod,
            "品牌": prod[:2],
            "法国销量": int(fr_sales),
            "意大利销量": int(it_sales),
            "总销量": int(total_sales),
            "法国订单数": int(fr_orders),
            "意大利订单数": int(it_orders),
            "总订单数": int(total_orders),
            "包裹数": int(n_pkgs),
            "有销量尺寸数": n_sizes,
            "有销量色号数": n_colors,
            "月份覆盖数": month_cover,
            "退款风险": f"{refund_rate:.1%}",
            "海托推荐等级": level,
            "推荐组合": product_combos.get(prod, ""),
            "推荐理由": "、".join(reason) if reason else "需进一步评估",
        })

    df = pd.DataFrame(rows).sort_values("总销量", ascending=False)
    return df


# ============================================================
# 尺寸级分析
# ============================================================
def size_analysis(orders, min_total_sales=20):
    """按产品+尺寸聚合，计算尺寸推荐分"""
    if orders.empty:
        return pd.DataFrame()

    prod_sizes = orders.groupby(["_product", "_size"]).agg(
        FR_sales=("_is_fr", lambda x: orders.loc[x.index, "_qty"][x].sum()),
        IT_sales=("_is_it", lambda x: orders.loc[x.index, "_qty"][x].sum()),
        total_qty=("_qty", "sum"),
        n_orders=("_order", "nunique") if "_order" in orders.columns else ("_qty", "sum"),
        n_colors=("_color", lambda x: x.dropna().nunique()),
        has_fr=("_is_fr", "any"),
        has_it=("_is_it", "any"),
        refund_rate=("_has_refund", "mean") if "_has_refund" in orders.columns else ("_qty", lambda x: 0),
    ).reset_index()

    if prod_sizes.empty:
        return pd.DataFrame()

    prod_sizes.columns = ["_product", "_size", "FR_sales", "IT_sales", "total_qty",
                           "n_orders", "n_colors", "has_fr", "has_it", "refund_rate"]
    prod_sizes["FR_sales"] = prod_sizes["FR_sales"].fillna(0).astype(int)
    prod_sizes["IT_sales"] = prod_sizes["IT_sales"].fillna(0).astype(int)
    prod_sizes["has_fr"] = prod_sizes["has_fr"].fillna(False)
    prod_sizes["has_it"] = prod_sizes["has_it"].fillna(False)

    # 过滤无尺寸的
    prod_sizes = prod_sizes[prod_sizes["_size"].notna() & (prod_sizes["_size"] != "")]

    if prod_sizes.empty:
        return pd.DataFrame()

    # 月覆盖
    if "_time" in orders.columns:
        month_cover = orders.groupby(["_product", "_size"])["_time"].apply(
            lambda x: x.dt.to_period("M").nunique()
        ).reset_index()
        month_cover.columns = ["_product", "_size", "month_cover"]
        prod_sizes = prod_sizes.merge(month_cover, on=["_product", "_size"], how="left")
        prod_sizes["month_cover"] = prod_sizes["month_cover"].fillna(0).astype(int)
    else:
        prod_sizes["month_cover"] = 0

    # 为每个产品内部计算尺寸推荐分
    results = []
    for prod, grp in prod_sizes.groupby("_product"):
        if grp["total_qty"].sum() < min_total_sales:
            continue
        grp = grp.copy()
        total_prod_qty = grp["total_qty"].sum()

        # A. 尺寸销量占比 35%
        grp["size_share"] = grp["total_qty"] / max(total_prod_qty, 1)
        max_share = grp["size_share"].max()
        grp["score_share"] = (grp["size_share"] / max(max_share, 0.01)) * 35

        # B. 法意加权 25%
        grp["weighted_sales"] = grp["FR_sales"] * 1.2 + grp["IT_sales"] * 1.0
        max_w = grp["weighted_sales"].max()
        grp["score_weighted"] = (grp["weighted_sales"] / max(max_w, 1)) * 25

        # C. 订单数 15%
        max_ord = grp["n_orders"].max()
        grp["score_orders"] = (grp["n_orders"] / max(max_ord, 1)) * 15

        # D. 色号活跃度 10%
        max_col = grp["n_colors"].max()
        grp["score_color_active"] = (grp["n_colors"] / max(max_col, 1)) * 10

        # E. 国家覆盖 10%
        grp["score_country"] = grp.apply(
            lambda r: 10 if r["has_fr"] and r["has_it"] else (7 if r["has_fr"] else (5 if r["has_it"] else 2)),
            axis=1,
        )

        # F. 月份覆盖 5%
        max_mo = grp["month_cover"].max()
        grp["score_month"] = (grp["month_cover"] / max(max_mo, 1)) * 5

        # G. 退款惩罚
        grp["penalty_refund"] = grp["refund_rate"].apply(
            lambda r: 0 if r < 0.05 else (5 if r < 0.15 else (10 if r < 0.30 else 20))
        )

        grp["尺寸推荐分"] = (
            grp["score_share"] + grp["score_weighted"] + grp["score_orders"] +
            grp["score_color_active"] + grp["score_country"] + grp["score_month"] -
            grp["penalty_refund"]
        ).clip(0, 100).round(1)

        # 推荐状态
        grp = grp.sort_values("尺寸推荐分", ascending=False)
        top_scores = grp["尺寸推荐分"].values
        max_score = top_scores[0] if len(top_scores) > 0 else 0

        def status(rank, score):
            if rank == 0:
                return "主推尺寸"
            elif rank == 1 and (score >= 60 or score >= max_score * 0.5):
                return "次推尺寸"
            elif rank == 2 and (score >= 60 or score >= max_score * 0.5):
                return "第三尺寸"
            elif score >= 50:
                return "备选尺寸"
            return "不建议"

        grp["推荐状态"] = [status(i, s) for i, s in enumerate(grp["尺寸推荐分"])]
        grp["不推荐原因"] = grp["推荐状态"].apply(
            lambda x: "" if x != "不建议" else "得分不足或销量占比偏低"
        )

        # 国家覆盖描述
        grp["国家覆盖"] = grp.apply(
            lambda r: "法国+意大利" if r["has_fr"] and r["has_it"] else ("法国主导" if r["has_fr"] else "意大利"),
            axis=1,
        )

        results.append(grp)

    if not results:
        return pd.DataFrame()

    final = pd.concat(results, ignore_index=True)
    final = final.rename(columns={
        "_product": "产品型号", "_size": "尺寸",
        "FR_sales": "法国销量", "IT_sales": "意大利销量",
        "total_qty": "总销量", "n_orders": "订单数",
        "n_colors": "有销量色号数", "month_cover": "月份覆盖数",
    })
    display_cols = ["产品型号", "尺寸", "法国销量", "意大利销量", "总销量",
                    "订单数", "销量占比", "有销量色号数", "国家覆盖",
                    "月份覆盖数", "尺寸推荐分", "推荐状态", "不推荐原因"]
    final["销量占比"] = (final["总销量"] / final.groupby("产品型号")["总销量"].transform("sum") * 100).round(1).astype(str) + "%"
    return final[display_cols].sort_values(["产品型号", "尺寸推荐分"], ascending=[True, False])


# ============================================================
# 颜色级分析
# ============================================================
def color_analysis(orders, recommended_products, recommended_sizes):
    """跨推荐尺寸的颜色表现分析"""
    if orders.empty:
        return pd.DataFrame()

    orders = orders[orders["_color"].notna() & (orders["_color"] != "")]
    if orders.empty:
        return pd.DataFrame()

    key = orders[["_product", "_size", "_color", "_qty", "_is_fr", "_is_it",
                   "_has_refund", "_order", "_pkg"]].copy()

    # 只分析推荐产品+推荐尺寸
    rec_set = set()
    for _, row in recommended_sizes.iterrows():
        rec_set.add((row["产品型号"], row["尺寸"]))

    if rec_set:
        key["_rec"] = key.apply(lambda r: (r["_product"], r["_size"]) in rec_set, axis=1)
        key = key[key["_rec"]]

    # 颜色聚合
    color_agg = key.groupby(["_product", "_color"]).agg(
        FR_sales=("_qty", lambda x: key.loc[x.index][key.loc[x.index, "_is_fr"]]["_qty"].sum()),
        IT_sales=("_qty", lambda x: key.loc[x.index][key.loc[x.index, "_is_it"]]["_qty"].sum()),
        total_qty=("_qty", "sum"),
        n_orders=("_order", "nunique") if "_order" in key.columns else ("_qty", "sum"),
        n_sizes_covered=("_size", "nunique"),
        refund_rate=("_has_refund", "mean") if "_has_refund" in key.columns else ("_qty", lambda x: 0),
    ).reset_index()

    color_agg.columns = ["_product", "_color", "FR_sales", "IT_sales", "total_qty",
                          "n_orders", "n_sizes_covered", "refund_rate"]
    color_agg["FR_sales"] = color_agg["FR_sales"].fillna(0).astype(int)
    color_agg["IT_sales"] = color_agg["IT_sales"].fillna(0).astype(int)

    # 颜色推荐分计算（简化版：加权销量 45% + 尺寸覆盖 20% + 订单 15% + 退款惩罚）
    results = []
    for prod, grp in color_agg.groupby("_product"):
        grp = grp.copy()
        grp["weighted"] = grp["FR_sales"] * 1.2 + grp["IT_sales"] * 1.0
        max_w = grp["weighted"].max()
        grp["score_sales"] = (grp["weighted"] / max(max_w, 1)) * 45

        max_cov = grp["n_sizes_covered"].max()
        grp["score_cover"] = (grp["n_sizes_covered"] / max(max_cov, 1)) * 20

        max_ord = grp["n_orders"].max()
        grp["score_orders"] = (grp["n_orders"] / max(max_ord, 1)) * 15

        grp["penalty"] = grp["refund_rate"].apply(
            lambda r: 0 if r < 0.05 else (5 if r < 0.15 else (10 if r < 0.30 else 20))
        )

        grp["颜色推荐分"] = (
            grp["score_sales"] + grp["score_cover"] + grp["score_orders"] - grp["penalty"]
        ).clip(0, 100).round(1)

        grp["共用图片"] = grp["n_sizes_covered"].apply(
            lambda n: "适合" if n >= 3 else ("有限" if n >= 2 else "单尺寸特化")
        )

        results.append(grp)

    if not results:
        return pd.DataFrame()

    final = pd.concat(results, ignore_index=True)
    final = final.rename(columns={"_product": "产品型号", "_color": "色号",
                                    "FR_sales": "法国销量", "IT_sales": "意大利销量",
                                    "total_qty": "总销量", "n_orders": "订单数",
                                    "n_sizes_covered": "推荐尺寸覆盖数"})
    cols = ["产品型号", "色号", "法国销量", "意大利销量", "总销量", "订单数",
            "推荐尺寸覆盖数", "颜色推荐分", "共用图片"]
    return final[cols].sort_values(["产品型号", "颜色推荐分"], ascending=[True, False])


# ============================================================
# 组合生成
# ============================================================
def generate_product_combos(orders, recommended_sizes, color_scores, combo_size=3, max_combos=5):
    """为每个推荐产品生成组合字符串，返回 dict: 产品 → 组合字符串"""
    if orders.empty or recommended_sizes.empty or color_scores.empty:
        return {}

    product_combos = {}

    for prod in recommended_sizes["产品型号"].unique():
        prod_colors = color_scores[color_scores["产品型号"] == prod]
        top_colors = prod_colors.nlargest(6, "颜色推荐分")["色号"].tolist()

        if len(top_colors) < 2:
            continue

        # 生成有放回组合
        combos_raw = list(combinations_with_replacement(top_colors, combo_size))
        scored = []
        for combo in combos_raw:
            clist = list(combo)
            scores = []
            for c in clist:
                cr = prod_colors[prod_colors["色号"] == c]
                if not cr.empty:
                    scores.append(cr["颜色推荐分"].values[0])
            if not scores:
                continue
            avg = sum(scores) / len(scores)
            uniq = len(set(clist))
            diversity = uniq / len(clist) * 5
            combo_s = avg * 0.8 + diversity
            scored.append((combo_s, combo))

        scored.sort(key=lambda x: x[0], reverse=True)

        # 取 top combos，去重
        seen = set()
        result_combos = []
        for _, combo in scored:
            ckey = "".join(combo)
            if ckey not in seen:
                seen.add(ckey)
                result_combos.append("、".join(combo))
            if len(result_combos) >= max_combos:
                break

        if result_combos:
            product_combos[prod] = " | ".join(result_combos)

    return product_combos


# ============================================================
# 渲染函数
# ============================================================
def render_sea_freight_tab():
    st.header("法国/意大利海托组合分析")

    st.markdown("""
    **数据源：店小秘订单导出表**（非库存表）
    分析法国和意大利近一年订单，筛选适合法国仓海托的产品、尺寸和 SKU 组合。
    """)

    # 上传订单 Excel
    order_file = st.file_uploader("上传订单导出 Excel", type=["xlsx"], key="sea_freight_upload")
    if not order_file:
        st.info("请上传店小秘订单导出表开始分析。")
        return

    df, sku_col, qty_col, refund_col, country_col, time_col, name_col, store_col, spec_col, merch_sku_col = load_orders(order_file.getvalue())

    if df.empty:
        st.error("订单表为空或无法读取。")
        return

    # ---- 侧边筛选 ----
    with st.sidebar:
        st.markdown("### 海托筛选条件")
        fr_only = st.checkbox("法国", value=True)
        it_only = st.checkbox("意大利", value=True)
        brand_filter = st.multiselect("品牌", ["LW", "DT"], default=["LW", "DT"])
        min_sales = st.number_input("最低总销量阈值", 1, 1000, 20)
        combo_size = st.selectbox("组合件数", [2, 3, 4, 5], index=2)
        max_combos = st.slider("每产品最大组合数", 6, 20, 10)

        # 时间范围
        if "_time" in df.columns:
            min_d = df["_time"].min().date()
            max_d = df["_time"].max().date()
            date_range = st.date_input("时间范围", value=(min_d, max_d), min_value=min_d, max_value=max_d)
            if len(date_range) == 2:
                start_date, end_date = date_range
            else:
                start_date, end_date = min_d, max_d
        else:
            start_date = pd.Timestamp("2020-01-01")
            end_date = pd.Timestamp.now()

    # 数据处理（含诊断）
    min_dt = pd.Timestamp(start_date)
    max_dt = pd.Timestamp(end_date)

    diag = []
    diag.append(f"原始行数: {len(df):,}")
    raw = df.copy()
    if "_time" in raw.columns:
        diag.append(f"时间列有效值: {raw['_time'].notna().sum():,} / {len(raw):,}")
    if country_col:
        diag.append(f"法国: {raw['_is_fr'].sum():,}  意大利: {raw['_is_it'].sum():,}")
    if store_col:
        d1 = raw[store_col].astype(str).str.upper().str.startswith("D1").sum()
        diag.append(f"D1店铺: {d1:,}  非D1: {len(raw) - d1:,}")
    diag.append(f"时间筛选范围: {start_date} ~ {end_date}")

    orders = prepare_orders(df, sku_col, qty_col, refund_col, country_col, name_col,
                            store_col, spec_col, merch_sku_col,
                            fr_only, it_only, min_dt, max_dt)

    if orders.empty:
        st.warning("筛选后无有效订单。请检查筛选条件或数据格式。")
        return

    # 品牌过滤
    if brand_filter:
        before = len(orders)
        orders = orders[orders["_brand"].isin(brand_filter)]
        if len(orders) != before:
            diag.append(f"品牌过滤: {before:,} → {len(orders):,}")

    diag.append(f"最终有效: {len(orders):,} 行, {orders['_product'].nunique()} 个产品")
    with st.expander("诊断信息", expanded=True):
        for d in diag:
            st.caption(d)

    st.success(f"有效订单行数：{len(orders):,} | 产品数：{orders['_product'].nunique()}")

    # ---- 先做尺寸和颜色分析，再生成组合，最后输出含组合的产品排行榜 ----
    prod_df_basic = product_analysis(orders)  # 不含组合，仅用于判断非空

    recommended_sizes = pd.DataFrame()
    size_df = pd.DataFrame()
    if not prod_df_basic.empty:
        size_df = size_analysis(orders, min_sales)
        if not size_df.empty:
            recommended_sizes = size_df[size_df["推荐状态"] != "不建议"]

    # ---- 颜色级分析 ----
    color_df = pd.DataFrame()
    if not recommended_sizes.empty:
        color_df = color_analysis(orders, prod_df_basic, recommended_sizes)

    # ---- 生成组合（仅分析前50推荐产品，避免超时） ----
    product_combos = {}
    if not color_df.empty and not recommended_sizes.empty:
        top50_products = prod_df_basic.head(50)["产品型号"].tolist()
        sizes_top50 = recommended_sizes[recommended_sizes["产品型号"].isin(top50_products)]
        colors_top50 = color_df[color_df["产品型号"].isin(top50_products)]
        product_combos = generate_product_combos(orders, sizes_top50, colors_top50, combo_size, min(max_combos, 5))

    # ---- 产品级海托排行榜（含组合） ----
    prod_df = product_analysis(orders, product_combos)
    prod_df = prod_df[prod_df["总销量"] >= min_sales]

    st.markdown("---")
    st.subheader("产品级海托排行榜")
    st.caption(f"共 {len(prod_df)} 个产品达到最低销量阈值 | 组合件数：{combo_size} | 顿号分隔色号")
    if not prod_df.empty:
        st.dataframe(prod_df, use_container_width=True, hide_index=True)

    # ---- 尺寸级分析 ----
    if not size_df.empty:
        st.markdown("---")
        st.subheader("尺寸级推荐表")
        st.caption(f"共 {len(size_df)} 个产品-尺寸组合，其中推荐 {len(recommended_sizes)} 个")
        st.dataframe(size_df, use_container_width=True, hide_index=True)
    elif not prod_df.empty:
        st.markdown("---")
        st.info("未识别到有效尺寸信息。")

    # ---- 颜色级分析 ----
    if not color_df.empty:
        st.markdown("---")
        st.subheader("跨尺寸颜色表现表")
        st.caption(f"共 {len(color_df)} 个颜色")
        st.dataframe(color_df, use_container_width=True, hide_index=True)

    # ---- 下载 ----
    if not prod_df.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            prod_df.to_excel(writer, sheet_name="产品排行榜", index=False)
            if not size_df.empty:
                size_df.to_excel(writer, sheet_name="尺寸推荐", index=False)
            if not color_df.empty:
                color_df.to_excel(writer, sheet_name="颜色表现", index=False)
        st.download_button(
            label="下载海托分析 Excel",
            data=output.getvalue(),
            file_name="海托组合分析.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
