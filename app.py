import streamlit as st
import pandas as pd
import re
import io
import plotly.express as px
from io import BytesIO
from config import APP_VERSION
from sea_freight import render_combo_analysis_tab, render_sea_freight_tab

# ============================================================
# PAGE CONFIG & STYLE
# ============================================================
st.set_page_config(page_title="Hunthouse & D1", layout="wide")
st.markdown("""
<style>
  :root {
    --bg: #f6f7f9;
    --card: #ffffff;
    --line: #e5e7eb;
    --muted: #64748b;
    --text: #0f172a;
  }
  .stApp { background: var(--bg); color: var(--text); }
  header[data-testid="stHeader"] { background: transparent !important; }
  .block-container { padding-top: 2rem; padding-bottom: 3rem; }
  h1, h2, h3 { letter-spacing: 0; color: var(--text); }
  h1 { font-size: 1.75rem !important; font-weight: 750 !important; }
  h2 { font-size: 1.35rem !important; }
  h3 { font-size: 1.05rem !important; }
  .stTabs [data-baseweb="tab"] {
    font-weight: 600;
    border-radius: 8px 8px 0 0;
    padding: 10px 16px;
  }
  .stExpander {
    border-radius: 8px;
    border: 1px solid var(--line);
    box-shadow: none;
    background: var(--card);
  }
  div[data-testid="stMetric"] {
    background: var(--card);
    border-radius: 8px;
    padding: 14px 16px;
    border: 1px solid var(--line);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }
  div[data-testid="stMetric"] label {
    color: var(--muted);
    font-size: 0.82rem;
  }
  .stPlotlyChart, div[data-testid="stDataFrame"], div[data-testid="stTable"] {
    background: var(--card);
    border-radius: 8px;
    padding: 10px;
    border: 1px solid var(--line);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }
  .section-note {
    color: var(--muted);
    font-size: 0.9rem;
    margin: -0.25rem 0 0.65rem 0;
  }
</style>
""", unsafe_allow_html=True)
st.title("Hunthouse & D1")
st.caption(APP_VERSION)

# ============================================================
# CONSTANTS
# ============================================================
LEVEL_ORDER     = ["🟩 热销", "🟩 主销", "🟨 弱动销", "🟥 滞销", "💀 死库存"]
LEVEL_LABELS    = {
    "🟩 热销":  "热销（90天销量 ≥ 300）",
    "🟩 主销":  "主销（90天销量 50~299）",
    "🟨 弱动销": "弱动销（90天销量 30~49）",
    "🟥 滞销":  "滞销（90天销量 1~29）",
    "💀 死库存": "死库存（90天销量 = 0）",
}
COLOR_MAP = {
    "🟩 热销":  "#10b981",
    "🟩 主销":  "#6366f1",
    "🟨 弱动销": "#f59e0b",
    "🟥 滞销":  "#ef4444",
    "💀 死库存": "#94a3b8",
    "🆕 新品池": "#0ea5e9",
}

BADGE_COLORS = {
    "强烈推荐": ("#dcfce7", "#166534"),
    "推荐": ("#dbeafe", "#1d4ed8"),
    "可测试": ("#fef3c7", "#92400e"),
    "暂不推荐": ("#f1f5f9", "#475569"),
    "高风险": ("#fee2e2", "#b91c1c"),
    "极高风险": ("#fee2e2", "#991b1b"),
    "中风险": ("#fef3c7", "#92400e"),
    "低风险": ("#dbeafe", "#1d4ed8"),
    "优质": ("#dcfce7", "#166534"),
    "新品观察": ("#e0f2fe", "#0369a1"),
    "热销": ("#dcfce7", "#166534"),
    "主销": ("#dbeafe", "#1d4ed8"),
    "弱动销": ("#fef3c7", "#92400e"),
    "滞销": ("#fee2e2", "#b91c1c"),
    "死库存": ("#f1f5f9", "#475569"),
    "新品池": ("#e0f2fe", "#0369a1"),
}

BRAND_DISPLAY = {
    "LW": "Hunthouse(LW)",
    "DT": "D1",
}


def display_brand(value):
    return BRAND_DISPLAY.get(str(value), value)


def strip_status_icon(value):
    text = str(value)
    return re.sub(r"^[^\w\u4e00-\u9fff]+\s*", "", text)


def render_overview_cards(items):
    """展示统一的顶部指标卡。items: [(标题, 值, 说明)]"""
    if not items:
        return
    cols = st.columns(min(len(items), 6))
    for col, item in zip(cols, items):
        label, value, help_text = (list(item) + [""])[:3]
        col.metric(label, value, help=help_text or None)


def _format_value(v):
    if isinstance(v, float):
        return f"{v:,.1f}"
    if isinstance(v, int):
        return f"{v:,}"
    return v


def _truncate_text(v, max_len=42):
    if pd.isna(v):
        return ""
    s = str(v)
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


def style_dataframe(df):
    badge_cols = [c for c in ["海托推荐等级", "风险等级", "产品分类", "销售动作", "处理建议"] if c in df.columns]
    numeric_cols = df.select_dtypes(include="number").columns.tolist()

    def badge_style(val):
        text = str(val)
        for key, (bg, fg) in BADGE_COLORS.items():
            if key in text:
                return f"background-color:{bg}; color:{fg}; font-weight:600; border-radius:6px;"
        return ""

    styler = df.style
    if numeric_cols:
        styler = styler.format({c: _format_value for c in numeric_cols})
        styler = styler.set_properties(subset=numeric_cols, **{"text-align": "right"})
    if badge_cols:
        if hasattr(styler, "map"):
            styler = styler.map(badge_style, subset=badge_cols)
        else:
            styler = styler.applymap(badge_style, subset=badge_cols)
    return styler

# ============================================================
# ① 产品识别
# ============================================================
def extract_product(name):
    name = str(name).strip()
    m = re.search(r"\b(LW\d{3,4}|DT\d{3,5})\b", name)
    return m.group(1) if m else None

# ============================================================
# ② 产品分类
# ============================================================
def classify_product(sales_90d, is_new=False):
    if is_new:
        return "🆕 新品池"
    if sales_90d >= 300: return "🟩 热销"
    elif sales_90d >= 50: return "🟩 主销"
    elif sales_90d >= 30: return "🟨 弱动销"
    elif sales_90d >= 1:  return "🟥 滞销"
    else:                 return "💀 死库存"

# ============================================================
# ③ 决策引擎
# ============================================================
def compute_sales_action(sales_90d, is_new=False):
    if is_new:
        return "🟦 新品观察（不清仓、不降级）"
    if sales_90d == 0:   return "🟥 清仓（停广告+降价）"
    elif sales_90d < 30: return "🟥 强清仓"
    elif sales_90d < 50: return "🟨 优化测试"
    elif sales_90d < 300: return "🟧 放量"
    else:                return "🟩 扩量"

def compute_risk_level(sales_90d, stock, is_new=False):
    if is_new:
        return "新品观察"
    if sales_90d == 0 and stock > 0:
        return "极高风险"
    elif sales_90d < 30 and stock >= 50:
        return "高风险"
    elif 30 <= sales_90d < 50:
        return "中风险"
    elif 50 <= sales_90d < 300:
        return "低风险"
    else:
        return "优质"

def compute_clear_score(sales_90d, inventory_value):
    if sales_90d == 0:
        return 100000 + max(inventory_value, 0)
    return round(inventory_value / (sales_90d + 1), 2)

def compute_priority_score(inventory_value, sales_90d):
    return round(inventory_value / (sales_90d + 1), 2)

def compute_recommendation(priority_score, sales_90d, level):
    if priority_score >= 1000 and sales_90d < 30:
        return "🟥 必须立即清仓（资金卡死）"
    elif priority_score >= 100:
        return "🟧 尽快处理（低周转）"
    elif sales_90d >= 50:
        return "🟩 可以放量"
    else:
        return "🟨 观察优化"

def compute_health_score(sales_90d, inventory_value, is_new=False):
    if is_new:
        return 75
    if sales_90d >= 300: base = 92
    elif sales_90d >= 50: base = 80
    elif sales_90d >= 30: base = 68
    elif sales_90d >= 1: base = 50
    else: base = 30
    if sales_90d > 0 and inventory_value > 0:
        ratio = inventory_value / (sales_90d + 1)
        if ratio > 100: base -= 12
        elif ratio > 50: base -= 8
        elif ratio > 10: base -= 4
        elif ratio < 1: base += 5
    return max(0, min(100, base))

# ============================================================
# ④ 数据加载（缓存）
# ============================================================
@st.cache_data
def load_data(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes))
    if "商品名称" not in df.columns:
        st.error("Excel 文件中缺少「商品名称」列，无法识别产品。")
        st.stop()

    col_sku = [c for c in df.columns if c.upper() == "SKU"]
    col_sku = col_sku[0] if col_sku else None

    col_price = [c for c in df.columns if "单价" in c]
    col_price = col_price[0] if col_price else None

    col_amount = [c for c in df.columns if "总价" in c or "金额" in c or "销售额" in c]
    col_amount = col_amount[0] if col_amount else None

    col_create = [c for c in df.columns if any(k in c for k in ["创建", "时间", "上架", "日期"])]
    col_create = col_create[0] if col_create else None

    df["产品ID"] = df["商品名称"].apply(extract_product)
    before = len(df)
    df = df[df["产品ID"].notnull()].copy()
    filtered = before - len(df)
    df["品牌"] = df["产品ID"].apply(lambda x: x[:2])

    # 新品标记
    if col_create:
        df[col_create] = pd.to_datetime(df[col_create], errors="coerce")
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=90)
        df["_is_new"] = df[col_create] >= cutoff
    else:
        df["_is_new"] = False

    # 库存金额 = 可用库存 × 单价
    if col_price:
        df["库存金额"] = df["可用库存"] * df[col_price]
    elif col_amount:
        df["库存金额"] = df[col_amount]
    else:
        df["库存金额"] = 0

    return df, col_sku, col_amount, col_price, col_create, filtered

# ============================================================
# ⑤ 聚合 + 全字段
# ============================================================
def aggregate_and_enrich(df_brand, col_sku, col_amount):
    """产品层 + SKU 层聚合，附加所有 V5.3 字段"""
    agg_dict = {"可用库存": "sum", "90天内销量": "sum", "库存金额": "sum"}
    if col_amount:
        agg_dict[col_amount] = "sum"

    # 产品层
    prod = df_brand.groupby("产品ID").agg(agg_dict).reset_index()
    prod["_is_new"] = df_brand.groupby("产品ID")["_is_new"].any().values
    prod["产品分类"] = prod.apply(lambda r: classify_product(r["90天内销量"], r["_is_new"]), axis=1)
    prod["销售动作"] = prod.apply(lambda r: compute_sales_action(r["90天内销量"], r["_is_new"]), axis=1)
    prod["风险等级"] = prod.apply(lambda r: compute_risk_level(r["90天内销量"], r["可用库存"], r["_is_new"]), axis=1)
    prod["清仓评分"] = prod.apply(lambda r: compute_clear_score(r["90天内销量"], r["库存金额"]), axis=1)
    prod["优先级评分"] = prod.apply(lambda r: compute_priority_score(r["库存金额"], r["90天内销量"]), axis=1)
    prod["处理建议"] = prod.apply(lambda r: compute_recommendation(r["优先级评分"], r["90天内销量"], r["产品分类"]), axis=1)
    prod["周转率"] = prod.apply(
        lambda r: f"{round(r['90天内销量'] / (r['可用库存'] + 1) * 100, 1)}%", axis=1
    )
    prod["产品健康评分"] = prod.apply(lambda r: compute_health_score(r["90天内销量"], r["库存金额"], r["_is_new"]), axis=1)
    prod.drop(columns=["_is_new"], inplace=True)

    # SKU 层
    sku = None
    if col_sku:
        sku = df_brand.groupby(col_sku).agg(agg_dict).reset_index()
        sku["产品ID"] = sku[col_sku].map(
            df_brand.drop_duplicates(col_sku).set_index(col_sku)["产品ID"]
        )
        sku["_is_new"] = df_brand.groupby(col_sku)["_is_new"].any().values
        sku["产品分类"] = sku.apply(lambda r: classify_product(r["90天内销量"], r["_is_new"]), axis=1)
        sku["销售动作"] = sku.apply(lambda r: compute_sales_action(r["90天内销量"], r["_is_new"]), axis=1)
        sku["风险等级"] = sku.apply(lambda r: compute_risk_level(r["90天内销量"], r["可用库存"], r["_is_new"]), axis=1)
        sku["清仓评分"] = sku.apply(lambda r: compute_clear_score(r["90天内销量"], r["库存金额"]), axis=1)
        sku["优先级评分"] = sku.apply(lambda r: compute_priority_score(r["库存金额"], r["90天内销量"]), axis=1)
        sku["处理建议"] = sku.apply(lambda r: compute_recommendation(r["优先级评分"], r["90天内销量"], r["产品分类"]), axis=1)
        sku.drop(columns=["_is_new"], inplace=True)

    return prod, sku

# ============================================================
# ⑥ 图表
# ============================================================
def make_pie(labels, values, title, color_map):
    display_labels = [strip_status_icon(label) for label in labels]
    display_color_map = {strip_status_icon(k): v for k, v in color_map.items()}
    df_pie = pd.DataFrame({"等级": display_labels, "数量": values})
    df_pie = df_pie[df_pie["数量"] > 0]
    if df_pie.empty:
        return None
    fig = px.pie(
        df_pie, names="等级", values="数量", color="等级",
        color_discrete_map=display_color_map, category_orders={"等级": list(display_color_map.keys())}, hole=0.4,
    )
    fig.update_traces(
        textposition="inside", textinfo="percent", textfont_size=12,
        textfont_color="#475569", marker=dict(line=dict(color="white", width=2)),
        hovertemplate="<b>%{label}</b><br>%{value} 个<br>%{percent}<extra></extra>",
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#64748b")),
        showlegend=False, margin=dict(t=40, b=10, l=10, r=10),
        height=240, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig

def show_table(df, cols, sort_by=None, ascending=False):
    """统一的表格渲染"""
    avail = [c for c in cols if c in df.columns]
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=ascending)
    display_df = df[avail].copy()
    if "品牌" in display_df.columns:
        display_df["品牌"] = display_df["品牌"].apply(display_brand)
    for c in ["产品分类", "销售动作", "处理建议"]:
        if c in display_df.columns:
            display_df[c] = display_df[c].apply(strip_status_icon)
    for c in ["处理建议", "推荐理由"]:
        if c in display_df.columns:
            display_df[c] = display_df[c].apply(_truncate_text)
    st.dataframe(style_dataframe(display_df), use_container_width=True, hide_index=True)

# ============================================================
# ⑦ 渲染：库存分析（保留原有饼图+折叠表）
# ============================================================
def render_analysis(prod, sku, col_sku, col_amount, brand):
    st.header(display_brand(brand))
    if prod.empty:
        st.info("无该品牌产品")
        return
    render_overview_cards([
        ("分析产品数", f"{len(prod):,}", "当前品牌识别到的产品数量"),
        ("热销/主销", f"{len(prod[prod['产品分类'].isin(['🟩 热销', '🟩 主销'])]):,}", "适合重点补货和放量的产品"),
        ("高风险产品", f"{len(prod[prod['风险等级'].isin(['极高风险', '高风险'])]):,}", "极高风险和高风险产品"),
        ("库存金额", f"¥{prod['库存金额'].sum():,.0f}", "当前品牌库存资金占用"),
    ])

    # 产品层
    st.subheader("产品")
    st.markdown("<div class='section-note'>按产品聚合查看库存、销量、健康评分和处理动作。</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    all_levels = list(COLOR_MAP.keys())
    with c1:
        prod_counts = [len(prod[prod["产品分类"] == lv]) for lv in all_levels]
        fig1 = make_pie(all_levels, prod_counts, "产品数量占比（按分类）", COLOR_MAP)
        if fig1: st.plotly_chart(fig1, use_container_width=True)
        else: st.info("无数据")
    with c2:
        if col_amount:
            prod_amounts = [prod[prod["产品分类"] == lv][col_amount].sum() for lv in all_levels]
            fig2 = make_pie(all_levels, prod_amounts, f"产品金额占比（{col_amount}）", COLOR_MAP)
            if fig2: st.plotly_chart(fig2, use_container_width=True)
            else: st.info("无数据")
        else:
            st.info("未识别到金额列")

    for lv in all_levels:
        sub = prod[prod["产品分类"] == lv]
        if not sub.empty:
            with st.expander(f"{LEVEL_LABELS.get(lv, lv)} — {len(sub)} 个产品", expanded=False):
                cols = ["产品ID", "可用库存", "90天内销量", "库存金额", "周转率",
                        "产品健康评分", "销售动作", "风险等级", "清仓评分", "处理建议"]
                show_table(sub, cols, "90天内销量", False)

    st.divider()
    st.subheader("SKU")
    st.markdown("<div class='section-note'>SKU 维度用于定位具体库存项，适合执行补货、清仓或广告动作。</div>", unsafe_allow_html=True)
    if sku is None:
        st.info("未识别到 SKU 列")
        return
    c3, c4 = st.columns(2)
    with c3:
        sku_counts = [len(sku[sku["产品分类"] == lv]) for lv in all_levels]
        fig3 = make_pie(all_levels, sku_counts, "SKU 数量占比（按分类）", COLOR_MAP)
        if fig3: st.plotly_chart(fig3, use_container_width=True)
        else: st.info("无数据")
    with c4:
        if col_amount:
            sku_amounts = [sku[sku["产品分类"] == lv][col_amount].sum() for lv in all_levels]
            fig4 = make_pie(all_levels, sku_amounts, f"SKU 金额占比（{col_amount}）", COLOR_MAP)
            if fig4: st.plotly_chart(fig4, use_container_width=True)
            else: st.info("无数据")
        else:
            st.info("未识别到金额列")
    for lv in all_levels:
        sub = sku[sku["产品分类"] == lv]
        if not sub.empty:
            with st.expander(f"{LEVEL_LABELS.get(lv, lv)} — {len(sub)} 个 SKU", expanded=False):
                cols = [col_sku, "产品ID", "可用库存", "90天内销量", "库存金额",
                        "销售动作", "风险等级", "清仓评分", "处理建议"]
                show_table(sub, cols, "90天内销量", False)

# ============================================================
# ⑧ 渲染：新品池
# ============================================================
def render_new_products(prod, sku, col_sku, col_amount, has_create_time):
    st.header("新品监控")
    if not has_create_time:
        st.info("未检测到「创建时间」列，无法识别新品。新品池暂为空。")
        return
    p_new = prod[prod["产品分类"] == "🆕 新品池"]
    render_overview_cards([
        ("新品产品数", f"{len(p_new):,}", "创建时间在 90 天内的产品"),
        ("新品库存金额", f"¥{p_new['库存金额'].sum():,.0f}", "新品池库存资金占用"),
        ("新品销量", f"{p_new['90天内销量'].sum():,}", "新品近 90 天销量"),
        ("新品 SKU", f"{len(sku[sku['产品分类'] == '🆕 新品池']):,}" if sku is not None else "0", "新品 SKU 数量"),
    ])
    if not p_new.empty:
        st.caption("定义：创建时间 ≤ 90天。新品不进入清仓/风险系统，统一标记为「新品观察」。")
        cols = ["产品ID", "可用库存", "90天内销量", "库存金额", "周转率", "销售动作", "产品健康评分"]
        show_table(p_new, cols, "库存金额", False)
        st.metric("新品库存金额合计", f"¥{p_new['库存金额'].sum():,.0f}")
    if sku is not None:
        s_new = sku[sku["产品分类"] == "🆕 新品池"]
        if not s_new.empty:
            st.markdown(f"**新品 SKU：{len(s_new)} 个**")
            cols = [col_sku, "产品ID", "可用库存", "90天内销量", "库存金额", "销售动作"]
            show_table(s_new, cols, "库存金额", False)

# ============================================================
# ⑨ 渲染：清仓清单
# ============================================================
def render_clearance(prod, sku, col_sku, col_amount):
    st.header("清仓清单")
    p_clear = prod[prod["销售动作"].isin(["🟥 清仓（停广告+降价）", "🟥 强清仓"])]
    p_clear = p_clear.sort_values("清仓评分", ascending=False)
    render_overview_cards([
        ("清仓产品数", f"{len(p_clear):,}", "触发清仓或强清仓动作的产品"),
        ("死库存", f"{len(p_clear[p_clear['90天内销量'] == 0]):,}", "90 天内销量为 0 的清仓产品"),
        ("清仓库存金额", f"¥{p_clear['库存金额'].sum():,.0f}", "清仓产品库存资金占用"),
        ("最高清仓评分", f"{p_clear['清仓评分'].max():,.0f}" if not p_clear.empty else "0", "分数越高越优先处理"),
    ])
    st.caption("按清仓评分从高到低排列，分数越高越优先处理。")
    if not p_clear.empty:
        cols = ["产品ID", "可用库存", "90天内销量", "库存金额", "周转率", "风险等级", "清仓评分", "优先级评分", "处理建议"]
        show_table(p_clear, cols)
        c1, c2 = st.columns(2)
        c1.metric("清仓产品库存金额", f"¥{p_clear['库存金额'].sum():,.0f}")
        c2.metric("死库存（0销量）", len(p_clear[p_clear["90天内销量"] == 0]))
    if sku is not None:
        s_clear = sku[sku["销售动作"].isin(["🟥 清仓（停广告+降价）", "🟥 强清仓"])]
        s_clear = s_clear.sort_values("清仓评分", ascending=False)
        if not s_clear.empty:
            st.markdown(f"**清仓 SKU：{len(s_clear)} 个**")
            cols = [col_sku, "产品ID", "可用库存", "90天内销量", "库存金额", "清仓评分", "优先级评分", "处理建议"]
            show_table(s_clear, cols)

# ============================================================
# ⑩ 渲染：放量清单
# ============================================================
def render_scaleup(prod, sku, col_sku, col_amount):
    st.header("放量清单")
    p_scale = prod[prod["销售动作"].isin(["🟩 扩量", "🟧 放量"])]
    p_scale = p_scale.sort_values("90天内销量", ascending=False)
    render_overview_cards([
        ("放量产品数", f"{len(p_scale):,}", "触发扩量或放量动作的产品"),
        ("90天销量", f"{p_scale['90天内销量'].sum():,}", "放量产品近 90 天销量"),
        ("库存金额", f"¥{p_scale['库存金额'].sum():,.0f}", "放量产品库存资金占用"),
        ("平均健康分", f"{p_scale['产品健康评分'].mean():.1f}" if not p_scale.empty else "0", "产品健康评分均值"),
    ])
    st.caption("热销和主销产品，适合加广告、扩颜色/尺寸。")
    if not p_scale.empty:
        cols = ["产品ID", "可用库存", "90天内销量", "库存金额", "周转率", "产品健康评分", "销售动作", "处理建议"]
        show_table(p_scale, cols, "90天内销量", False)
        c1, c2 = st.columns(2)
        c1.metric("放量产品库存金额", f"¥{p_scale['库存金额'].sum():,.0f}")
        c2.metric("总销量（90天）", f"{p_scale['90天内销量'].sum():,}")
    if sku is not None:
        s_scale = sku[sku["销售动作"].isin(["🟩 扩量", "🟧 放量"])]
        s_scale = s_scale.sort_values("90天内销量", ascending=False)
        if not s_scale.empty:
            st.markdown(f"**放量 SKU：{len(s_scale)} 个**")
            cols = [col_sku, "产品ID", "可用库存", "90天内销量", "库存金额", "销售动作"]
            show_table(s_scale, cols, "90天内销量", False)

# ============================================================
# ⑪ 渲染：风险清单
# ============================================================
def render_risk(prod, sku, col_sku, col_amount):
    st.header("风险清单")
    p_risk = prod[prod["风险等级"].isin(["极高风险", "高风险", "中风险"])]
    risk_order = {"极高风险": 0, "高风险": 1, "中风险": 2}
    p_risk["_r"] = p_risk["风险等级"].map(risk_order)
    p_risk = p_risk.sort_values(["_r", "库存金额"], ascending=[True, False])
    p_risk.drop(columns=["_r"], inplace=True)
    render_overview_cards([
        ("风险产品数", f"{len(p_risk):,}", "极高风险、高风险和中风险产品"),
        ("高风险以上", f"{len(p_risk[p_risk['风险等级'].isin(['极高风险', '高风险'])]):,}", "需要优先关注的产品"),
        ("风险库存金额", f"¥{p_risk['库存金额'].sum():,.0f}", "风险产品库存资金占用"),
        ("中风险产品", f"{len(p_risk[p_risk['风险等级'] == '中风险']):,}", "中风险产品数量"),
    ])
    if not p_risk.empty:
        cols = ["产品ID", "可用库存", "90天内销量", "库存金额", "周转率", "风险等级", "产品健康评分", "处理建议"]
        show_table(p_risk, cols)
        # 风险统计
        for rk in ["极高风险", "高风险", "中风险"]:
            sub = p_risk[p_risk["风险等级"] == rk]
            if not sub.empty:
                st.caption(f"{rk}：{len(sub)} 个，库存金额 ¥{sub['库存金额'].sum():,.0f}")
    if sku is not None:
        s_risk = sku[sku["风险等级"].isin(["极高风险", "高风险", "中风险"])]
        if not s_risk.empty:
            st.markdown(f"**风险 SKU：{len(s_risk)} 个**")
            cols = [col_sku, "产品ID", "可用库存", "90天内销量", "库存金额", "风险等级"]
            show_table(s_risk, cols)

# ============================================================
# ⑫ 渲染：领导决策清单
# ============================================================
def render_leader(prod, sku, col_sku, col_amount):
    st.header("领导决策清单")
    st.caption("按优先级评分从高到低排列。评分 = 库存金额 ÷ (90天销量 + 1)，资金占用越严重、销量越低，评分越高。")

    # 统计卡片
    p0 = prod[prod["处理建议"] == "🟥 必须立即清仓（资金卡死）"]
    p1 = prod[prod["处理建议"] == "🟧 尽快处理（低周转）"]
    p2 = prod[prod["处理建议"] == "🟨 观察优化"]
    p3 = prod[prod["处理建议"] == "🟩 可以放量"]
    total_inv = prod["库存金额"].sum()

    render_overview_cards([
        ("必须立即清仓", f"{len(p0):,}", "资金卡死的高优先级项"),
        ("尽快处理", f"{len(p1):,}", "低周转且资金占用偏高"),
        ("观察优化", f"{len(p2):,}", "需要优化测试的产品"),
        ("可以放量", f"{len(p3):,}", "适合继续放量"),
        ("库存总金额", f"¥{total_inv:,.0f}", "全部产品库存资金占用"),
    ])

    # 下载
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        prod.to_excel(writer, sheet_name="领导决策清单", index=False)
        if sku is not None:
            sku.to_excel(writer, sheet_name="SKU明细", index=False)
    st.download_button(
        label="下载领导决策清单 Excel",
        data=output.getvalue(),
        file_name="领导决策清单.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # 按优先级评分降序
    leader = prod.sort_values("优先级评分", ascending=False)
    cols = ["产品ID", "可用库存", "90天内销量", "库存金额", "周转率",
            "风险等级", "销售动作", "优先级评分", "处理建议"]
    show_table(leader, cols)

    # SKU 明细（折叠）
    if sku is not None:
        sku_sorted = sku.sort_values("优先级评分", ascending=False)
        with st.expander(f"SKU 明细 — {len(sku_sorted)} 个", expanded=False):
            cols = [col_sku, "产品ID", "可用库存", "90天内销量", "库存金额",
                    "风险等级", "优先级评分", "处理建议"]
            show_table(sku_sorted, cols)

# ============================================================
# ⑬ 导出 Excel
# ============================================================
def build_full_export(prod_all, sku_all, col_sku, col_amount):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # 新品池
        p_new = prod_all[prod_all["产品分类"] == "🆕 新品池"]
        p_new.to_excel(writer, sheet_name="新品池", index=False)
        # 清仓清单
        p_clear = prod_all[prod_all["销售动作"].isin(["🟥 清仓（停广告+降价）", "🟥 强清仓"])]
        p_clear.to_excel(writer, sheet_name="清仓清单", index=False)
        # 放量清单
        p_scale = prod_all[prod_all["销售动作"].isin(["🟩 扩量", "🟧 放量"])]
        p_scale.to_excel(writer, sheet_name="放量清单", index=False)
        # 风险清单
        p_risk = prod_all[prod_all["风险等级"].isin(["极高风险", "高风险", "中风险"])]
        p_risk.to_excel(writer, sheet_name="风险清单", index=False)
        # 领导决策清单
        prod_all.to_excel(writer, sheet_name="领导决策清单（核心）", index=False)
        # SKU 明细
        if sku_all is not None:
            sku_all.to_excel(writer, sheet_name="SKU明细", index=False)
        # 产品明细
        prod_all.to_excel(writer, sheet_name="产品明细", index=False)
    return output.getvalue()

# ============================================================
# ⑭ 主流程
# ============================================================
def analyze_inventory_file(file):
    df, col_sku, col_amount, col_price, col_create, filtered = load_data(file.getvalue())
    if filtered:
        st.caption(f"已过滤 {filtered} 行无法识别为 LW/DT 产品的数据")
    if not col_price:
        st.caption("未识别到「单价」列，库存金额由总价列推算")
    if not col_create:
        st.caption("未识别到「创建时间」列，新品监控暂不可用")

    results = {}
    for brand in ["LW", "DT"]:
        df_b = df[df["品牌"] == brand].copy()
        results[brand] = (pd.DataFrame(), None) if df_b.empty else aggregate_and_enrich(df_b, col_sku, col_amount)

    prod_lw, sku_lw = results["LW"]
    prod_dt, sku_dt = results["DT"]

    prod_frames = []
    for brand, prod in [("LW", prod_lw), ("DT", prod_dt)]:
        if not prod.empty:
            tagged = prod.copy()
            tagged["品牌"] = brand
            prod_frames.append(tagged)
    prod_all = pd.concat(prod_frames, ignore_index=True) if prod_frames else pd.DataFrame()

    sku_frames = []
    for brand, sku_df in [("LW", sku_lw), ("DT", sku_dt)]:
        if sku_df is not None and not sku_df.empty:
            tagged = sku_df.copy()
            tagged["品牌"] = brand
            sku_frames.append(tagged)
    sku_all = pd.concat(sku_frames, ignore_index=True) if sku_frames else None

    st.session_state["_inv_prod_lw"] = prod_lw
    st.session_state["_inv_prod_dt"] = prod_dt
    st.session_state["_inv_prod_all"] = prod_all
    st.session_state["_inv_sku_lw"] = sku_lw
    st.session_state["_inv_sku_dt"] = sku_dt
    st.session_state["_inv_sku_all"] = sku_all
    st.session_state["_inv_col_sku"] = col_sku
    st.session_state["_inv_col_amount"] = col_amount
    st.session_state["_inv_col_create"] = bool(col_create)
    st.session_state["_inventory_ready"] = True


def render_inventory_upload(key_suffix):
    uploaded = st.file_uploader("上传库存表", type=["xlsx"], key=f"inventory_upload_{key_suffix}")
    if st.session_state.get("_inventory_ready"):
        st.caption("已读取库存表，可重新上传。")
    else:
        st.caption("上传库存表后点击按钮开始分析。")
    if uploaded:
        file_id = f"{uploaded.name}:{getattr(uploaded, 'size', 0)}"
        if st.session_state.get("_inventory_file_id") != file_id:
            st.session_state["_inventory_ready"] = False
            st.session_state["_inventory_file_id"] = file_id
        if st.button("开始分析库存数据", type="primary", use_container_width=True, key=f"analyze_inventory_{key_suffix}"):
            with st.spinner("正在分析库存数据..."):
                analyze_inventory_file(uploaded)
            st.success("库存分析完成")


def filter_brand_df(df, brand):
    if df is None or df.empty or brand == "ALL":
        return df
    return df[df["品牌"] == brand].copy() if "品牌" in df.columns else df


def mature_inventory(df):
    if df is None or df.empty or "产品分类" not in df.columns:
        return df
    return df[df["产品分类"] != "🆕 新品池"].copy()


def render_stock_health_tab():
    st.header("库存健康")
    render_inventory_upload("health")
    if not st.session_state.get("_inventory_ready"):
        st.info("请先上传库存表并点击开始分析。")
        return

    prod_all = mature_inventory(st.session_state.get("_inv_prod_all", pd.DataFrame()))
    sku_all = mature_inventory(st.session_state.get("_inv_sku_all"))
    col_sku = st.session_state.get("_inv_col_sku")
    col_amount = st.session_state.get("_inv_col_amount")

    render_overview_cards([
        ("成熟产品数", f"{len(prod_all):,}", "已排除 90 天内新品"),
        ("高风险产品", f"{len(prod_all[prod_all['风险等级'].isin(['极高风险', '高风险'])]):,}" if not prod_all.empty else "0", "极高风险和高风险产品"),
        ("库存总金额", f"¥{prod_all['库存金额'].sum():,.0f}" if not prod_all.empty else "¥0", "成熟库存资金占用"),
        ("90天销量", f"{prod_all['90天内销量'].sum():,}" if not prod_all.empty else "0", "成熟库存近 90 天销量"),
    ])

    brand_tabs = st.tabs(["全部", "Hunthouse(LW)", "D1"])
    for tab, brand, label in zip(brand_tabs, ["ALL", "LW", "DT"], ["全部", "LW", "DT"]):
        with tab:
            p = filter_brand_df(prod_all, brand)
            s = filter_brand_df(sku_all, brand)
            if p is None or p.empty:
                st.info("当前品牌暂无成熟库存数据。")
                continue
            render_analysis(p, s, col_sku, col_amount, label)
            with st.expander("清仓建议", expanded=False):
                render_clearance(p, s, col_sku, col_amount)
            with st.expander("放量机会", expanded=False):
                render_scaleup(p, s, col_sku, col_amount)
            with st.expander("库存风险", expanded=False):
                render_risk(p, s, col_sku, col_amount)
            with st.expander("领导决策清单", expanded=False):
                render_leader(p, s, col_sku, col_amount)

    export_data = build_full_export(prod_all, sku_all, col_sku, col_amount)
    st.download_button(
        label="下载库存健康 Excel",
        data=export_data,
        file_name="库存健康_成熟库存.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def render_new_monitor_tab():
    st.header("新品监控")
    render_inventory_upload("new")
    if not st.session_state.get("_inventory_ready"):
        st.info("请先上传库存表并点击开始分析。若已在库存健康上传，可直接复用。")
        return

    prod_all = st.session_state.get("_inv_prod_all", pd.DataFrame())
    sku_all = st.session_state.get("_inv_sku_all")
    brand_choice = st.selectbox(
        "品牌",
        options=["ALL", "LW", "DT"],
        format_func=lambda x: "全部" if x == "ALL" else display_brand(x),
        index=0,
    )
    p = filter_brand_df(prod_all, brand_choice)
    s = filter_brand_df(sku_all, brand_choice)
    render_new_products(
        p,
        s,
        st.session_state.get("_inv_col_sku"),
        st.session_state.get("_inv_col_amount"),
        st.session_state.get("_inv_col_create"),
    )


t1, t2, t3, t4 = st.tabs(["库存健康", "新品监控", "意法海托", "组合分析"])

with t1:
    render_stock_health_tab()
with t2:
    render_new_monitor_tab()
with t3:
    render_sea_freight_tab()
with t4:
    render_combo_analysis_tab()
