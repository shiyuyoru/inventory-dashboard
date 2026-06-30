"""
法国/意大利海托组合分析模块 V2
数据源：店小秘订单导出表（非库存表）
"""
import streamlit as st
import pandas as pd
import re
import io
import time
from itertools import combinations, combinations_with_replacement, product

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


VALID_COLOR_MIN = 1
VALID_COLOR_MAX = 30


def is_valid_color_code(value):
    if value is None or pd.isna(value):
        return False
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.isdigit() and VALID_COLOR_MIN <= int(text) <= VALID_COLOR_MAX


def normalize_valid_color(value):
    return str(int(str(value).strip().replace(".0", ""))).zfill(3) if is_valid_color_code(value) else ""


def extract_expected_combo_count(*texts):
    joined = " ".join("" if pd.isna(t) else str(t) for t in texts)
    m = re.search(r"\b([2-9]|1[0-2])\s*(?:PCS|Pcs|pcs|件|只|支)\b", joined, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_color_field(text):
    if pd.isna(text):
        return None, False
    s = str(text)
    m = re.search(r"(?:颜色|Color|Colour)\s*[:：]\s*([^\n\r;；|]+)", s, re.IGNORECASE)
    if not m:
        return None, False
    value = m.group(1)
    value = re.split(r"\b(?:Size|尺寸|Line\s*Number|Line|型号|规格)\s*[:：]", value, maxsplit=1, flags=re.IGNORECASE)[0]
    return value.strip(), True


def _split_digits_to_valid_colors(digits, expected_count=None):
    digits = re.sub(r"\D", "", str(digits))
    if not digits:
        return [], False
    if is_valid_color_code(digits):
        return [normalize_valid_color(digits)], False
    if len(digits) % 3 == 0:
        chunks = [digits[i:i + 3] for i in range(0, len(digits), 3)]
        if all(is_valid_color_code(chunk) for chunk in chunks):
            if expected_count is None or len(chunks) == expected_count:
                return [normalize_valid_color(chunk) for chunk in chunks], False

    solutions = []

    def walk(pos, parts):
        if pos == len(digits):
            solutions.append(parts[:])
            return
        if expected_count and len(parts) >= expected_count:
            return
        for width in (1, 2, 3):
            token = digits[pos:pos + width]
            if not token:
                continue
            if is_valid_color_code(token):
                parts.append(normalize_valid_color(token))
                walk(pos + width, parts)
                parts.pop()

    walk(0, [])
    if not solutions:
        return [], True

    if expected_count:
        exact = [s for s in solutions if len(s) == expected_count]
        if exact:
            solutions = exact
        else:
            return [], True

    def score_solution(sol):
        unique_bonus = len(set(sol)) * 4
        two_digit_bonus = sum(1 for c in sol if int(c) >= 10) * 2
        count_penalty = abs(len(sol) - (expected_count or max(2, round(len(digits) / 2)))) * 3
        return unique_bonus + two_digit_bonus - count_penalty

    best = sorted(solutions, key=score_solution, reverse=True)[0]
    return best, False


def parse_color_codes_from_spec(spec, product_name=None, sku=None, expected_count=None, known_colors=None):
    """从颜色字段解析 001-030 色号；组合色号会拆成多个颜色。返回 (codes, needs_review)。"""
    field_value, has_color_field = _extract_color_field(spec)
    if not has_color_field:
        return [], False

    expected_count = expected_count or extract_expected_combo_count(product_name, sku, spec)
    value = str(field_value).strip()
    value_wo_sizes = re.sub(r"\b\d{2,3}\s*mm\b", " ", value, flags=re.IGNORECASE)
    value_wo_sizes = re.sub(r"\b\d+(?:\.\d+)?\s*(?:LB|g|kg|m|cm|strand|strands)\b", " ", value_wo_sizes, flags=re.IGNORECASE)

    # 英文颜色名不从描述里的数字硬解析，例如 Color:Green-8 strands。
    if re.search(r"[A-Za-z]", value_wo_sizes):
        return [], True

    tokens = [t for t in re.split(r"[\s,，/、+&]+", value_wo_sizes) if t]
    if len(tokens) > 1:
        parsed = []
        for token in tokens:
            digits = re.sub(r"\D", "", token)
            if not digits:
                continue
            if is_valid_color_code(digits):
                parsed.append(normalize_valid_color(digits))
            else:
                split, issue = _split_digits_to_valid_colors(digits)
                if issue:
                    return [], True
                parsed.extend(split)
        parsed = list(dict.fromkeys(parsed))
        if parsed and (expected_count is None or len(parsed) == expected_count):
            return parsed, False
        if parsed and expected_count and len(parsed) != expected_count:
            split, issue = _split_digits_to_valid_colors("".join(re.sub(r"\D", "", t) for t in tokens), expected_count)
            return split, issue
        return [], True

    digits = re.sub(r"\D", "", value_wo_sizes)
    return _split_digits_to_valid_colors(digits, expected_count)


def parse_color_from_sku_suffix(*texts):
    for text in texts:
        if pd.isna(text):
            continue
        s = str(text).strip()
        for pattern in [r"(?:^|[-_ ])(0?[1-9]|[12]\d|30)$", r"(?:^|[-_ ])(00[1-9]|0[12]\d|030)$"]:
            m = re.search(pattern, s)
            if m and is_valid_color_code(m.group(1)):
                return [normalize_valid_color(m.group(1))], False
    return [], False


def extract_color(text):
    codes, _ = parse_color_codes_from_spec(text)
    return codes[0] if codes else None


def normalize_color(c):
    """统一色号为 3 位字符串，例如 3→003, 4.0→004"""
    if pd.isna(c): return ""
    s = str(c).strip()
    if s.endswith(".0"): s = s[:-2]
    if s.isdigit() and len(s) <= 3: return s.zfill(3)
    return s


def is_valid_normalized_color(c):
    return bool(re.fullmatch(r"0[0-2]\d|030", str(c or "").strip()))


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


SEA_BADGE_COLORS = {
    "强烈推荐": ("#dcfce7", "#166534"),
    "推荐": ("#dbeafe", "#1d4ed8"),
    "可测试": ("#fef3c7", "#92400e"),
    "暂不推荐": ("#f1f5f9", "#475569"),
    "高风险": ("#fee2e2", "#b91c1c"),
    "畅销多色": ("#dcfce7", "#166534"),
    "共购组合": ("#ede9fe", "#6d28d9"),
    "单尺寸特化": ("#f1f5f9", "#475569"),
    "主推尺寸": ("#dcfce7", "#166534"),
    "次推尺寸": ("#dbeafe", "#1d4ed8"),
    "第三尺寸": ("#ede9fe", "#6d28d9"),
    "备选尺寸": ("#fef3c7", "#92400e"),
    "不建议": ("#f1f5f9", "#475569"),
    "是": ("#dcfce7", "#166534"),
    "有限": ("#fef3c7", "#92400e"),
    "否": ("#f1f5f9", "#475569"),
    "高机会": ("#dcfce7", "#166534"),
    "观察": ("#f1f5f9", "#475569"),
}

BRAND_DISPLAY = {
    "LW": "Hunthouse(LW)",
    "DT": "D1",
}


def display_brand(value):
    return BRAND_DISPLAY.get(str(value), value)


def render_metric_cards(items):
    cols = st.columns(min(len(items), 6))
    for col, item in zip(cols, items):
        label, value, help_text = (list(item) + [""])[:3]
        col.metric(label, value, help=help_text or None)


def inject_combo_compact_css():
    st.markdown("""
    <style>
      div[data-testid="stExpander"] details { padding-top: 0 !important; }
      div[data-testid="stExpander"] div[role="button"] p { font-size: 0.9rem; }
      div[data-testid="stVerticalBlock"] { gap: 0.45rem; }
      .combo-hint {
        color: #64748b;
        font-size: 0.84rem;
        line-height: 1.35;
        margin: -0.2rem 0 0.35rem 0;
      }
      .combo-summary {
        background: #eef4ff;
        border: 1px solid #d8e4f8;
        border-radius: 8px;
        padding: 9px 12px;
        color: #1f2937;
        font-size: 0.92rem;
        line-height: 1.45;
        margin: 0.35rem 0 0.45rem 0;
      }
      .combo-kpis {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 7px 10px;
        color: #334155;
        font-size: 0.86rem;
        line-height: 1.45;
        margin: 0.2rem 0 0.35rem 0;
      }
      .combo-section-title {
        font-size: 1rem;
        font-weight: 700;
        color: #0f172a;
        margin: 0.45rem 0 0.2rem 0;
      }
    </style>
    """, unsafe_allow_html=True)


def truncate_text(value, max_len=46):
    if pd.isna(value):
        return ""
    text = str(value)
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def _format_table_value(value):
    if isinstance(value, float):
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return value


def style_table(df):
    badge_cols = [
        c for c in ["海托推荐等级", "风险标签", "组合类型", "组合机会等级", "推荐状态", "是否共用图片"]
        if c in df.columns
    ]
    numeric_cols = df.select_dtypes(include="number").columns.tolist()

    def badge_style(value):
        text = str(value)
        for key, (bg, fg) in SEA_BADGE_COLORS.items():
            if key == text or key in text:
                return f"background-color:{bg}; color:{fg}; font-weight:600; border-radius:6px;"
        return ""

    styler = df.style
    if numeric_cols:
        styler = styler.format({c: _format_table_value for c in numeric_cols})
        styler = styler.set_properties(subset=numeric_cols, **{"text-align": "right"})
    if badge_cols:
        if hasattr(styler, "map"):
            styler = styler.map(badge_style, subset=badge_cols)
        else:
            styler = styler.applymap(badge_style, subset=badge_cols)
    return styler


def show_table(df, columns=None, text_cols=None, height=420):
    if df.empty:
        st.info("暂无数据")
        return
    display_df = df[[c for c in columns if c in df.columns]].copy() if columns else df.copy()
    if "品牌" in display_df.columns:
        display_df["品牌"] = display_df["品牌"].apply(display_brand)
    for col in text_cols or []:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(truncate_text)
    st.dataframe(style_table(display_df), use_container_width=True, hide_index=True, height=height)


def df_to_csv(df):
    return df.to_csv(index=False).encode("utf-8-sig")


def build_combo_preview(combo_df, fallback_text=""):
    if not combo_df.empty and "推荐组合色号" in combo_df.columns:
        combos = combo_df["推荐组合色号"].dropna().astype(str).tolist()
    else:
        combos = [c.strip() for c in str(fallback_text).split(" | ") if c.strip()]
    if not combos:
        return ""
    return f"{combos[0]} 等 {len(combos)} 组"


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

    multi_name_col = None
    for c in orders.columns:
        if "多品名" in str(c) or "品名" in str(c):
            multi_name_col = c
            break

    def parse_row_colors(row):
        product_name = row.get(name_col, "") if name_col else ""
        multi_name = row.get(multi_name_col, "") if multi_name_col else ""
        sku_value = row.get(sku_col, "") if sku_col else ""
        merch_sku = row.get(merch_sku_col, "") if merch_sku_col else ""
        expected = extract_expected_combo_count(product_name, multi_name, sku_value, merch_sku)
        issue = False

        # 1. 产品规格优先，只要有颜色字段就先按它解析。
        if spec_col:
            codes, issue = parse_color_codes_from_spec(
                row.get(spec_col, ""), product_name=f"{product_name} {multi_name}", sku=f"{sku_value} {merch_sku}",
                expected_count=expected,
            )
            if codes:
                return codes, issue
            field_value, has_color_field = _extract_color_field(row.get(spec_col, ""))
            if has_color_field:
                fallback_codes, fallback_issue = parse_color_from_sku_suffix(merch_sku, sku_value)
                return fallback_codes, issue or fallback_issue or not bool(fallback_codes)

        # 2. 多品名 / 商品SKU / SKU / 商品编码。
        for value in [multi_name, merch_sku, sku_value]:
            codes, field_issue = parse_color_codes_from_spec(
                value, product_name=f"{product_name} {multi_name}", sku=f"{sku_value} {merch_sku}",
                expected_count=expected,
            )
            if codes:
                return codes, issue or field_issue
            issue = issue or field_issue

        fallback_codes, fallback_issue = parse_color_from_sku_suffix(merch_sku, sku_value)
        return fallback_codes, issue or fallback_issue

    parsed = orders.apply(parse_row_colors, axis=1)
    orders["_colors"] = parsed.apply(lambda x: x[0])
    orders["_color_parse_issue"] = parsed.apply(lambda x: bool(x[1]))
    orders["_colors"] = orders["_colors"].apply(
        lambda codes: [c for c in codes if is_valid_color_code(c)] if isinstance(codes, list) else []
    )
    orders["_color"] = orders["_colors"].apply(lambda codes: codes[0] if codes else None)

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

    # 组合包订单拆成多条颜色贡献；无色号订单保留但不进入颜色/共购推荐。
    orders["_colors"] = orders["_colors"].apply(lambda codes: codes if codes else [None])
    orders = orders.explode("_colors").copy()
    orders["_color"] = orders["_colors"]
    orders.drop(columns=["_colors"], inplace=True)

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
        n_pkgs=("_pkg", "nunique") if "_pkg" in orders else ("_qty", "sum"),
        n_colors=("_color", lambda x: x.dropna().nunique()),
        has_fr=("_is_fr", "any"), has_it=("_is_it", "any"),
        refund_rate=("_refund_flag", "mean"),
        month_cover=("_time", lambda x: x.dt.to_period("M").nunique()) if "_time" in orders else ("_qty", "sum"),
    ).reset_index()

    agg = agg[agg["_size"].notna() & (agg["_size"] != "")]
    if agg.empty: return pd.DataFrame()

    for c in ["FR_sales", "IT_sales", "total_qty", "n_orders", "n_pkgs"]:
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
        "n_pkgs": "包裹数",
        "n_colors": "有销量色号数", "month_cover": "月份覆盖数",
    })
    final["销量占比"] = (final["总销量"] / final.groupby("产品型号")["总销量"].transform("sum") * 100).round(1).astype(str) + "%"
    cols = ["产品型号", "尺寸", "法国销量", "意大利销量", "总销量", "订单数", "包裹数",
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
    color_orders = orders[
        orders["_color"].notna() &
        (orders["_color"] != "") &
        orders["_color"].apply(is_valid_normalized_color)
    ]
    merged = color_orders.merge(
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

    orders = orders[
        orders["_color"].notna() &
        (orders["_color"] != "") &
        orders["_color"].apply(is_valid_normalized_color)
    ].copy()
    if orders.empty: return pd.DataFrame()

    pairs = []
    group_cols = []
    if "_order" in orders.columns: group_cols.append("_order")
    if "_pkg" in orders.columns: group_cols.append("_pkg")

    for gcols in [["_order", "_product", "_size"], ["_pkg", "_product", "_size"]]:
        g = [c for c in gcols if c in orders.columns]
        if len(g) < 2: continue
        is_pkg = "_pkg" in g
        for _, grp in orders.groupby(g):
            if len(grp) < 2: continue
            colors = sorted({normalize_color(c) for c in grp["_color"].unique() if normalize_color(c)})
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
def _combo_key(combo):
    return tuple(sorted(normalize_color(c) for c in combo if normalize_color(c)))


def _applicable_sizes(combo, color_sizes_map):
    size_sets = [set(color_sizes_map.get(c, set())) for c in set(combo)]
    if not size_sets:
        return []
    common = set.intersection(*size_sets)
    return sorted(common)


def _build_color_tiers(prod_colors, co_purchase_map):
    """按销量、订单、推荐分和共购强度把颜色分为热卖/稳定/弱色。"""
    if prod_colors.empty:
        return {}, {}, []

    colors = prod_colors.copy()
    colors["色号"] = colors["色号"].apply(normalize_color)
    colors["总销量"] = pd.to_numeric(colors["总销量"], errors="coerce").fillna(0)
    colors["订单数"] = pd.to_numeric(colors.get("订单数", 0), errors="coerce").fillna(0)
    colors["颜色推荐分"] = pd.to_numeric(colors["颜色推荐分"], errors="coerce").fillna(0)
    colors = colors[(colors["色号"] != "") & (colors["总销量"] > 0) & (colors["订单数"] > 0)]
    if colors.empty:
        return {}, {}, []

    co_strength = {}
    for (a, b), score in co_purchase_map.items():
        co_strength[a] = co_strength.get(a, 0) + score
        co_strength[b] = co_strength.get(b, 0) + score
    colors["_co_strength"] = colors["色号"].map(co_strength).fillna(0)

    def norm(series):
        max_v = max(float(series.max()), 1)
        return series / max_v

    colors["_balanced_rank"] = (
        norm(colors["总销量"]) * 0.45 +
        norm(colors["订单数"]) * 0.25 +
        norm(colors["颜色推荐分"]) * 0.20 +
        norm(colors["_co_strength"]) * 0.10
    )
    colors = colors.sort_values("_balanced_rank", ascending=False).reset_index(drop=True)

    n_colors = len(colors)
    hot_cut = max(1, int(n_colors * 0.20 + 0.999))
    stable_cut = max(hot_cut + 1, int(n_colors * 0.60 + 0.999))
    avg_sales = max(float(colors["总销量"].mean()), 1)
    score_q80 = float(colors["颜色推荐分"].quantile(0.80)) if n_colors > 1 else float(colors["颜色推荐分"].max())

    tier_map = {}
    for idx, row in colors.iterrows():
        color = row["色号"]
        if idx < hot_cut or row["总销量"] >= avg_sales * 1.30 or row["颜色推荐分"] >= score_q80:
            tier = "热卖色"
        elif idx < stable_cut:
            tier = "稳定色"
        else:
            tier = "弱色"
        tier_map[color] = tier

    # 数据集中如果强弱分布不明显，也强制保留最低位颜色为弱色，用于色卡铺货测试。
    if "弱色" not in tier_map.values() and n_colors >= 3:
        weak_n = max(1, int(n_colors * 0.20 + 0.999))
        for color in colors.tail(weak_n)["色号"]:
            if tier_map.get(color) != "热卖色":
                tier_map[color] = "弱色"
    if "稳定色" not in tier_map.values() and n_colors >= 2:
        for color in colors["色号"]:
            if tier_map.get(color) != "热卖色":
                tier_map[color] = "稳定色"
                break

    tier_colors = {
        "热卖色": [c for c in colors["色号"] if tier_map.get(c) == "热卖色"],
        "稳定色": [c for c in colors["色号"] if tier_map.get(c) == "稳定色"],
        "弱色": [c for c in colors["色号"] if tier_map.get(c) == "弱色"],
    }
    return tier_map, tier_colors, colors["色号"].tolist()


def _balanced_patterns(combo_size):
    if combo_size == 2:
        return [
            ("爆款带货", {"热卖色": 1, "稳定色": 1, "弱色": 0}),
            ("爆款带货", {"热卖色": 1, "稳定色": 0, "弱色": 1}),
            ("色卡覆盖", {"热卖色": 0, "稳定色": 1, "弱色": 1}),
            ("色卡覆盖", {"热卖色": 0, "稳定色": 2, "弱色": 0}),
        ]
    if combo_size == 3:
        return [
            ("均衡铺货", {"热卖色": 1, "稳定色": 1, "弱色": 1}),
            ("色卡覆盖", {"热卖色": 1, "稳定色": 2, "弱色": 0}),
            ("铺货测试", {"热卖色": 0, "稳定色": 2, "弱色": 1}),
            ("爆款带货", {"热卖色": 1, "稳定色": 0, "弱色": 2}),
        ]
    if combo_size == 4:
        return [
            ("均衡铺货", {"热卖色": 1, "稳定色": 2, "弱色": 1}),
            ("铺货测试", {"热卖色": 1, "稳定色": 1, "弱色": 2}),
            ("色卡覆盖", {"热卖色": 0, "稳定色": 3, "弱色": 1}),
            ("爆款带货", {"热卖色": 2, "稳定色": 1, "弱色": 1}),
        ]
    if combo_size == 5:
        return [
            ("均衡铺货", {"热卖色": 1, "稳定色": 2, "弱色": 2}),
            ("爆款带货", {"热卖色": 2, "稳定色": 2, "弱色": 1}),
            ("色卡覆盖", {"热卖色": 1, "稳定色": 3, "弱色": 1}),
            ("铺货测试", {"热卖色": 1, "稳定色": 1, "弱色": 3}),
        ]
    return [
        ("均衡铺货", {"热卖色": 2, "稳定色": 2, "弱色": 2}),
        ("色卡覆盖", {"热卖色": 1, "稳定色": 3, "弱色": 2}),
        ("铺货测试", {"热卖色": 1, "稳定色": 2, "弱色": 3}),
        ("爆款带货", {"热卖色": 2, "稳定色": 3, "弱色": 1}),
    ]


def _tier_choices(colors, count, allow_repeat, limit=80):
    if count == 0:
        return [()]
    if not colors:
        return []
    colors = list(colors)
    if count <= len(colors):
        return list(combinations(colors, count))[:limit]
    if not allow_repeat:
        return []
    choices = []
    for combo in combinations_with_replacement(colors, count):
        if len(set(combo)) > 1:
            choices.append(combo)
        if len(choices) >= limit:
            break
    return choices


def _score_balanced_combo(combo, base_type, tier_map, color_score_map, color_sales_map,
                          color_cover_map, color_sizes_map, co_purchase_map, rec_sizes,
                          selected_keys=None):
    clist = list(combo)
    tiers = [tier_map.get(c, "稳定色") for c in clist]
    tier_counts = {tier: tiers.count(tier) for tier in ["热卖色", "稳定色", "弱色"]}

    sales_values = [color_sales_map.get(c, 0) for c in clist]
    score_values = [color_score_map.get(c, 0) for c in clist]
    sales_support = min(100, (sum(score_values) / max(len(score_values), 1)) * 0.65 +
                        (min(sales_values) / max(max(color_sales_map.values()), 1)) * 35)

    present_tiers = sum(1 for v in tier_counts.values() if v > 0)
    balance_score = {1: 45, 2: 75, 3: 100}.get(present_tiers, 60)
    if tier_counts["弱色"] > max(1, len(clist) // 2):
        balance_score -= 18
    if tier_counts["热卖色"] > 2:
        balance_score -= 12

    co_raw = 0
    pair_count = 0
    strongest_pair = None
    strongest_pair_score = 0
    for i in range(len(clist)):
        for j in range(i + 1, len(clist)):
            if clist[i] == clist[j]:
                continue
            pair = (min(clist[i], clist[j]), max(clist[i], clist[j]))
            pair_score = co_purchase_map.get(pair, 0)
            co_raw += pair_score
            pair_count += 1
            if pair_score > strongest_pair_score:
                strongest_pair_score = pair_score
                strongest_pair = pair
    co_score = min(100, (co_raw / max(pair_count, 1)) * 8)

    has_anchor = tier_counts["热卖色"] + tier_counts["稳定色"] > 0
    if tier_counts["弱色"] == 0:
        weak_score = 62
    elif has_anchor and tier_counts["弱色"] <= max(1, len(clist) // 2):
        weak_score = 100
    elif has_anchor:
        weak_score = 68
    else:
        weak_score = 20

    selected_keys = selected_keys or []
    if selected_keys:
        max_overlap = max(len(set(clist) & set(key)) / max(len(clist), 1) for key in selected_keys)
        difference_score = max(25, 100 - max_overlap * 85)
    else:
        difference_score = 100

    total = (
        sales_support * 0.25 +
        balance_score * 0.25 +
        co_score * 0.20 +
        weak_score * 0.15 +
        difference_score * 0.15
    )
    if len(set(clist)) == 1:
        total -= 40
    if tier_counts["弱色"] == len(clist):
        total -= 35
    total = max(0, min(100, total))

    ctype = base_type
    if strongest_pair_score > 0 and co_score >= 18:
        ctype = "共购组合"
    elif tier_counts["弱色"] >= 2 or (tier_counts["弱色"] >= 1 and tier_counts["热卖色"] == 0):
        ctype = "铺货测试"
    elif tier_counts["热卖色"] >= 1 and tier_counts["弱色"] >= 1:
        ctype = "爆款带货"
    elif present_tiers >= 3:
        ctype = "均衡铺货"
    elif ctype not in ["均衡铺货", "色卡覆盖", "爆款带货", "铺货测试", "共购组合"]:
        ctype = "色卡覆盖"

    applicable = _applicable_sizes(clist, color_sizes_map)
    min_cov = min(color_cover_map.get(c, 0) for c in clist)
    return total, ctype, co_score, max(len(applicable), min_cov), applicable, tier_counts, strongest_pair


def _combo_reason(combo, ctype, tier_map, strongest_pair=None):
    by_tier = {"热卖色": [], "稳定色": [], "弱色": []}
    for color in combo:
        by_tier.setdefault(tier_map.get(color, "稳定色"), []).append(color)
    hot = "、".join(by_tier.get("热卖色", []))
    stable = "、".join(by_tier.get("稳定色", []))
    weak = "、".join(by_tier.get("弱色", []))
    parts = []
    if hot:
        parts.append(f"热卖色 {hot}")
    if stable:
        parts.append(f"稳定色 {stable}")
    if weak:
        parts.append(f"长尾色 {weak}")

    if ctype == "共购组合" and strongest_pair:
        return f"共购组合：{strongest_pair[0]} 与 {strongest_pair[1]} 同单/同包裹出现较多，同时覆盖" + "、".join(parts) + "。"
    if ctype == "爆款带货":
        return f"爆款带货：包含{('、'.join(parts))}，用热卖或稳定颜色带动长尾色。"
    if ctype == "铺货测试":
        return f"铺货测试：包含{('、'.join(parts))}，适合补齐色卡并少量上传观察。"
    if ctype == "色卡覆盖":
        return f"色卡覆盖：包含{('、'.join(parts))}，用于减少颜色重复、扩大色卡覆盖。"
    return f"均衡铺货：包含{('、'.join(parts))}，适合扩展色卡。"


def _combo_note(ctype, tier_counts, has_top1):
    notes = []
    if tier_counts.get("弱色", 0) > 0:
        notes.append("包含长尾色，建议少量测试。")
    if ctype in ["铺货测试", "色卡覆盖", "均衡铺货"]:
        notes.append("该组合偏铺货，不是纯销量最优。")
    if has_top1:
        notes.append("热卖色已限制重复，组合更偏均衡覆盖。")
    return " ".join(notes)


def generate_product_combos(orders, recommended_sizes, color_scores,
                            combo_size=3, max_combos=6, co_purchase_df=None,
                            allow_color_repeat=True, excluded_colors=None):
    """均衡铺货优先：热卖色、稳定色、弱色分层生成组合，并控制颜色重复。"""
    if orders.empty or recommended_sizes.empty or color_scores.empty:
        return {}, pd.DataFrame()
    if co_purchase_df is None:
        co_purchase_df = pd.DataFrame()
    excluded_colors = {
        normalize_valid_color(c)
        for c in (excluded_colors or [])
        if normalize_valid_color(c)
    }

    product_combos_preview = {}
    all_combo_rows = []

    for prod in recommended_sizes["产品型号"].unique():
        prod_colors = color_scores[color_scores["产品型号"] == prod].copy()
        prod_colors["色号"] = prod_colors["色号"].apply(normalize_color)
        prod_colors = prod_colors[prod_colors["色号"].apply(is_valid_normalized_color)]
        if excluded_colors:
            prod_colors = prod_colors[~prod_colors["色号"].isin(excluded_colors)]
        if len(prod_colors) < 2: continue

        prod_sizes = recommended_sizes[
            (recommended_sizes["产品型号"] == prod) &
            (recommended_sizes["推荐状态"].isin(["主推尺寸", "次推尺寸", "第三尺寸"]))
        ]
        rec_sizes = prod_sizes["尺寸"].tolist()
        if not rec_sizes: continue

        n = max(1, int(max_combos))

        co_purchase_map = {}
        if not co_purchase_df.empty:
            cp = co_purchase_df[(co_purchase_df["产品型号"] == prod) & (co_purchase_df["尺寸"].isin(rec_sizes))]
            for _, r in cp.iterrows():
                a = normalize_color(r["色号A"])
                b = normalize_color(r["色号B"])
                if a and b and is_valid_normalized_color(a) and is_valid_normalized_color(b):
                    if a in excluded_colors or b in excluded_colors:
                        continue
                    key = (min(a, b), max(a, b))
                    co_purchase_map[key] = co_purchase_map.get(key, 0) + r["共购分"]

        tier_map, tier_colors, all_colors = _build_color_tiers(prod_colors, co_purchase_map)
        if len(all_colors) < 2:
            continue

        color_pool = all_colors[:min(len(all_colors), max(18, n * combo_size))]
        pool = prod_colors.copy()
        pool["色号"] = pool["色号"].apply(normalize_color)
        pool = pool[pool["色号"].isin(color_pool)]
        color_score_map = dict(zip(pool["色号"], pool["颜色推荐分"]))
        color_cover_map = dict(zip(pool["色号"], pool["推荐尺寸覆盖数"]))
        color_sales_map = dict(zip(pool["色号"], pool["总销量"]))
        top1 = all_colors[0]

        prod_rec_orders = orders[
            (orders["_product"] == prod) &
            (orders["_size"].isin(rec_sizes)) &
            (orders["_color"].notna()) &
            (orders["_color"] != "")
        ].copy()
        prod_rec_orders["_color"] = prod_rec_orders["_color"].apply(normalize_color)
        prod_rec_orders = prod_rec_orders[
            prod_rec_orders["_color"].apply(is_valid_normalized_color) &
            ~prod_rec_orders["_color"].isin(excluded_colors)
        ]
        color_sizes_map = {
            c: set(g["_size"].dropna().tolist())
            for c, g in prod_rec_orders.groupby("_color")
        }

        candidates = {}

        def add_candidate(combo, ctype):
            key = _combo_key(combo)
            if len(key) != combo_size:
                return
            if any(c in excluded_colors for c in key):
                return
            if any(not is_valid_normalized_color(c) for c in key):
                return
            if any(color_sales_map.get(c, 0) <= 0 for c in key):
                return
            if not allow_color_repeat and len(set(key)) < len(key):
                return
            if len(set(key)) == 1:
                return
            weak_count = sum(1 for c in key if tier_map.get(c) == "弱色")
            anchor_count = sum(1 for c in key if tier_map.get(c) in ["热卖色", "稳定色"])
            if weak_count == len(key) or (weak_count >= 2 and anchor_count == 0):
                return
            candidates.setdefault(key, {"combo": key, "base_type": ctype})

        # 1) 按颜色层级结构生成均衡铺货候选。
        for ctype, pattern in _balanced_patterns(combo_size):
            choice_groups = []
            valid_pattern = True
            for tier in ["热卖色", "稳定色", "弱色"]:
                count = pattern.get(tier, 0)
                colors = [c for c in tier_colors.get(tier, []) if c in color_pool]
                choices = _tier_choices(colors, count, allow_color_repeat)
                if not choices:
                    valid_pattern = False
                    break
                choice_groups.append(choices)
            if not valid_pattern:
                continue
            for parts in product(*choice_groups):
                combo = []
                for part in parts:
                    combo.extend(part)
                add_candidate(combo, ctype)
                if len(candidates) >= max(300, n * 60):
                    break

        # 2) 色卡覆盖候选：从全颜色池中铺开，鼓励差异化和长尾覆盖。
        if combo_size <= len(color_pool):
            for combo in combinations(color_pool[:min(len(color_pool), 18)], combo_size):
                tier_counts = {tier: sum(1 for c in combo if tier_map.get(c) == tier) for tier in ["热卖色", "稳定色", "弱色"]}
                if tier_counts["弱色"] > max(1, combo_size // 2):
                    continue
                add_candidate(combo, "色卡覆盖")
                if len(candidates) >= max(420, n * 80):
                    break

        # 3) 共购组合：保留明显同购证据，但补足时仍优先带入稳定/弱色。
        if co_purchase_map:
            co_pairs = sorted(co_purchase_map.items(), key=lambda x: x[1], reverse=True)
            for (a, b), score in co_pairs[:max(20, n * 4)]:
                if a in color_pool and b in color_pool and a != b:
                    partners = sorted(
                        [c for c in color_pool if c not in (a, b)],
                        key=lambda c: (
                            8 if tier_map.get(c) == "弱色" else (5 if tier_map.get(c) == "稳定色" else 2),
                            co_purchase_map.get((min(a, c), max(a, c)), 0) +
                            co_purchase_map.get((min(b, c), max(b, c)), 0),
                            color_score_map.get(c, 0)
                        ),
                        reverse=True,
                    )
                    base = [a, b] + partners[:max(combo_size - 2, 0)]
                    if len(base) == combo_size:
                        add_candidate(base, "共购组合")

        scored = []
        for cand in candidates.values():
            total, ctype, co, min_cov, applicable, tier_counts, strongest_pair = _score_balanced_combo(
                cand["combo"], cand["base_type"], tier_map, color_score_map, color_sales_map,
                color_cover_map, color_sizes_map, co_purchase_map, rec_sizes
            )
            scored.append({
                "score": total,
                "combo_tuple": cand["combo"],
                "type": ctype,
                "co_score": co,
                "min_cov": min_cov,
                "applicable_sizes": applicable,
                "_key": cand["combo"],
                "contains_top1": top1 in cand["combo"],
                "top1_count": cand["combo"].count(top1),
                "tier_counts": tier_counts,
                "strongest_pair": strongest_pair,
            })
        scored.sort(key=lambda x: x["score"], reverse=True)

        total_slots = n * combo_size
        top1_slot_limit = max(1, int(total_slots * 0.38 + 0.999))
        top1_combo_limit = max(1, int(n * 0.60 + 0.999))
        color_slot_limit = max(2, int(total_slots * 0.32 + 0.999))
        selected = []
        color_usage = {}

        def too_similar(item, strict=True):
            if not selected:
                return False
            max_shared = combo_size - 1 if strict else combo_size
            return any(len(set(item["_key"]) & set(s["_key"])) >= max_shared for s in selected)

        def can_add(item, strict=True, enforce_top1=True):
            if len(selected) >= n:
                return False
            if any(s["_key"] == item["_key"] for s in selected):
                return False
            if strict and too_similar(item, strict=True):
                return False
            projected_top1_slots = sum(s["top1_count"] for s in selected) + item["top1_count"]
            projected_top1_combos = sum(1 for s in selected if s["contains_top1"]) + (1 if item["contains_top1"] else 0)
            if enforce_top1 and (projected_top1_slots > top1_slot_limit or projected_top1_combos > top1_combo_limit):
                return False
            for color in item["_key"]:
                if color_usage.get(color, 0) + item["_key"].count(color) > color_slot_limit:
                    return False
            return True

        def add_selected(item):
            selected.append(item)
            for color in item["_key"]:
                color_usage[color] = color_usage.get(color, 0) + 1

        # 先保障弱色合理覆盖，再选高分组合。
        weak_candidates = [item for item in scored if item["tier_counts"].get("弱色", 0) > 0]
        for item in weak_candidates:
            if len(selected) >= min(n, max(2, n // 2)):
                break
            if can_add(item, strict=True, enforce_top1=True):
                add_selected(item)

        for item in scored:
            if len(selected) >= n:
                break
            if can_add(item, strict=True, enforce_top1=True):
                add_selected(item)

        # 候选足够但相似度过严时，放宽相似度；仍控制 Top1 和重复。
        if len(selected) < n:
            for item in scored:
                if len(selected) >= n:
                    break
                if can_add(item, strict=False, enforce_top1=True):
                    add_selected(item)

        # 最后一轮只放宽 Top1 软限制，避免有效候选足够却无法补满；仍不允许重复组合。
        if len(selected) < n:
            for item in scored:
                if len(selected) >= n:
                    break
                if can_add(item, strict=False, enforce_top1=False):
                    add_selected(item)

        # ---- 输出 ----
        previews = []
        for s in selected:
            formatted = format_combo(s["combo_tuple"])
            previews.append(formatted)
            applicable_sizes = s["applicable_sizes"] or rec_sizes[:1]
            display_type = s["type"]
            reason = _combo_reason(s["combo_tuple"], display_type, tier_map, s["strongest_pair"])
            note = _combo_note(display_type, s["tier_counts"], s["contains_top1"])
            if len(rec_sizes) > 1 and len(applicable_sizes) <= 1:
                note = f"{note} 单尺寸特化，不建议做共用图片".strip()
            all_combo_rows.append({
                "产品型号": prod,
                "推荐尺寸": " / ".join(rec_sizes),
                "组合类型": display_type,
                "推荐组合色号": formatted,
                "组合件数": combo_size,
                "是否共用图片": "是" if len(applicable_sizes) >= len(rec_sizes) else ("有限" if len(applicable_sizes) >= 2 else "否"),
                "适用尺寸": " / ".join(applicable_sizes),
                "组合推荐分": round(s["score"], 1),
                "推荐理由": reason,
                "注意事项": note,
            })

        product_combos_preview[prod] = " | ".join(previews[:max_combos])

    combo_df = pd.DataFrame(all_combo_rows).sort_values(["产品型号", "组合推荐分"], ascending=[True, False]) if all_combo_rows else pd.DataFrame()
    return product_combos_preview, combo_df


# ============================================================
# 渲染
# ============================================================
def store_order_upload(uploaded_file, source):
    if not uploaded_file:
        return None
    file_bytes = uploaded_file.getvalue()
    file_id = f"{uploaded_file.name}:{getattr(uploaded_file, 'size', len(file_bytes))}"
    if st.session_state.get("_order_file_id") != file_id:
        st.session_state["_order_file_id"] = file_id
        st.session_state["_order_file_name"] = uploaded_file.name
        st.session_state["_order_file_bytes"] = file_bytes
        for key in list(st.session_state.keys()):
            if str(key).startswith("_sea_freight_combo_cache_") or str(key).startswith("_daily_combo_cache_"):
                del st.session_state[key]
    st.session_state["_order_file_source"] = source
    return file_bytes


def get_order_bytes():
    return st.session_state.get("_order_file_bytes")


def load_order_context(file_bytes):
    if not file_bytes:
        return None
    df, sku_col, qty_col, refund_col, country_col, time_col, name_col, store_col, spec_col, merch_sku_col = load_orders(file_bytes)
    return {
        "df": df,
        "sku_col": sku_col,
        "qty_col": qty_col,
        "refund_col": refund_col,
        "country_col": country_col,
        "time_col": time_col,
        "name_col": name_col,
        "store_col": store_col,
        "spec_col": spec_col,
        "merch_sku_col": merch_sku_col,
    }


def prepare_orders_from_context(ctx, fr_only, it_only, start_date, end_date):
    return prepare_orders(
        ctx["df"], ctx["sku_col"], ctx["qty_col"], ctx["refund_col"], ctx["country_col"],
        ctx["name_col"], ctx["store_col"], ctx["spec_col"], ctx["merch_sku_col"],
        fr_only, it_only, pd.Timestamp(start_date), pd.Timestamp(end_date)
    )


def render_order_upload(label, key, source):
    uploaded = st.file_uploader(label, type=["xlsx"], key=key)
    if uploaded:
        store_order_upload(uploaded, source)
    elif get_order_bytes():
        st.caption(f"已读取订单表：{st.session_state.get('_order_file_name', '已上传文件')}，可重新上传。")
    else:
        st.info("请先上传订单表。")
    return get_order_bytes()


def add_risk_label(prod_df):
    if prod_df.empty or "退款风险" not in prod_df.columns:
        return prod_df
    out = prod_df.copy()
    risk = pd.to_numeric(out["退款风险"].astype(str).str.rstrip("%"), errors="coerce").fillna(0)
    out["风险标签"] = risk.apply(lambda v: "高风险" if v >= 15 else "正常")
    return out


def clean_product_rank(prod_df):
    if prod_df.empty:
        return prod_df
    out = add_risk_label(prod_df.copy())
    out = out.drop(columns=[c for c in ["推荐组合", "推荐理由"] if c in out.columns])
    return out


def filter_brand(orders, brand_choice):
    if orders.empty or brand_choice == "ALL":
        return orders
    return orders[orders["_brand"] == brand_choice].copy()


def summarize_orders(orders):
    if orders.empty:
        render_metric_cards([
            ("有效订单行数", "0", ""),
            ("产品数", "0", ""),
            ("色号数", "0", ""),
            ("尺寸数", "0", ""),
        ])
        return
    fr_orders = orders[orders["_is_fr"]]
    it_orders = orders[orders["_is_it"]]
    render_metric_cards([
        ("有效订单行数", f"{len(orders):,}", "清洗后参与分析的订单行"),
        ("产品数", f"{orders['_product'].nunique():,}", "识别到的产品型号"),
        ("色号数", f"{orders['_color'].dropna().nunique():,}", "识别到的色号"),
        ("尺寸数", f"{orders['_size'].dropna().nunique():,}", "识别到的尺寸"),
        ("法国销量", f"{int(fr_orders['_qty'].sum()):,}", "法国订单销量"),
        ("意大利销量", f"{int(it_orders['_qty'].sum()):,}", "意大利订单销量"),
    ])
    issue_count = int(orders.get("_color_parse_issue", pd.Series(False, index=orders.index)).fillna(False).sum())
    invalid_count = int(
        orders["_color"].notna().sum() -
        orders[orders["_color"].notna()]["_color"].apply(is_valid_normalized_color).sum()
    )
    if issue_count or invalid_count:
        st.warning("存在未能拆分的组合色号或英文颜色名规格，已排除或需人工复核。")


def analyze_combo_quantity(orders, product, sizes=None):
    prod_orders = orders[(orders["_product"] == product) & orders["_size"].notna()].copy()
    if sizes:
        prod_orders = prod_orders[prod_orders["_size"].isin(sizes)]
    if prod_orders.empty:
        return pd.DataFrame(columns=["同购件数", "出现次数", "占比"]), 3, 2, "该产品暂无可用同购数据，建议先测试 2-3 件组合。", True

    group_sources = []
    for group_id in ["_order", "_pkg"]:
        if group_id in prod_orders.columns:
            grouped = prod_orders.groupby([group_id, "_product", "_size"])["_qty"].sum().reset_index()
            grouped["_source"] = group_id
            group_sources.append(grouped)
    if not group_sources:
        grouped = prod_orders.groupby(["_product", "_size"])["_qty"].sum().reset_index()
        grouped["_source"] = "rows"
    else:
        grouped = pd.concat(group_sources, ignore_index=True)

    grouped["_combo_qty"] = grouped["_qty"].clip(lower=1).round().astype(int)
    dist = grouped[grouped["_combo_qty"].between(2, 6)]["_combo_qty"].value_counts().sort_index()
    total_groups = max(len(grouped), 1)
    if dist.empty:
        rows = pd.DataFrame({"同购件数": [2, 3], "出现次数": [0, 0], "占比": ["0.0%", "0.0%"]})
        return rows, 3, 2, "该产品同购行为较弱，建议先测试 2-3 件组合。", True

    dist_df = dist.rename_axis("同购件数").reset_index(name="出现次数")
    dist_df["占比值"] = dist_df["出现次数"] / total_groups
    dist_df["占比"] = (dist_df["占比值"] * 100).round(1).astype(str) + "%"
    ranked = dist_df.sort_values(["出现次数", "同购件数"], ascending=[False, True]).reset_index(drop=True)
    primary = int(ranked.loc[0, "同购件数"])
    backup = int(ranked.loc[1, "同购件数"]) if len(ranked) > 1 else (3 if primary != 3 else 2)
    weak = float(ranked.loc[0, "占比值"]) < 0.12 or int(ranked.loc[0, "出现次数"]) < 3
    if weak:
        reason = "该产品同购行为较弱，建议先测试 2-3 件组合。"
    else:
        backup_part = f"，{backup} 件同购占比 {ranked.loc[1, '占比']}" if len(ranked) > 1 else ""
        reason = f"{primary} 件同购占比 {ranked.loc[0, '占比']}{backup_part}。"
    return dist_df.drop(columns=["占比值"]), primary, backup, reason, weak


def get_product_options(prod_df):
    if prod_df.empty:
        return []
    return prod_df["产品型号"].dropna().astype(str).sort_values().tolist()


def parse_excluded_colors(text):
    if not text:
        return []
    colors = []
    for token in re.split(r"[\s,，、/;+]+", str(text)):
        color = normalize_valid_color(token)
        if color:
            colors.append(color)
    return sorted(set(colors))


def get_product_color_options(orders, product):
    if orders.empty or not product or "_product" not in orders.columns or "_color" not in orders.columns:
        return []
    product = str(product).strip().upper()
    colors = (
        orders.loc[orders["_product"] == product, "_color"]
        .dropna()
        .astype(str)
        .map(normalize_color)
    )
    return sorted({c for c in colors if is_valid_normalized_color(c)})


def generate_single_product_result(orders, product, min_sales, max_combos, allow_repeat,
                                   size_scope, cache_prefix, force_combo_size=None, cache_context="",
                                   excluded_colors=None):
    product = product.strip().upper()
    if not product:
        return None
    excluded_colors = sorted({
        normalize_valid_color(c)
        for c in (excluded_colors or [])
        if normalize_valid_color(c)
    })
    excluded_key = ",".join(excluded_colors)

    size_df = size_analysis(orders, min_sales)
    prod_size_df = size_df[size_df["产品型号"] == product].copy() if not size_df.empty else pd.DataFrame()
    if prod_size_df.empty:
        return {"error": f"未找到 {product} 的尺寸销量数据。"}

    statuses = ["主推尺寸", "次推尺寸", "第三尺寸"]
    if size_scope == "包含备选尺寸":
        statuses.append("备选尺寸")
    recommended_sizes = prod_size_df[prod_size_df["推荐状态"].isin(statuses)].copy()
    if recommended_sizes.empty:
        recommended_sizes = prod_size_df.head(1).copy()

    rec_sizes = recommended_sizes["尺寸"].dropna().tolist()
    dist_df, primary_size, backup_size, qty_reason, weak_combo = analyze_combo_quantity(orders, product, rec_sizes)
    combo_size = force_combo_size or primary_size
    if combo_size < 2:
        combo_size = 3

    cache_key = (
        f"{cache_prefix}_balanced_stock_v4_{product}_{min_sales}_{max_combos}_{allow_repeat}_"
        f"{size_scope}_{combo_size}_{cache_context}_{','.join(rec_sizes)}_excluded_{excluded_key}"
    )
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    prod_orders = orders[orders["_product"] == product].copy()
    product_basic = product_analysis(prod_orders)
    color_df = color_analysis(prod_orders, product_basic, recommended_sizes)
    co_purchase_df = build_co_purchase_table(prod_orders)
    _, combo_df = generate_product_combos(
        prod_orders, recommended_sizes, color_df, combo_size, max_combos, co_purchase_df,
        allow_color_repeat=allow_repeat, excluded_colors=excluded_colors
    ) if not color_df.empty else ({}, pd.DataFrame())

    if not combo_df.empty:
        if excluded_colors and "推荐组合色号" in combo_df.columns:
            combo_df = combo_df[
                ~combo_df["推荐组合色号"].astype(str).apply(
                    lambda value: any(color in re.split(r"[、,，\s/]+", value) for color in excluded_colors)
                )
            ].copy()
        combo_df = combo_df.rename(columns={"推荐尺寸": "尺寸"})
        combo_df = combo_df[[
            "产品型号", "尺寸", "组合件数", "推荐组合色号", "组合类型",
            "组合推荐分", "推荐理由", "注意事项"
        ]]
    generated_count = len(combo_df)
    shortage_note = ""
    if generated_count < int(max_combos):
        shortage_note = (
            f"排除色号后有效候选不足，仅生成 {generated_count} 组。"
            if excluded_colors else
            f"有效候选不足，仅生成 {generated_count} 组。"
        )

    product_row = product_analysis(prod_orders).head(1)
    product_row = add_risk_label(product_row)
    shared_image = "是"
    if not color_df.empty and color_df["推荐尺寸覆盖数"].max() < max(len(rec_sizes), 1):
        shared_image = "有限"

    result = {
        "product": product,
        "brand": display_brand(product[:2]),
        "product_row": product_row,
        "size_df": prod_size_df,
        "recommended_sizes": rec_sizes,
        "combo_size": combo_size,
        "backup_combo_size": backup_size,
        "quantity_distribution": dist_df,
        "quantity_reason": qty_reason,
        "weak_combo": weak_combo,
        "combo_df": combo_df,
        "target_combos": int(max_combos),
        "generated_count": generated_count,
        "shortage_note": shortage_note,
        "color_df": color_df,
        "shared_image": shared_image,
        "excluded_colors": excluded_colors,
    }
    st.session_state[cache_key] = result
    return result


def render_product_combo_generator(orders, prod_df, module_key, cache_prefix,
                                   default_country_label="法国+意大利", cache_context=""):
    inject_combo_compact_css()
    st.subheader("产品组合生成器")
    st.markdown(
        "<div class='combo-hint'>当前组合策略：均衡铺货优先。热卖色不会过度重复，系统会尽量把稳定色和长尾色分散到不同组合中。</div>",
        unsafe_allow_html=True,
    )
    product_options = get_product_options(prod_df)
    input_cols = st.columns([1.25, 1.2, 0.85, 0.75, 0.8])
    with input_cols[0]:
        selected_product = st.selectbox(
            "产品型号",
            options=[""] + product_options,
            format_func=lambda x: "选择产品型号" if x == "" else x,
            key=f"{module_key}_product_select",
        )
    with input_cols[1]:
        product_input = st.text_input("或输入产品型号", value="", placeholder="例如 LW546", key=f"{module_key}_product_input")
    with input_cols[2]:
        max_combos = st.slider("每产品最大组合数", 6, 10, 6, key=f"{module_key}_max_combos")
    with input_cols[3]:
        allow_repeat = st.checkbox("允许同色重复", value=True, key=f"{module_key}_allow_repeat")
    with input_cols[4]:
        st.write("")
        generate_clicked = st.button("生成组合建议", type="primary", key=f"{module_key}_generate")

    product = (product_input or selected_product or "").strip().upper()
    excluded_from_select = []
    manual_excluded = []
    color_options = get_product_color_options(orders, product) if product else []
    exclude_cols = st.columns([1.6, 1.1])
    with exclude_cols[0]:
        excluded_from_select = st.multiselect(
            "排除色号",
            options=color_options,
            placeholder="请先选择产品型号" if not product else "选择不参与组合的色号",
            disabled=not bool(product),
            key=f"{module_key}_excluded_colors",
        )
    with exclude_cols[1]:
        excluded_text = st.text_input(
            "手动输入排除色号",
            value="",
            placeholder="例如 001,014,019",
            disabled=not bool(product),
            key=f"{module_key}_excluded_text",
        )
        manual_excluded = parse_excluded_colors(excluded_text) if product else []
    if product:
        if not color_options:
            st.caption("当前产品暂无可识别的 001-030 色号。")
    else:
        st.caption("请先选择产品型号后再选择排除色号。")
    excluded_colors = sorted(set(excluded_from_select) | set(manual_excluded))

    with st.expander("高级筛选", expanded=False):
        a1, a2, a3 = st.columns([0.8, 1.1, 0.9])
        with a1:
            min_sales = st.number_input("最低销量阈值", 1, 1000, 20, key=f"{module_key}_min_sales")
        with a2:
            size_scope = st.selectbox("推荐尺寸范围", ["推荐尺寸（主推/次推/第三）", "包含备选尺寸"], key=f"{module_key}_size_scope")
        with a3:
            manual_combo_size = st.selectbox("组合件数", ["自动判断", 2, 3, 4, 5, 6], key=f"{module_key}_manual_combo_size")
        st.caption(f"当前数据范围：{default_country_label}。筛选条件只影响当前产品组合生成。")

    if generate_clicked:
        force = None if manual_combo_size == "自动判断" else int(manual_combo_size)
        with st.spinner("正在生成单产品组合建议..."):
            result = generate_single_product_result(
                orders, product, min_sales, max_combos, allow_repeat, size_scope,
                cache_prefix, force, cache_context, excluded_colors=excluded_colors
            )
        st.session_state[f"{module_key}_last_result"] = result

    result = st.session_state.get(f"{module_key}_last_result")
    if not result:
        st.info("输入产品型号后点击生成组合建议。")
        return
    if result.get("error"):
        st.warning(result["error"])
        return

    product_row = result["product_row"]
    total_qty = int(product_row["总销量"].iloc[0]) if not product_row.empty and "总销量" in product_row else 0
    fr_qty = int(product_row["法国销量"].iloc[0]) if not product_row.empty and "法国销量" in product_row else 0
    it_qty = int(product_row["意大利销量"].iloc[0]) if not product_row.empty and "意大利销量" in product_row else 0
    refund = product_row["退款风险"].iloc[0] if not product_row.empty and "退款风险" in product_row else "-"

    summary = (
        f"<b>{result['product']}</b>｜{result['brand']}｜主推 {result['combo_size']} 件｜"
        f"备选 {result['backup_combo_size']} 件｜推荐尺寸：{' / '.join(result['recommended_sizes']) or '暂无'}｜"
        f"共用图片：{result['shared_image']}"
    )
    st.markdown(f"<div class='combo-summary'>{summary}</div>", unsafe_allow_html=True)
    excluded_status = "、".join(result.get("excluded_colors") or [])
    st.caption(f"已排除色号：{excluded_status}" if excluded_status else "未排除色号")
    kpi_line = (
        f"法国销量 {fr_qty:,}｜意大利销量 {it_qty:,}｜总销量 {total_qty:,}｜"
        f"退款风险 {refund}｜主要购买尺寸 {' / '.join(result['recommended_sizes'][:3]) or '-'}｜{result['quantity_reason']}"
    )
    st.markdown(f"<div class='combo-kpis'>{kpi_line}</div>", unsafe_allow_html=True)
    with st.expander("同购件数分布", expanded=False):
        show_table(result["quantity_distribution"], height=180)

    st.markdown(
        f"<div class='combo-section-title'>推荐组合表（{result.get('generated_count', len(result['combo_df']))}组）</div>",
        unsafe_allow_html=True,
    )
    if result["combo_df"].empty:
        if result.get("shortage_note"):
            st.warning(result["shortage_note"])
        st.warning("该产品暂无足够颜色或共购数据生成组合。")
    else:
        if result.get("shortage_note"):
            st.warning(result["shortage_note"])
        else:
            st.caption(f"已按当前设置生成 {result.get('generated_count', len(result['combo_df']))} / {result.get('target_combos', len(result['combo_df']))} 组。")
        show_table(result["combo_df"], text_cols=["推荐理由", "注意事项"], height=420)

    notes = []
    if result["weak_combo"]:
        notes.append("该产品同购行为较弱，建议首批先测试 2-3 件组合。")
    if result["shared_image"] != "是":
        notes.append("部分颜色或尺寸覆盖不足，共用图片组合需要谨慎。")
    if not product_row.empty and "风险标签" in product_row and product_row["风险标签"].iloc[0] == "高风险":
        notes.append("退款风险偏高，建议谨慎备货。")
    if not notes:
        notes.append("当前产品未发现明显组合风险，可结合库存和图片资源安排测试。")
    st.caption("；".join(notes))


def render_product_size_detail(size_df, prod_df, module_key):
    st.subheader("单产品尺寸详情")
    options = get_product_options(prod_df)
    selected = st.selectbox(
        "查看产品尺寸详情",
        options=[""] + options,
        format_func=lambda x: "选择产品型号" if x == "" else x,
        key=f"{module_key}_size_detail_product",
    )
    if not selected:
        st.info("选择产品型号后查看不同尺寸明细。")
        return
    detail = size_df[size_df["产品型号"] == selected].copy() if not size_df.empty else pd.DataFrame()
    if detail.empty:
        st.warning(f"暂无 {selected} 的尺寸明细。")
        return
    detail = detail.rename(columns={"推荐状态": "尺寸状态", "不推荐原因": "备注"})
    cols = [
        "产品型号", "尺寸", "法国销量", "意大利销量", "总销量", "订单数",
        "有销量色号数", "月份覆盖数", "尺寸推荐分", "尺寸状态", "备注",
    ]
    show_table(detail, cols, height=360)

def render_sea_freight_tab():
    st.header("意法海托")
    file_bytes = render_order_upload("上传订单表", "sea_freight_upload", "sea_freight")
    if not file_bytes:
        return

    ctx = load_order_context(file_bytes)
    if ctx is None or ctx["df"].empty:
        st.error("订单表为空或无法读取。")
        return

    df = ctx["df"]
    if "_time" in df.columns and df["_time"].notna().any():
        min_d = df["_time"].min().date()
        max_d = df["_time"].max().date()
    else:
        min_d = pd.Timestamp("2020-01-01").date()
        max_d = pd.Timestamp.now().date()

    st.subheader("数据摘要")
    orders_base = prepare_orders_from_context(ctx, True, True, min_d, max_d)
    if orders_base.empty:
        st.warning("订单表中没有识别到法国/意大利有效订单。")
        return
    summarize_orders(orders_base)

    prod_df_rank = clean_product_rank(product_analysis(orders_base))
    size_df_rank = size_analysis(orders_base, 20)

    st.markdown("---")
    with st.expander("产品组合生成器筛选条件", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            fr_only = st.checkbox("法国", value=True, key="sf_gen_fr")
            it_only = st.checkbox("意大利", value=True, key="sf_gen_it")
        with c2:
            brand_choice = st.selectbox(
                "品牌", ["ALL", "LW", "DT"],
                format_func=lambda x: "全部" if x == "ALL" else display_brand(x),
                key="sf_gen_brand",
            )
        with c3:
            date_range = st.date_input(
                "时间范围", value=(min_d, max_d), min_value=min_d, max_value=max_d, key="sf_gen_date"
            )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = min_d, max_d

    orders = prepare_orders_from_context(ctx, fr_only, it_only, start_date, end_date)
    orders = filter_brand(orders, brand_choice)
    if orders.empty:
        st.warning("当前筛选条件下无有效订单。")
    else:
        prod_df_gen = clean_product_rank(product_analysis(orders))
        render_product_combo_generator(
            orders, prod_df_gen, "sea_freight", "_sea_freight_combo_cache", "法国+意大利",
            f"{fr_only}_{it_only}_{brand_choice}_{start_date}_{end_date}"
        )

    st.markdown("---")
    st.subheader("产品级海托排行榜")
    st.caption("主表只回答哪些产品值得做意法海托；组合建议请在上方输入产品型号生成。")
    product_cols = [
        "产品型号", "品牌", "法国销量", "意大利销量", "总销量", "总订单数", "包裹数",
        "有销量尺寸数", "有销量色号数", "月份覆盖数", "退款风险", "风险标签", "海托推荐等级",
    ]
    show_table(prod_df_rank, product_cols, height=430)

    render_product_size_detail(size_df_rank, prod_df_rank, "sea_freight")


def combo_opportunity_analysis(orders):
    if orders.empty:
        return pd.DataFrame()
    base = product_analysis(orders)
    if base.empty:
        return base
    rows = []
    co_df = build_co_purchase_table(orders)
    co_counts = co_df.groupby("产品型号")["共购分"].sum().to_dict() if not co_df.empty else {}
    for _, row in base.iterrows():
        product = row["产品型号"]
        total = max(int(row["总销量"]), 1)
        co_score = co_counts.get(product, 0)
        color_n = int(row["有销量色号数"])
        size_n = int(row["有销量尺寸数"])
        opportunity_score = min(100, co_score * 2 + color_n * 5 + size_n * 3 + min(total, 300) / 6)
        if opportunity_score >= 75:
            level = "高机会"
        elif opportunity_score >= 45:
            level = "可测试"
        else:
            level = "观察"
        rows.append({
            "产品型号": product,
            "品牌": row["品牌"],
            "总销量": row["总销量"],
            "总订单数": row["总订单数"],
            "包裹数": row["包裹数"],
            "有销量尺寸数": row["有销量尺寸数"],
            "有销量色号数": row["有销量色号数"],
            "月份覆盖数": row["月份覆盖数"],
            "共购强度": round(co_score, 1),
            "组合机会分": round(opportunity_score, 1),
            "组合机会等级": level,
        })
    return pd.DataFrame(rows).sort_values("组合机会分", ascending=False)


def render_combo_analysis_tab():
    st.header("组合分析")
    file_bytes = render_order_upload("上传订单表", "combo_analysis_upload", "combo_analysis")
    if not file_bytes:
        return

    ctx = load_order_context(file_bytes)
    if ctx is None or ctx["df"].empty:
        st.error("订单表为空或无法读取。")
        return

    df = ctx["df"]
    if "_time" in df.columns and df["_time"].notna().any():
        min_d = df["_time"].min().date()
        max_d = df["_time"].max().date()
    else:
        min_d = pd.Timestamp("2020-01-01").date()
        max_d = pd.Timestamp.now().date()

    with st.expander("组合分析筛选条件", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            brand_choice = st.selectbox(
                "品牌", ["ALL", "LW", "DT"],
                format_func=lambda x: "全部" if x == "ALL" else display_brand(x),
                key="combo_brand",
            )
        with c2:
            date_range = st.date_input(
                "时间范围", value=(min_d, max_d), min_value=min_d, max_value=max_d, key="combo_date"
            )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = min_d, max_d

    orders = prepare_orders_from_context(ctx, False, False, start_date, end_date)
    orders = filter_brand(orders, brand_choice)
    if orders.empty:
        st.warning("当前筛选条件下无有效订单。")
        return

    st.subheader("数据摘要")
    summarize_orders(orders)

    prod_df = combo_opportunity_analysis(orders)
    render_product_combo_generator(
        orders, prod_df,
        "combo_analysis", "_daily_combo_cache", "全部国家",
        f"all_{brand_choice}_{start_date}_{end_date}"
    )

    st.markdown("---")
    st.subheader("产品级组合机会表")
    st.caption("该表用于日常店铺组合销售，不使用海托推荐等级。")
    cols = [
        "产品型号", "品牌", "总销量", "总订单数", "包裹数", "有销量尺寸数",
        "有销量色号数", "月份覆盖数", "共购强度", "组合机会分", "组合机会等级",
    ]
    show_table(prod_df, cols, height=460)
