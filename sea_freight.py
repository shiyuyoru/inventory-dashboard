"""
法国/意大利海托组合分析模块 V2
数据源：店小秘订单导出表（非库存表）
"""
import streamlit as st
import pandas as pd
import re
import io
import time
from itertools import combinations_with_replacement

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
    if pd.isna(text): return None
    m = re.search(r"\b(LW\d{3,4}|DT\d{3,5})\b", str(text).strip())
    return m.group(1) if m else None


def extract_size(text):
    if pd.isna(text): return None
    s = str(text).strip()
    m = re.search(r"Size:\s*(\d{2,3})\s*mm", s, re.IGNORECASE)
    if m: return f"{m.group(1)}mm"
    m = re.search(r"(\d{2,3})\s*mm", s, re.IGNORECASE)
    return f"{m.group(1)}mm" if m else None


def extract_color(text):
    if pd.isna(text): return None
    s = str(text).strip()
    for m in re.finditer(r"Color:\s*(\d{2,3})\b", s, re.IGNORECASE):
        code = m.group(1)
        before = s[max(0, m.start()-5):m.start()]
        if "mm" in before.lower(): continue
        return code
    return None


def normalize_color(c):
    """统一色号为 3 位字符串，例如 3→003, 4.0→004"""
    if pd.isna(c): return ""
    s = str(c).strip()
    if s.endswith(".0"): s = s[:-2]
    if s.isdigit() and len(s) <= 3: return s.zfill(3)
    return s


def format_combo(combo):
    """格式化组合为 '003、004、002' 格式"""
    if isinstance(combo, str):
        s = combo.strip()
        if re.fullmatch(r"\d{6,30}", s) and len(s) % 3 == 0:
            parts = [s[i:i+3] for i in range(0, len(s), 3)]
        else:
            parts = [s]
    else:
        parts = [normalize_color(c) for c in combo]
    return "、".join(p for p in parts if p)


def extract_product_from_sku(sku_val, store_account=""):
    if pd.isna(sku_val): return None, None
    s = str(sku_val).strip()
    explicit = extract_product(s)
    if explicit:
        brand = "DT" if explicit.startswith("DT") else "LW"
        return explicit, brand
    if s.isdigit() and len(s) > 15: return None, None
    store_upper = str(store_account).strip().upper()
    brand = "DT" if store_upper.startswith("D1") else "LW"
    if s.isdigit() and 5 <= len(s) <= 15:
        return (f"LW{s[:3]}", "LW") if brand == "LW" else (f"DT{s[:4]}", brand)
    if "\n" in s:
        first = s.split("\n")[0].strip()
        if first.isdigit() and 5 <= len(first) <= 15:
            return (f"LW{first[:3]}", "LW") if brand == "LW" else (f"DT{first[:4]}", brand)
    return None, None


# ============================================================
# 数据加载 (cached)
# ============================================================
@st.cache_data(show_spinner=False)
def load_orders(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes))
    df.columns = df.columns.astype(str).str.strip()

    time_col_pay = time_col_order = None
    for c in df.columns:
        if "付款时间" in c: time_col_pay = c
        if "下单时间" in c: time_col_order = c
    time_col = time_col_pay or time_col_order
    if time_col_pay:
        df["_time"] = pd.to_datetime(df[time_col_pay], errors="coerce")
        if time_col_order:
            df["_time"] = df["_time"].fillna(pd.to_datetime(df[time_col_order], errors="coerce"))
    elif time_col_order:
        df["_time"] = pd.to_datetime(df[time_col_order], errors="coerce")

    country_col = None
    for c in df.columns:
        if "收货人国家" in c: country_col = c; break
    if country_col:
        df["_is_fr"] = df[country_col].apply(is_france)
        df["_is_it"] = df[country_col].apply(is_italy)
    else:
        df["_is_fr"] = df["_is_it"] = False

    sku_col = None
    for c in df.columns:
        if c.strip() == "SKU": sku_col = c; break
    if not sku_col:
        for c in df.columns:
            if "商品SKU" in c or "商品编码" in c: sku_col = c; break
    if not sku_col: sku_col = "SKU"; df[sku_col] = ""

    qty_col = None
    for c in df.columns:
        if "单个产品数量" in c: qty_col = c; break

    refund_col = None
    for c in df.columns:
        if "退款金额" in c: refund_col = c; break
    if refund_col:
        df[refund_col] = pd.to_numeric(df[refund_col], errors="coerce").fillna(0)

    name_col = None
    for c in df.columns:
        if "产品名称" in c: name_col = c; break

    store_col = None
    for c in df.columns:
        if "店铺账号" in c or "店铺" in c or "账号" in c: store_col = c; break

    spec_col = None
    for c in df.columns:
        if "产品规格" in c or "规格" in c: spec_col = c; break

    merch_sku_col = None
    for c in df.columns:
        if "商品SKU" in c or "商品编码" in c: merch_sku_col = c; break

    return df, sku_col, qty_col, refund_col, country_col, time_col, name_col, store_col, spec_col, merch_sku_col


# ============================================================
# 筛选 + 识别 (cached)
# ============================================================
@st.cache_data(show_spinner=False)
def prepare_orders(df, sku_col, qty_col, refund_col, country_col, name_col,
                   store_col, spec_col, merch_sku_col,
                   fr_only, it_only, min_date, max_date):
    """筛选法意订单，识别产品、尺寸、颜色。返回清洗后的 orders"""
    orders = df.copy()

    if "_time" in orders.columns:
        orders = orders[(orders["_time"] >= min_date) & (orders["_time"] <= max_date)]
    if fr_only and it_only:
        orders = orders[orders["_is_fr"] | orders["_is_it"]]
    elif fr_only:
        orders = orders[orders["_is_fr"]]
    elif it_only:
        orders = orders[orders["_is_it"]]
    if orders.empty: return orders

    # ---- 产品识别（两遍学习法） ----
    def guess_from_sku(s, use_4digit=False):
        s = str(s).strip()
        if not s.isdigit() or len(s) > 15 or len(s) < 5: return None
        return f"DT{s[:4]}" if use_4digit else f"LW{s[:3]}"

    products = {}
    brands = {}
    store_series = orders[store_col] if store_col else pd.Series([""] * len(orders), index=orders.index)

    # 第一遍：非 D1 店铺 → LW
    for idx in orders.index:
        sku = orders.at[idx, sku_col]
        store = str(store_series.at[idx]).strip().upper() if store_col else ""
        explicit = extract_product(sku)
        if explicit:
            products[idx] = explicit
            brands[idx] = "DT" if explicit.startswith("DT") else "LW"
            continue
        s = str(sku).strip()
        if s.isdigit() and len(s) > 15: products[idx] = None; continue
        if "\n" in s: s = s.split("\n")[0].strip()
        if not store.startswith("D1"):
            prod = guess_from_sku(s, False)
            products[idx] = prod
            brands[idx] = "LW" if prod else None
        else:
            products[idx] = None

    # 构建已知 LW 前缀
    known_lw = set()
    for idx, p in products.items():
        if p and p.startswith("LW"): known_lw.add(p[2:])

    # 第二遍：D1 店铺 + 未识别
    for idx in orders.index:
        if products.get(idx) is not None: continue
        sku = orders.at[idx, sku_col]
        store = str(store_series.at[idx]).strip().upper() if store_col else ""
        s = str(sku).strip()
        if "\n" in s: s = s.split("\n")[0].strip()
        if store.startswith("D1"):
            lw3 = guess_from_sku(s, False)
            if lw3 and lw3[2:] in known_lw:
                products[idx] = lw3; brands[idx] = "LW"
            else:
                dt4 = guess_from_sku(s, True)
                products[idx] = dt4; brands[idx] = "DT" if dt4 else None
        else:
            prod = guess_from_sku(s, False)
            products[idx] = prod; brands[idx] = "LW" if prod else None

    orders["_product"] = orders.index.map(products)
    orders["_brand"] = orders.index.map(brands)

    # 回退列
    for fb in [merch_sku_col, spec_col, name_col]:
        if fb:
            mask = orders["_product"].isna()
            orders.loc[mask, "_product"] = orders.loc[mask, fb].apply(extract_product)
            mask2 = orders["_brand"].isna()
            orders.loc[mask2, "_brand"] = orders.loc[mask2, "_product"].apply(
                lambda x: ("DT" if str(x).startswith("DT") else "LW") if pd.notna(x) else None
            )

    # 兜底
    still = orders["_product"].isna()
    for idx in orders[still].index:
        s = str(orders.at[idx, sku_col]).strip()
        if "\n" in s: s = s.split("\n")[0].strip()
        if s.isdigit() and 5 <= len(s) <= 15:
            orders.at[idx, "_product"] = f"LW{s[:3]}"
            orders.at[idx, "_brand"] = "LW"

    orders = orders[orders["_product"].notnull()].copy()
    if orders.empty: return orders

    # ---- 尺寸/色号 ----
    orders["_size"] = orders[spec_col].apply(extract_size) if spec_col else None
    mask = orders["_size"].isna()
    orders.loc[mask, "_size"] = orders.loc[mask, sku_col].apply(extract_size)
    if name_col:
        mask = orders["_size"].isna()
        orders.loc[mask, "_size"] = orders.loc[mask, name_col].apply(extract_size)

    orders["_color"] = orders[spec_col].apply(extract_color) if spec_col else None
    mask = orders["_color"].isna()
    orders.loc[mask, "_color"] = orders.loc[mask, sku_col].apply(
        lambda x: None if pd.isna(x) else (
            re.search(r"(\d{3})$", str(x).strip()) and re.search(r"(\d{3})$", str(x).strip()).group(1)
        )
    )
    # 统一色号为 3 位
    orders["_color"] = orders["_color"].apply(lambda c: normalize_color(c) if pd.notna(c) and c != "" else None)

    # ---- 数量与退款 ----
    orders["_qty"] = pd.to_numeric(orders[qty_col], errors="coerce").fillna(1) if qty_col else 1
    orders["_has_refund"] = orders[refund_col] > 0 if refund_col else False

    # ---- 预计算列（加速后续 groupby） ----
    orders["_fr_qty"] = orders["_qty"] * orders["_is_fr"].astype(int)
    orders["_it_qty"] = orders["_qty"] * orders["_is_it"].astype(int)
    orders["_refund_flag"] = orders["_has_refund"].astype(int)

    # ---- 订单号/包裹号 ----
    for c in df.columns:
        if "订单号" in str(c) and "包裹" not in str(c):
            orders["_order"] = orders[c].astype(str); break
    for c in df.columns:
        if "包裹号" in str(c):
            orders["_pkg"] = orders[c].astype(str); break

    return orders


# ============================================================
# 产品级分析 (cached)
# ============================================================
@st.cache_data(show_spinner=False)
def product_analysis(orders, product_combos=None):
    if orders.empty: return pd.DataFrame()
    if product_combos is None: product_combos = {}

    result = orders.groupby("_product").agg(
        FR_qty=("_fr_qty", "sum"), IT_qty=("_it_qty", "sum"),
        total_qty=("_qty", "sum"), n_orders=("_order", "nunique") if "_order" in orders else ("_qty", "sum"),
        n_sizes=("_size", lambda x: x.dropna().nunique()),
        n_colors=("_color", lambda x: x.dropna().nunique()),
        refund_rate=("_refund_flag", "mean"),
        n_pkgs=("_pkg", "nunique") if "_pkg" in orders else ("_qty", "sum"),
        month_cover=("_time", lambda x: x.dt.to_period("M").nunique()) if "_time" in orders else ("_qty", "sum"),
    ).reset_index()

    result.columns = ["_product", "法国销量", "意大利销量", "总销量", "总订单数",
                       "有销量尺寸数", "有销量色号数", "退款风险", "包裹数", "月份覆盖数"]
    for c in ["法国销量", "意大利销量", "总销量", "总订单数", "包裹数", "月份覆盖数"]:
        result[c] = result[c].fillna(0).astype(int)

    def recommend(row):
        if row["总销量"] >= 100 and row["有销量尺寸数"] >= 2 and row["退款风险"] < 0.15: return "强烈推荐"
        elif row["总销量"] >= 50: return "推荐"
        elif row["总销量"] >= 20: return "可测试"
        return "暂不推荐"

    result["品牌"] = result["_product"].apply(lambda x: x[:2])
    result["海托推荐等级"] = result.apply(recommend, axis=1)
    result["推荐组合"] = result["_product"].map(product_combos).fillna("")
    result["退款风险"] = (result["退款风险"] * 100).round(1).astype(str) + "%"
    result["推荐理由"] = result.apply(lambda r: "、".join(
        [x for x, c in [("法意销量充足", r["总销量"]>=100), ("多尺寸可组合", r["有销量尺寸数"]>=2),
                         ("退款风险低", float(r["退款风险"].rstrip("%"))<10)] if c]
    ) or "需进一步评估", axis=1)

    result = result.rename(columns={"_product": "产品型号"})
    cols = ["产品型号", "品牌", "法国销量", "意大利销量", "总销量", "总订单数", "包裹数",
            "有销量尺寸数", "有销量色号数", "月份覆盖数", "退款风险", "海托推荐等级", "推荐组合", "推荐理由"]
    return result[cols].sort_values("总销量", ascending=False)


# ============================================================
# 尺寸级分析 (cached)
# ============================================================
@st.cache_data(show_spinner=False)
def size_analysis(orders, min_total_sales=20):
    if orders.empty: return pd.DataFrame()

    agg = orders.groupby(["_product", "_size"]).agg(
        FR_sales=("_fr_qty", "sum"), IT_sales=("_it_qty", "sum"),
        total_qty=("_qty", "sum"), n_orders=("_order", "nunique") if "_order" in orders else ("_qty", "sum"),
        n_colors=("_color", lambda x: x.dropna().nunique()),
        has_fr=("_is_fr", "any"), has_it=("_is_it", "any"),
        refund_rate=("_refund_flag", "mean"),
        month_cover=("_time", lambda x: x.dt.to_period("M").nunique()) if "_time" in orders else ("_qty", "sum"),
    ).reset_index()

    agg = agg[agg["_size"].notna() & (agg["_size"] != "")]
    if agg.empty: return pd.DataFrame()

    for c in ["FR_sales", "IT_sales", "total_qty", "n_orders"]:
        agg[c] = agg[c].fillna(0).astype(int)

    results = []
    for prod, grp in agg.groupby("_product"):
        if grp["total_qty"].sum() < min_total_sales: continue
        grp = grp.copy()
        max_sale = max(grp["total_qty"].sum(), 1)
        grp["size_share"] = grp["total_qty"] / max_sale
        grp["weighted"] = grp["FR_sales"] * 1.2 + grp["IT_sales"] * 1.0

        max_share = max(grp["size_share"].max(), 0.01)
        max_w = max(grp["weighted"].max(), 1)
        max_ord = max(grp["n_orders"].max(), 1)
        max_col = max(grp["n_colors"].max(), 1)
        max_mo = max(grp["month_cover"].max(), 1)

        grp["尺寸推荐分"] = (
            (grp["size_share"] / max_share) * 35 +
            (grp["weighted"] / max_w) * 25 +
            (grp["n_orders"] / max_ord) * 15 +
            (grp["n_colors"] / max_col) * 10 +
            grp.apply(lambda r: 10 if r["has_fr"] and r["has_it"] else (7 if r["has_fr"] else 5), axis=1) +
            (grp["month_cover"] / max_mo) * 5 -
            grp["refund_rate"].apply(lambda r: 0 if r < 0.05 else (5 if r < 0.15 else (10 if r < 0.30 else 20)))
        ).clip(0, 100).round(1)

        grp = grp.sort_values("尺寸推荐分", ascending=False)
        top_scores = grp["尺寸推荐分"].values
        max_sc = top_scores[0] if len(top_scores) > 0 else 0

        def status(rank, score):
            if rank == 0: return "主推尺寸"
            if rank == 1 and (score >= 60 or score >= max_sc * 0.5): return "次推尺寸"
            if rank == 2 and (score >= 60 or score >= max_sc * 0.5): return "第三尺寸"
            if score >= 50: return "备选尺寸"
            return "不建议"

        grp["推荐状态"] = [status(i, s) for i, s in enumerate(grp["尺寸推荐分"])]
        grp["不推荐原因"] = grp["推荐状态"].apply(lambda x: "" if x != "不建议" else "得分不足")
        grp["国家覆盖"] = grp.apply(
            lambda r: "法国+意大利" if r["has_fr"] and r["has_it"] else ("法国主导" if r["has_fr"] else "意大利"), axis=1)
        results.append(grp)

    if not results: return pd.DataFrame()
    final = pd.concat(results, ignore_index=True).rename(columns={
        "_product": "产品型号", "_size": "尺寸",
        "FR_sales": "法国销量", "IT_sales": "意大利销量",
        "total_qty": "总销量", "n_orders": "订单数",
        "n_colors": "有销量色号数", "month_cover": "月份覆盖数",
    })
    final["销量占比"] = (final["总销量"] / final.groupby("产品型号")["总销量"].transform("sum") * 100).round(1).astype(str) + "%"
    cols = ["产品型号", "尺寸", "法国销量", "意大利销量", "总销量", "订单数",
            "销量占比", "有销量色号数", "国家覆盖", "月份覆盖数", "尺寸推荐分", "推荐状态", "不推荐原因"]
    return final[cols].sort_values(["产品型号", "尺寸推荐分"], ascending=[True, False])


# ============================================================
# 颜色级分析 (cached)
# ============================================================
@st.cache_data(show_spinner=False)
def color_analysis(orders, recommended_products, recommended_sizes):
    if orders.empty or recommended_sizes.empty: return pd.DataFrame()

    # 向量化筛选推荐尺寸
    rec_key = recommended_sizes[["产品型号", "尺寸"]].drop_duplicates()
    rec_key.columns = ["_product", "_size"]
    merged = orders[orders["_color"].notna() & (orders["_color"] != "")].merge(
        rec_key, on=["_product", "_size"], how="inner"
    )
    if merged.empty: return pd.DataFrame()

    agg = merged.groupby(["_product", "_color"]).agg(
        FR_sales=("_fr_qty", "sum"), IT_sales=("_it_qty", "sum"),
        total_qty=("_qty", "sum"), n_orders=("_order", "nunique") if "_order" in merged else ("_qty", "sum"),
        n_sizes_covered=("_size", "nunique"), refund_rate=("_refund_flag", "mean"),
    ).reset_index()

    agg["FR_sales"] = agg["FR_sales"].fillna(0).astype(int)
    agg["IT_sales"] = agg["IT_sales"].fillna(0).astype(int)

    results = []
    for prod, grp in agg.groupby("_product"):
        grp = grp.copy()
        grp["weighted"] = grp["FR_sales"] * 1.2 + grp["IT_sales"] * 1.0
        max_w = max(grp["weighted"].max(), 1)
        max_cov = max(grp["n_sizes_covered"].max(), 1)
        max_ord = max(grp["n_orders"].max(), 1)
        grp["颜色推荐分"] = (
            (grp["weighted"] / max_w) * 45 +
            (grp["n_sizes_covered"] / max_cov) * 20 +
            (grp["n_orders"] / max_ord) * 15 -
            grp["refund_rate"].apply(lambda r: 0 if r < 0.05 else (5 if r < 0.15 else (10 if r < 0.30 else 20)))
        ).clip(0, 100).round(1)
        grp["共用图片"] = grp["n_sizes_covered"].apply(
            lambda n: "适合" if n >= 3 else ("有限" if n >= 2 else "单尺寸特化"))
        results.append(grp)

    if not results: return pd.DataFrame()
    final = pd.concat(results, ignore_index=True).rename(columns={
        "_product": "产品型号", "_color": "色号",
        "FR_sales": "法国销量", "IT_sales": "意大利销量",
        "total_qty": "总销量", "n_orders": "订单数",
        "n_sizes_covered": "推荐尺寸覆盖数",
    })
    final["色号"] = final["色号"].apply(normalize_color)
    cols = ["产品型号", "色号", "法国销量", "意大利销量", "总销量", "订单数",
            "推荐尺寸覆盖数", "颜色推荐分", "共用图片"]
    return final[cols].sort_values(["产品型号", "颜色推荐分"], ascending=[True, False])


# ============================================================
# 共购关系表
# ============================================================
def build_co_purchase_table(orders):
    """从订单/包裹数据构建颜色 pair 共购表"""
    if "_order" not in orders.columns and "_pkg" not in orders.columns:
        return pd.DataFrame()

    orders = orders[orders["_color"].notna() & (orders["_color"] != "")].copy()
    if orders.empty: return pd.DataFrame()

    pairs = []
    group_cols = []
    if "_order" in orders.columns: group_cols.append("_order")
    if "_pkg" in orders.columns: group_cols.append("_pkg")

    for gcols in [["_order", "_product", "_size"], ["_pkg", "_product", "_size"]]:
        g = [c for c in gcols if c in orders.columns]
        if len(g) < 2: continue
        is_pkg = "_pkg" in g
        for _, grp in orders.groupby(g[:2] if len(g) >= 2 else g):
            if len(grp) < 2: continue
            colors = grp["_color"].unique()
            prod = grp["_product"].iloc[0]
            sz = grp["_size"].iloc[0] if "_size" in grp.columns else ""
            for i in range(len(colors)):
                for j in range(i+1, len(colors)):
                    weight = 1.5 if is_pkg else 1.0
                    pairs.append((prod, sz, min(colors[i], colors[j]),
                                  max(colors[i], colors[j]), weight))

    if not pairs: return pd.DataFrame()
    pair_df = pd.DataFrame(pairs, columns=["产品型号", "尺寸", "色号A", "色号B", "weight"])
    pair_df = pair_df.groupby(["产品型号", "尺寸", "色号A", "色号B"])["weight"].sum().reset_index()
    pair_df["共购分"] = pair_df["weight"].round(1)
    return pair_df.drop(columns=["weight"])


# ============================================================
# 组合生成
# ============================================================
def _score_combo(combo, color_score_map, color_cover_map, co_purchase_map, n_rec_sizes):
    """评分单个组合，返回 (total, co_score, img_score, min_cov, unique_n)"""
    clist = list(combo)
    color_counts = {}
    for c in clist:
        color_counts[c] = color_counts.get(c, 0) + 1
    decay = {1: 1.0, 2: 0.85, 3: 0.70, 4: 0.55, 5: 0.45}
    demand_scores = [color_score_map.get(c, 0) * decay.get(color_counts.get(c, 0), 0.5) for c in clist]
    demand_score = sum(demand_scores) / len(demand_scores)

    co_score = 0; pair_count = 0
    for i in range(len(clist)):
        for j in range(i+1, len(clist)):
            co_score += co_purchase_map.get((min(clist[i], clist[j]), max(clist[i], clist[j])), 0)
            pair_count += 1
    co_score = min(100, (co_score / max(pair_count, 1)) * 5)

    min_cov = min(color_cover_map.get(c, 0) for c in clist)
    img_score = min(100, (min_cov / max(n_rec_sizes, 1)) * 100)

    unique_n = len(set(clist))
    struct = {1: 10, 2: 30, 3: 50}.get(unique_n, 50)
    struct = min(100, struct + unique_n * 5)
    size_rep = min(100, (min_cov / max(n_rec_sizes, 1)) * 100)
    dup_penalty = max(0, (max(color_counts.values()) / len(clist) - 0.5) * 30)

    total = max(0, min(100, demand_score * 0.40 + co_score * 0.25 + img_score * 0.15 + struct * 0.10 + size_rep * 0.10 - dup_penalty))
    ctype = "爆款重复" if unique_n == 1 else ("爆款核心" if unique_n == 2 else "畅销多色")
    return total, ctype, co_score, img_score, min_cov


def generate_product_combos(orders, recommended_sizes, color_scores,
                            combo_size=3, max_combos=6, co_purchase_df=None):
    """为每个产品生成多样化组合，按类型配额分配"""
    if orders.empty or recommended_sizes.empty or color_scores.empty:
        return {}, pd.DataFrame()
    if co_purchase_df is None:
        co_purchase_df = pd.DataFrame()

    product_combos_preview = {}
    all_combo_rows = []

    for prod in recommended_sizes["产品型号"].unique():
        prod_colors = color_scores[color_scores["产品型号"] == prod]
        if len(prod_colors) < 2: continue

        prod_sizes = recommended_sizes[
            (recommended_sizes["产品型号"] == prod) &
            (recommended_sizes["推荐状态"].isin(["主推尺寸", "次推尺寸", "第三尺寸"]))
        ]
        rec_sizes = prod_sizes["尺寸"].tolist()
        if not rec_sizes: continue

        # 颜色池：Top 10
        pool = prod_colors.nlargest(10, "颜色推荐分")
        pool_colors = pool["色号"].tolist()
        color_score_map = dict(zip(pool["色号"], pool["颜色推荐分"]))
        color_cover_map = dict(zip(pool["色号"], pool["推荐尺寸覆盖数"]))
        top1 = pool_colors[0]

        co_purchase_map = {}
        if not co_purchase_df.empty:
            cp = co_purchase_df[co_purchase_df["产品型号"] == prod]
            for _, r in cp.iterrows():
                co_purchase_map[(r["色号A"], r["色号B"])] = r["共购分"]
                co_purchase_map[(r["色号B"], r["色号A"])] = r["共购分"]

        # ---- 分类型生成候选组合 ----
        repeat_candidates = []
        core_candidates = []
        multi_candidates = []
        co_candidates = []

        # 1) 纯重复组合
        repeat_candidates.append((top1,) * combo_size)

        # 2) 爆款核心：top1 + top1 + 其他，top1 + 其他1 + 其他2
        other_colors = [c for c in pool_colors if c != top1]
        for oc in other_colors[:5]:
            combo = tuple(sorted([top1, top1, oc]) if combo_size == 3 else ([top1] * (combo_size - 1) + [oc]))
            core_candidates.append(tuple(combo))
        # top1 + 2 other different colors
        if len(other_colors) >= 2:
            for i in range(min(4, len(other_colors))):
                for j in range(i+1, min(5, len(other_colors))):
                    core_candidates.append(tuple(sorted([top1, other_colors[i], other_colors[j]])))

        # 3) 畅销多色：不含 top1 的 Top 色组合
        for i in range(min(5, len(other_colors))):
            for j in range(i+1, min(6, len(other_colors))):
                if combo_size == 3:
                    multi_candidates.append(tuple(sorted([other_colors[i], other_colors[j], other_colors[min(j+1, len(other_colors)-1)]])))
                else:
                    combo = tuple(sorted(other_colors[i:i+combo_size]))
                    if len(set(combo)) >= 2:
                        multi_candidates.append(combo)
        # 也加入一些含 top1 但颜色更丰富的
        if len(other_colors) >= 3:
            for i in range(min(4, len(other_colors))):
                for j in range(i+1, min(5, len(other_colors))):
                    multi_candidates.append(tuple(sorted([top1, other_colors[i], other_colors[j]])))

        # 4) 共购组合：从共购对构建
        if co_purchase_map:
            co_pairs = sorted(co_purchase_map.items(), key=lambda x: x[1], reverse=True)
            seen_co_combos = set()
            for (a, b), score in co_pairs[:20]:
                if a in pool_colors and b in pool_colors and a != b:
                    others = [c for c in pool_colors if c not in (a, b)]
                    if others:
                        combo = tuple(sorted([a, b, others[0]]))
                        if combo not in seen_co_combos:
                            co_candidates.append(combo)
                            seen_co_combos.add(combo)

        # ---- 评分 ----
        def score_list(candidates, seen):
            result = []
            for combo in candidates:
                ckey = tuple(sorted(normalize_color(c) for c in combo))
                if ckey in seen: continue
                seen.add(ckey)
                total, ctype, co, img, min_c = _score_combo(combo, color_score_map, color_cover_map, co_purchase_map, len(rec_sizes))
                result.append((total, combo, ctype, co, img, min_c, ckey))
            result.sort(key=lambda x: x[0], reverse=True)
            return result

        seen_keys = set()
        repeat_scored = score_list(repeat_candidates, seen_keys)
        core_scored = score_list(core_candidates, seen_keys)
        multi_scored = score_list(multi_candidates, seen_keys)
        co_scored = score_list(co_candidates, seen_keys)

        # ---- 配额分配 & 填充 ----
        n = max_combos
        quota_repeat = min(2, max(1, n // 6))
        remaining = n - quota_repeat
        quota_core = max(2, remaining * 2 // 5)
        quota_multi = max(2, remaining * 2 // 5)
        quota_co = max(0, remaining - quota_core - quota_multi)

        selected = []

        def pick(from_list, limit):
            for item in from_list:
                if len([s for s in selected if s["_key"] == item[6]]) > 0: continue
                if len([s for s in selected if s["type"] == item[2]]) >= limit and item[2] != "畅销多色":
                    continue
                selected.append({
                    "_key": item[6], "combo_tuple": item[1], "score": item[0],
                    "type": item[2], "co_score": item[3], "img_score": item[4], "min_cov": item[5],
                })

        pick(repeat_scored, quota_repeat)
        pick(co_scored, quota_co)
        pick(core_scored, quota_core)
        pick(multi_scored, quota_multi)

        # 如果还不够，用 multi 填充
        if len(selected) < n:
            for item in multi_scored + core_scored:
                if len(selected) >= n: break
                if any(c["_key"] == item[6] for c in selected): continue
                selected.append({
                    "_key": item[6], "combo_tuple": item[1], "score": item[0],
                    "type": item[2], "co_score": item[3], "img_score": item[4], "min_cov": item[5],
                })

        selected = selected[:n]

        # ---- 输出 ----
        previews = []
        for s in selected:
            formatted = format_combo(s["combo_tuple"])
            previews.append(formatted)
            all_combo_rows.append({
                "产品型号": prod,
                "推荐尺寸": " / ".join(rec_sizes),
                "组合类型": s["type"],
                "推荐组合色号": formatted,
                "组合件数": combo_size,
                "是否共用图片": "是" if s["min_cov"] >= len(rec_sizes) else ("有限" if s["min_cov"] >= 2 else "否"),
                "适用尺寸": " / ".join(rec_sizes) if s["min_cov"] >= len(rec_sizes) else rec_sizes[0],
                "组合推荐分": round(s["score"], 1),
                "推荐理由": f"{s['type']}组合，均分{s['score']:.0f}" if s["score"] >= 50 else "可参考",
                "注意事项": "" if s["min_cov"] >= 2 else "单尺寸特化，不建议做共用图片",
            })

        product_combos_preview[prod] = " | ".join(previews[:5])

    combo_df = pd.DataFrame(all_combo_rows).sort_values(["产品型号", "组合推荐分"], ascending=[True, False]) if all_combo_rows else pd.DataFrame()
    return product_combos_preview, combo_df


# ============================================================
# 渲染
# ============================================================
def render_sea_freight_tab():
    st.header("法国/意大利海托组合分析")

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
        max_combos = st.slider("每产品最大组合数", 6, 10, 6)

        if "_time" in df.columns:
            min_d = df["_time"].min().date()
            max_d = df["_time"].max().date()
            date_range = st.date_input("时间范围", value=(min_d, max_d), min_value=min_d, max_value=max_d)
            start_date, end_date = (date_range[0], date_range[1]) if len(date_range) == 2 else (min_d, max_d)
        else:
            start_date, end_date = pd.Timestamp("2020-01-01"), pd.Timestamp.now()

    # ---- 预处理 ----
    min_dt, max_dt = pd.Timestamp(start_date), pd.Timestamp(end_date)
    orders = prepare_orders(df, sku_col, qty_col, refund_col, country_col, name_col,
                            store_col, spec_col, merch_sku_col,
                            fr_only, it_only, min_dt, max_dt)
    if orders.empty:
        st.warning("筛选后无有效订单。")
        return
    if brand_filter:
        orders = orders[orders["_brand"].isin(brand_filter)]

    st.success(f"数据就绪：{len(orders):,} 行 | {orders['_product'].nunique()} 个产品 | {orders['_color'].dropna().nunique()} 个色号 | {orders['_size'].dropna().nunique()} 个尺寸")

    # ---- 分析按钮 ----
    if not st.button("开始分析", type="primary", use_container_width=True):
        st.info("点击上方按钮开始分析订单数据。")
        return

    t0 = time.time()

    with st.spinner("正在分析订单数据..."):
        # 产品排行榜（不含组合）
        prod_df_basic = product_analysis(orders)

        # 尺寸
        size_df = size_analysis(orders, min_sales)
        recommended_sizes = size_df[size_df["推荐状态"].isin(["主推尺寸", "次推尺寸", "第三尺寸"])] if not size_df.empty else pd.DataFrame()

        # 颜色
        color_df = pd.DataFrame()
        if not recommended_sizes.empty:
            color_df = color_analysis(orders, prod_df_basic, recommended_sizes)

        # 共购表
        co_purchase_df = build_co_purchase_table(orders) if not orders.empty else pd.DataFrame()

        # 组合（仅前50产品）
        product_combos = {}
        combo_df = pd.DataFrame()
        if not color_df.empty and not recommended_sizes.empty:
            top50 = prod_df_basic.head(50)["产品型号"].tolist()
            sizes_50 = recommended_sizes[recommended_sizes["产品型号"].isin(top50)]
            colors_50 = color_df[color_df["产品型号"].isin(top50)]
            product_combos, combo_df = generate_product_combos(
                orders, sizes_50, colors_50, combo_size, max_combos, co_purchase_df
            )

        # 产品排行榜（含组合预览）
        prod_df = product_analysis(orders, product_combos)
        prod_df = prod_df[prod_df["总销量"] >= min_sales]

    elapsed = time.time() - t0
    st.success(f"分析完成，耗时 {elapsed:.1f} 秒")

    # ---- 产品级海托排行榜 ----
    st.markdown("---")
    st.subheader("产品级海托排行榜")
    st.caption(f"共 {len(prod_df)} 个产品 | 组合件数：{combo_size} | 点击查看推荐组合详情")
    if not prod_df.empty:
        st.dataframe(prod_df, use_container_width=True, hide_index=True)

    # ---- 尺寸级推荐表 ----
    if not size_df.empty:
        st.markdown("---")
        st.subheader("尺寸级推荐表")
        st.caption(f"共 {len(size_df)} 个产品-尺寸组合 | 推荐 {len(recommended_sizes)} 个（仅主推/次推/第三尺寸参与组合分析）")
        st.dataframe(size_df, use_container_width=True, hide_index=True)

    # ---- 颜色表现表 ----
    if not color_df.empty:
        st.markdown("---")
        st.subheader("跨尺寸颜色表现表")
        st.caption(f"共 {len(color_df)} 个颜色（仅推荐尺寸范围内）")
        st.dataframe(color_df, use_container_width=True, hide_index=True)

    # ---- 共购关系表 ----
    if not co_purchase_df.empty:
        st.markdown("---")
        st.subheader("颜色共购关系表")
        st.caption(f"共 {len(co_purchase_df)} 对共购关系")
        st.dataframe(co_purchase_df, use_container_width=True, hide_index=True)

    # ---- 最终组合建议表 ----
    if not combo_df.empty:
        st.markdown("---")
        st.subheader("最终组合建议表")
        st.caption(f"共 {len(combo_df)} 个推荐组合（件数：{combo_size}）")
        st.dataframe(combo_df, use_container_width=True, hide_index=True)

    # ---- 下载 ----
    if not prod_df.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            prod_df.to_excel(writer, sheet_name="产品排行榜", index=False)
            if not size_df.empty:
                size_df.to_excel(writer, sheet_name="尺寸推荐", index=False)
            if not color_df.empty:
                color_df.to_excel(writer, sheet_name="颜色表现", index=False)
            if not combo_df.empty:
                combo_df.to_excel(writer, sheet_name="组合建议", index=False)
            if not co_purchase_df.empty:
                co_purchase_df.to_excel(writer, sheet_name="共购关系", index=False)
        st.download_button(
            label="下载海托分析 Excel",
            data=output.getvalue(),
            file_name="海托组合分析.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
