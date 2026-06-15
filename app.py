import streamlit as st
import pandas as pd
import re
import io
import plotly.express as px
st.set_page_config(page_title="库存决策系统", layout="wide")
st.markdown("""
<style>
  .stApp { background: #f8fafc; }
  header[data-testid="stHeader"] { background: transparent !important; }
  .stTabs [data-baseweb="tab"] { font-weight: 500; border-radius: 8px 8px 0 0; padding: 8px 16px; }
  .stExpander { border-radius: 10px; border: 1px solid #e2e8f0; box-shadow: none; }
  div[data-testid="stMetric"] { background: white; border-radius: 10px; padding: 12px; border: 1px solid #f1f5f9; }
  .stPlotlyChart { background: white; border-radius: 12px; padding: 12px; border: 1px solid #f1f5f9; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
</style>
""", unsafe_allow_html=True)
st.title("库存决策系统")
file = st.file_uploader("上传 Excel 文件", type=["xlsx"])
# =========================
# ① 产品识别（只保留 LW / DT）
# =========================
def extract_product(name):
    name = str(name).strip()
    m = re.search(r"\b(LW\d{3,4}|DT\d{3,5})\b", name)
    if m:
        return m.group(1)
    return None
# =========================
# ② 动销等级（按 90天销量 判定）
# =========================
def level(x):
    if x >= 300:  return "热销"
    elif x >= 50: return "主销"
    elif x >= 30: return "弱动销"
    elif x >= 1:  return "滞销"
    else:         return "死库存"
# =========================
# ③ 饼状图颜色映射
# =========================
LEVEL_ORDER      = ["热销", "主销", "弱动销", "滞销", "死库存"]
LEVEL_THRESHOLD  = {
    "热销":   "热销（90天销量 ≥ 300）",
    "主销":   "主销（90天销量 50~299）",
    "弱动销": "弱动销（90天销量 30~49）",
    "滞销":   "滞销（90天销量 1~29）",
    "死库存":  "死库存（90天销量 = 0）",
}
COLOR_MAP = {
    "热销":   "#10b981",
    "主销":   "#6366f1",
    "弱动销": "#f59e0b",
    "滞销":   "#ef4444",
    "死库存":  "#94a3b8",
}
# =========================
# 缓存预处理
# =========================
@st.cache_data
def load_data(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes))
    if "商品名称" not in df.columns:
        st.error("Excel 文件中缺少「商品名称」列，无法识别产品。")
        st.stop()
    col_sku = [c for c in df.columns if c.upper() == "SKU"]
    col_sku = col_sku[0] if col_sku else None
    col_amount = [c for c in df.columns if "总价" in c or "金额" in c or "销售额" in c]
    col_amount = col_amount[0] if col_amount else None
    df["产品ID"] = df["商品名称"].apply(extract_product)
    before = len(df)
    df = df[df["产品ID"].notnull()].copy()
    filtered = before - len(df)
    df["品牌"] = df["产品ID"].apply(lambda x: x[:2])
    return df, col_sku, col_amount, filtered
# =========================
# 主流程
# =========================
if file:
    df, col_sku, col_amount, filtered = load_data(file.getvalue())
    if filtered:
        st.caption(f"已过滤 {filtered} 行无法识别为 LW/DT 产品的数据")
    df_lw = df[df["品牌"] == "LW"].copy()
    df_dt = df[df["品牌"] == "DT"].copy()
    # =========================
    # 图表工具函数
    # =========================
    def make_pie(labels, values, title, color_map):
        df_pie = pd.DataFrame({"等级": labels, "数量": values})
        df_pie = df_pie[df_pie["数量"] > 0]
        if df_pie.empty:
            return None
        fig = px.pie(
            df_pie,
            names="等级",
            values="数量",
            color="等级",
            color_discrete_map=color_map,
            category_orders={"等级": LEVEL_ORDER},
            hole=0.4,
        )
        fig.update_traces(
            textposition="inside",
            textinfo="percent",
            textfont_size=12,
            textfont_color="#475569",
            marker=dict(line=dict(color="white", width=2)),
            hovertemplate="<b>%{label}</b><br>%{value} 个<br>%{percent}<extra></extra>",
        )
        fig.update_layout(
            title=dict(text=title, font=dict(size=13, color="#64748b")),
            showlegend=False,
            margin=dict(t=40, b=10, l=10, r=10),
            height=240,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        return fig
    def render_brand(df_brand, brand):
        st.header(brand)
        if df_brand.empty:
            st.info("无该品牌产品")
            return
        df_b = df_brand.copy()
        # ---- 聚合字段 ----
        agg_dict = {"可用库存": "sum", "90天内销量": "sum"}
        if col_amount:
            agg_dict[col_amount] = "sum"
        # ---- 产品层聚合 ----
        prod = df_b.groupby("产品ID").agg(agg_dict).reset_index()
        prod["动销等级"] = prod["90天内销量"].apply(level)
        # ---- SKU 层聚合 ----
        if col_sku:
            sku = df_b.groupby(col_sku).agg(agg_dict).reset_index()
            sku["产品ID"] = sku[col_sku].map(
                df_b.drop_duplicates(col_sku).set_index(col_sku)["产品ID"]
            )
            sku["动销等级"] = sku["90天内销量"].apply(level)
        else:
            sku = None
        # ======== 产品层 ========
        st.subheader("产品")
        # 饼状图：数量占比 + 金额占比
        c1, c2 = st.columns(2)
        with c1:
            prod_counts = [len(prod[prod["动销等级"] == lv]) for lv in LEVEL_ORDER]
            fig1 = make_pie(LEVEL_ORDER, prod_counts, "产品数量占比（按动销等级）", COLOR_MAP)
            if fig1:
                st.plotly_chart(fig1, use_container_width=True)
            else:
                st.info("无数据")
        with c2:
            if col_amount:
                prod_amounts = [prod[prod["动销等级"] == lv][col_amount].sum() for lv in LEVEL_ORDER]
                fig2 = make_pie(LEVEL_ORDER, prod_amounts, f"产品金额占比（{col_amount}）", COLOR_MAP)
                if fig2:
                    st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.info("无数据")
            else:
                st.info("未识别到金额列，无法展示金额饼图")
        # 产品表格（默认折叠）
        for lv in LEVEL_ORDER:
            sub = prod[prod["动销等级"] == lv]
            if not sub.empty:
                label = LEVEL_THRESHOLD[lv]
                with st.expander(f"{label} — {len(sub)} 个产品", expanded=False):
                    st.dataframe(
                        sub.sort_values("90天内销量", ascending=False),
                        use_container_width=True,
                        hide_index=True
                    )
        st.divider()
        # ======== SKU 层 ========
        st.subheader("SKU")
        if sku is None:
            st.info("未识别到 SKU 列")
            return
        # 饼状图：数量占比 + 金额占比
        c3, c4 = st.columns(2)
        with c3:
            sku_counts = [len(sku[sku["动销等级"] == lv]) for lv in LEVEL_ORDER]
            fig3 = make_pie(LEVEL_ORDER, sku_counts, "SKU 数量占比（按动销等级）", COLOR_MAP)
            if fig3:
                st.plotly_chart(fig3, use_container_width=True)
            else:
                st.info("无数据")
        with c4:
            if col_amount:
                sku_amounts = [sku[sku["动销等级"] == lv][col_amount].sum() for lv in LEVEL_ORDER]
                fig4 = make_pie(LEVEL_ORDER, sku_amounts, f"SKU 金额占比（{col_amount}）", COLOR_MAP)
                if fig4:
                    st.plotly_chart(fig4, use_container_width=True)
                else:
                    st.info("无数据")
            else:
                st.info("未识别到金额列，无法展示金额饼图")
        # SKU 表格（默认折叠）
        for lv in LEVEL_ORDER:
            sub = sku[sku["动销等级"] == lv]
            if not sub.empty:
                label = LEVEL_THRESHOLD[lv]
                with st.expander(f"{label} — {len(sub)} 个 SKU", expanded=False):
                    st.dataframe(
                        sub.sort_values("90天内销量", ascending=False),
                        use_container_width=True,
                        hide_index=True
                    )
    # ======== 两个 Tab ========
    tab_lw, tab_dt = st.tabs(["LW", "DT"])
    with tab_lw:
        render_brand(df_lw, "LW")
    with tab_dt:
        render_brand(df_dt, "DT")
else:
    st.info("📂 请上传一个 Excel 文件开始分析")
    st.stop()
