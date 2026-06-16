import streamlit as st
import pandas as pd
import re
import io
import plotly.express as px
from io import BytesIO

# ============================================================
# PAGE CONFIG & STYLE
# ============================================================
st.set_page_config(page_title="库存决策系统 V5", layout="wide")
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
st.title("库存决策系统 V5")

# ============================================================
# CONSTANTS
# ============================================================
LEVEL_ORDER     = ["热销", "主销", "弱动销", "滞销", "死库存"]
LEVEL_THRESHOLD = {
    "热销":  "热销（90天销量 ≥ 300）",
    "主销":  "主销（90天销量 50~299）",
    "弱动销": "弱动销（90天销量 30~49）",
    "滞销":  "滞销（90天销量 1~29）",
    "死库存": "死库存（90天销量 = 0）",
}
COLOR_MAP = {
    "热销":   "#10b981",
    "主销":   "#6366f1",
    "弱动销": "#f59e0b",
    "滞销":   "#ef4444",
    "死库存":  "#94a3b8",
}
RISK_ORDER = ["极高风险", "高风险", "中风险", "低风险", "优质"]

# ============================================================
# ① 产品识别
# ============================================================
def extract_product(name):
    name = str(name).strip()
    m = re.search(r"\b(LW\d{3,4}|DT\d{3,5})\b", name)
    return m.group(1) if m else None

# ============================================================
# ② 动销等级
# ============================================================
def compute_sales_level(x):
    if x >= 300: return "热销"
    elif x >= 50: return "主销"
    elif x >= 30: return "弱动销"
    elif x >= 1:  return "滞销"
    else:         return "死库存"

# ============================================================
# ③ V5 决策引擎
# ============================================================
def compute_sales_action(sales_90d):
    if sales_90d >= 300:
        return "🟩 扩量保护：优先补货，保护排名，可扩颜色/尺寸"
    elif sales_90d >= 50:
        return "🟧 推广放量：维持库存，适合小幅加广告或活动曝光"
    elif sales_90d >= 30:
        return "🟨 优化测试：检查主图/标题/价格，低预算测试，暂不补货"
    elif sales_90d >= 1:
        return "🟥 强清仓：降价20%-40%+进入清仓活动+可捆绑热销款"
    else:
        return "🟥 立即清仓：停广告+降价30%-50%+打包出清"

def compute_risk_level(sales_90d, stock):
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

def compute_clear_score(sales_90d, amt):
    if sales_90d == 0:
        return 100000 + max(amt, 0)
    return round(amt / (sales_90d + 1), 2)

def compute_scale_signal(sales_90d):
    if sales_90d >= 300:
        return "强放量"
    elif sales_90d >= 50:
        return "可放量"
    elif sales_90d >= 30:
        return "暂不放量，先优化"
    else:
        return "不建议放量"

def compute_health_score(sales_90d, amount_val):
    if sales_90d >= 300:
        base = 92
    elif sales_90d >= 50:
        base = 80
    elif sales_90d >= 30:
        base = 68
    elif sales_90d >= 1:
        base = 50
    else:
        base = 30
    if sales_90d > 0 and amount_val > 0:
        ratio = amount_val / (sales_90d + 1)
        if ratio > 100:
            base -= 12
        elif ratio > 50:
            base -= 8
        elif ratio > 10:
            base -= 4
        elif ratio < 1:
            base += 5
    return max(0, min(100, base))

# ============================================================
# ③-B 待处理清单决策引擎
# ============================================================
def compute_leader_priority(row, col_amount):
    sales = row["90天内销量"]
    stock = row["可用库存"]
    amt = row[col_amount] if col_amount and col_amount in row.index else 0
    level = row["动销等级"]
    if level == "死库存" and amt >= 3000:
        return "P0"
    if sales < 30 and stock >= 500:
        return "P0"
    if sales < 30 and amt >= 3000:
        return "P0"
    if sales < 30 and stock >= 100:
        return "P1"
    if level == "弱动销" and amt >= 3000:
        return "P1"
    return "P2"

def compute_leader_action(row, priority, col_amount):
    level = row["动销等级"]
    if priority == "P0":
        return "立即清仓" if level == "死库存" else "降价促销"
    elif priority == "P1":
        return "停止补货" if level == "弱动销" else "降价促销"
    else:
        return "观察优化" if level == "弱动销" else "组合捆绑"

def compute_leader_reason(row, priority, col_amount):
    level = row["动销等级"]
    sales = row["90天内销量"]
    stock = row["可用库存"]
    amt = row[col_amount] if col_amount and col_amount in row.index else 0
    parts = []
    if level == "死库存":
        parts.append("零销量")
    elif level == "滞销":
        parts.append("销量极低")
    elif level == "弱动销":
        parts.append("动销偏弱")
    if stock >= 500:
        parts.append("库存较高")
    elif stock >= 100:
        parts.append("有一定库存积压")
    if amt >= 3000:
        parts.append("资金占用较高")
    if not parts:
        parts.append("需持续观察")
    suffix = "，建议进入清仓评估" if priority in ("P0", "P1") else ""
    return "、".join(parts) + suffix

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
    col_amount = [c for c in df.columns if "总价" in c or "金额" in c or "销售额" in c]
    col_amount = col_amount[0] if col_amount else None
    df["产品ID"] = df["商品名称"].apply(extract_product)
    before = len(df)
    df = df[df["产品ID"].notnull()].copy()
    filtered = before - len(df)
    df["品牌"] = df["产品ID"].apply(lambda x: x[:2])
    return df, col_sku, col_amount, filtered

# ============================================================
# ⑤ 聚合 + 决策字段
# ============================================================
def aggregate_and_enrich(df_brand, col_sku, col_amount):
    """产品层聚合 + SKU 层聚合，均附加 V5 决策字段"""
    agg_dict = {"可用库存": "sum", "90天内销量": "sum"}
    score_col = col_amount if col_amount else "可用库存"
    if col_amount:
        agg_dict[col_amount] = "sum"

    # 产品层
    prod = df_brand.groupby("产品ID").agg(agg_dict).reset_index()
    prod["动销等级"] = prod["90天内销量"].apply(compute_sales_level)
    prod["销售动作"] = prod["90天内销量"].apply(compute_sales_action)
    prod["风险等级"] = prod.apply(lambda r: compute_risk_level(r["90天内销量"], r["可用库存"]), axis=1)
    prod["清仓评分"] = prod.apply(lambda r: compute_clear_score(r["90天内销量"], r[score_col]), axis=1)
    prod["放量信号"] = prod["90天内销量"].apply(compute_scale_signal)
    prod["产品健康评分"] = prod.apply(lambda r: compute_health_score(r["90天内销量"], r[score_col]), axis=1)

    # SKU 层
    sku = None
    if col_sku:
        sku = df_brand.groupby(col_sku).agg(agg_dict).reset_index()
        sku["产品ID"] = sku[col_sku].map(
            df_brand.drop_duplicates(col_sku).set_index(col_sku)["产品ID"]
        )
        sku["动销等级"] = sku["90天内销量"].apply(compute_sales_level)
        sku["销售动作"] = sku["90天内销量"].apply(compute_sales_action)
        sku["风险等级"] = sku.apply(lambda r: compute_risk_level(r["90天内销量"], r["可用库存"]), axis=1)
        sku["清仓评分"] = sku.apply(lambda r: compute_clear_score(r["90天内销量"], r[score_col]), axis=1)
        sku["放量信号"] = sku["90天内销量"].apply(compute_scale_signal)

    return prod, sku, score_col

# ============================================================
# ⑥ 图表
# ============================================================
def make_pie(labels, values, title, color_map):
    df_pie = pd.DataFrame({"等级": labels, "数量": values})
    df_pie = df_pie[df_pie["数量"] > 0]
    if df_pie.empty:
        return None
    fig = px.pie(
        df_pie, names="等级", values="数量", color="等级",
        color_discrete_map=color_map, category_orders={"等级": LEVEL_ORDER}, hole=0.4,
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

# ============================================================
# ⑦ 库存分析渲染（原有功能）
# ============================================================
def render_analysis(prod, sku, col_sku, col_amount):
    """产品 + SKU 饼图 + 折叠表格"""
    st.subheader("产品")
    c1, c2 = st.columns(2)
    with c1:
        prod_counts = [len(prod[prod["动销等级"] == lv]) for lv in LEVEL_ORDER]
        fig1 = make_pie(LEVEL_ORDER, prod_counts, "产品数量占比（按动销等级）", COLOR_MAP)
        if fig1: st.plotly_chart(fig1, use_container_width=True)
        else: st.info("无数据")
    with c2:
        if col_amount:
            prod_amounts = [prod[prod["动销等级"] == lv][col_amount].sum() for lv in LEVEL_ORDER]
            fig2 = make_pie(LEVEL_ORDER, prod_amounts, f"产品金额占比（{col_amount}）", COLOR_MAP)
            if fig2: st.plotly_chart(fig2, use_container_width=True)
            else: st.info("无数据")
        else:
            st.info("未识别到金额列，无法展示金额饼图")
    for lv in LEVEL_ORDER:
        sub = prod[prod["动销等级"] == lv]
        if not sub.empty:
            label = LEVEL_THRESHOLD[lv]
            with st.expander(f"{label} — {len(sub)} 个产品", expanded=False):
                cols = ["产品ID", "可用库存", "90天内销量", "产品健康评分", "销售动作", "风险等级", "清仓评分", "放量信号"]
                if col_amount: cols.insert(3, col_amount)
                st.dataframe(
                    sub[[c for c in cols if c in sub.columns]].sort_values("90天内销量", ascending=False),
                    use_container_width=True, hide_index=True,
                )

    st.divider()
    st.subheader("SKU")
    if sku is None:
        st.info("未识别到 SKU 列")
        return
    c3, c4 = st.columns(2)
    with c3:
        sku_counts = [len(sku[sku["动销等级"] == lv]) for lv in LEVEL_ORDER]
        fig3 = make_pie(LEVEL_ORDER, sku_counts, "SKU 数量占比（按动销等级）", COLOR_MAP)
        if fig3: st.plotly_chart(fig3, use_container_width=True)
        else: st.info("无数据")
    with c4:
        if col_amount:
            sku_amounts = [sku[sku["动销等级"] == lv][col_amount].sum() for lv in LEVEL_ORDER]
            fig4 = make_pie(LEVEL_ORDER, sku_amounts, f"SKU 金额占比（{col_amount}）", COLOR_MAP)
            if fig4: st.plotly_chart(fig4, use_container_width=True)
            else: st.info("无数据")
        else:
            st.info("未识别到金额列，无法展示金额饼图")
    for lv in LEVEL_ORDER:
        sub = sku[sku["动销等级"] == lv]
        if not sub.empty:
            label = LEVEL_THRESHOLD[lv]
            with st.expander(f"{label} — {len(sub)} 个 SKU", expanded=False):
                cols = [col_sku, "产品ID", "可用库存", "90天内销量", "销售动作", "风险等级", "清仓评分", "放量信号"]
                if col_amount: cols.insert(4, col_amount)
                st.dataframe(
                    sub[[c for c in cols if c in sub.columns]].sort_values("90天内销量", ascending=False),
                    use_container_width=True, hide_index=True,
                )

# ============================================================
# ⑧ 决策面板渲染（V5 新增）
# ============================================================
def render_decision_panel(prod, sku, col_sku, col_amount):
    """V5 决策面板：销售动作总览 + 清仓 + 优化 + 放量 + 风险"""
    st.subheader("决策面板")

    # ---- 8.1 销售动作总览 ----
    st.markdown("#### 销售动作总览")
    action_order = [
        "🟩 扩量保护：优先补货，保护排名，可扩颜色/尺寸",
        "🟧 推广放量：维持库存，适合小幅加广告或活动曝光",
        "🟨 优化测试：检查主图/标题/价格，低预算测试，暂不补货",
        "🟥 强清仓：降价20%-40%+进入清仓活动+可捆绑热销款",
        "🟥 立即清仓：停广告+降价30%-50%+打包出清",
    ]
    overview_rows = []
    for action in action_order:
        p_sub = prod[prod["销售动作"] == action]
        s_sub = sku[sku["销售动作"] == action] if sku is not None else pd.DataFrame()
        row = {
            "动作类型": action,
            "产品数量": len(p_sub),
            "SKU数量": len(s_sub),
            "90天销量合计": p_sub["90天内销量"].sum(),
        }
        if col_amount:
            row["库存金额合计"] = p_sub[col_amount].sum()
        overview_rows.append(row)
    df_overview = pd.DataFrame(overview_rows)
    st.dataframe(df_overview, use_container_width=True, hide_index=True)

    # ---- 8.2 清仓优先级 ----
    with st.expander("🗑️ 清仓优先级", expanded=False):
        clearance_actions = [
            "🟥 立即清仓：停广告+降价30%-50%+打包出清",
            "🟥 强清仓：降价20%-40%+进入清仓活动+可捆绑热销款",
        ]
        clearance_risks = ["极高风险", "高风险"]
        p_clear = prod[(prod["销售动作"].isin(clearance_actions)) | (prod["风险等级"].isin(clearance_risks))]
        p_clear = p_clear.sort_values("清仓评分", ascending=False)

        st.markdown(f"**清仓产品清单：{len(p_clear)} 个**")
        if not p_clear.empty:
            cols = ["产品ID", "可用库存", "90天内销量", "动销等级", "风险等级", "清仓评分", "销售动作"]
            if col_amount: cols.insert(2, col_amount)
            st.dataframe(p_clear[[c for c in cols if c in p_clear.columns]],
                         use_container_width=True, hide_index=True)

        if sku is not None:
            s_clear = sku[(sku["销售动作"].isin(clearance_actions)) | (sku["风险等级"].isin(clearance_risks))]
            s_clear = s_clear.sort_values("清仓评分", ascending=False)
            st.markdown(f"**清仓 SKU 清单：{len(s_clear)} 个**")
            if not s_clear.empty:
                cols = [col_sku, "产品ID", "可用库存", "90天内销量", "动销等级", "风险等级", "清仓评分", "销售动作"]
                if col_amount: cols.insert(3, col_amount)
                st.dataframe(s_clear[[c for c in cols if c in s_clear.columns]],
                             use_container_width=True, hide_index=True)

    # ---- 8.3 优化测试清单 ----
    with st.expander("🔧 优化测试清单", expanded=False):
        opt_action = "🟨 优化测试：检查主图/标题/价格，低预算测试，暂不补货"
        p_opt = prod[prod["销售动作"] == opt_action].sort_values("清仓评分", ascending=False)
        st.markdown(f"**优化测试产品：{len(p_opt)} 个**")
        if not p_opt.empty:
            cols = ["产品ID", "可用库存", "90天内销量", "动销等级", "清仓评分", "放量信号"]
            if col_amount: cols.insert(2, col_amount)
            st.dataframe(p_opt[[c for c in cols if c in p_opt.columns]],
                         use_container_width=True, hide_index=True)
        if sku is not None:
            s_opt = sku[sku["销售动作"] == opt_action].sort_values("清仓评分", ascending=False)
            st.markdown(f"**优化测试 SKU：{len(s_opt)} 个**")
            if not s_opt.empty:
                cols = [col_sku, "产品ID", "可用库存", "90天内销量", "动销等级", "清仓评分", "放量信号"]
                if col_amount: cols.insert(3, col_amount)
                st.dataframe(s_opt[[c for c in cols if c in s_opt.columns]],
                             use_container_width=True, hide_index=True)

    # ---- 8.4 放量清单 ----
    with st.expander("📈 放量清单", expanded=False):
        scale_actions = [
            "🟩 扩量保护：优先补货，保护排名，可扩颜色/尺寸",
            "🟧 推广放量：维持库存，适合小幅加广告或活动曝光",
        ]
        p_scale = prod[prod["销售动作"].isin(scale_actions)].sort_values("90天内销量", ascending=False)
        st.markdown(f"**放量产品清单：{len(p_scale)} 个**")
        if not p_scale.empty:
            cols = ["产品ID", "可用库存", "90天内销量", "动销等级", "放量信号", "产品健康评分"]
            if col_amount: cols.insert(2, col_amount)
            st.dataframe(p_scale[[c for c in cols if c in p_scale.columns]],
                         use_container_width=True, hide_index=True)
        if sku is not None:
            s_scale = sku[sku["销售动作"].isin(scale_actions)].sort_values("90天内销量", ascending=False)
            st.markdown(f"**放量 SKU 清单：{len(s_scale)} 个**")
            if not s_scale.empty:
                cols = [col_sku, "产品ID", "可用库存", "90天内销量", "动销等级", "放量信号"]
                if col_amount: cols.insert(3, col_amount)
                st.dataframe(s_scale[[c for c in cols if c in s_scale.columns]],
                             use_container_width=True, hide_index=True)

    # ---- 8.5 风险产品清单 ----
    with st.expander("⚠️ 风险产品清单", expanded=False):
        p_risk = prod[prod["风险等级"].isin(["极高风险", "高风险", "中风险"])]
        p_risk = p_risk.sort_values(["风险等级", "清仓评分"], ascending=[True, False])
        st.markdown(f"**风险产品：{len(p_risk)} 个**")
        if not p_risk.empty:
            cols = ["产品ID", "可用库存", "90天内销量", "动销等级", "风险等级", "清仓评分", "产品健康评分"]
            if col_amount: cols.insert(2, col_amount)
            st.dataframe(p_risk[[c for c in cols if c in p_risk.columns]],
                         use_container_width=True, hide_index=True)

# ============================================================
# ⑨ 导出 Excel
# ============================================================
def build_export(prod_lw, prod_dt, sku_lw, sku_dt, col_sku, col_amount):
    clearance_actions = [
        "🟥 立即清仓：停广告+降价30%-50%+打包出清",
        "🟥 强清仓：降价20%-40%+进入清仓活动+可捆绑热销款",
    ]
    clearance_risks = ["极高风险", "高风险"]
    scale_actions = [
        "🟩 扩量保护：优先补货，保护排名，可扩颜色/尺寸",
        "🟧 推广放量：维持库存，适合小幅加广告或活动曝光",
    ]

    def tag_brand(prod_df, sku_df, brand):
        p = prod_df.copy(); p["品牌"] = brand
        if sku_df is not None:
            s = sku_df.copy(); s["品牌"] = brand
        else:
            s = pd.DataFrame()
        return p, s

    p_lw, s_lw = tag_brand(prod_lw, sku_lw, "LW")
    p_dt, s_dt = tag_brand(prod_dt, sku_dt, "DT")
    all_prod = pd.concat([p_lw, p_dt], ignore_index=True)
    all_sku = pd.concat([s_lw, s_dt], ignore_index=True) if sku_lw is not None and sku_dt is not None else pd.DataFrame()

    p_clear = all_prod[(all_prod["销售动作"].isin(clearance_actions)) | (all_prod["风险等级"].isin(clearance_risks))]
    s_clear = all_sku[(all_sku["销售动作"].isin(clearance_actions)) | (all_sku["风险等级"].isin(clearance_risks))]
    p_scale = all_prod[all_prod["销售动作"].isin(scale_actions)]
    s_scale = all_sku[all_sku["销售动作"].isin(scale_actions)]

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        all_prod.to_excel(writer, sheet_name="产品决策表", index=False)
        if not all_sku.empty:
            all_sku.to_excel(writer, sheet_name="SKU决策表", index=False)
        p_clear.to_excel(writer, sheet_name="清仓产品清单", index=False)
        if not s_clear.empty:
            s_clear.to_excel(writer, sheet_name="清仓SKU清单", index=False)
        p_scale.to_excel(writer, sheet_name="放量产品清单", index=False)
        if not s_scale.empty:
            s_scale.to_excel(writer, sheet_name="放量SKU清单", index=False)
    return output.getvalue()

# ============================================================
# ⑨-B 领导版导出
# ============================================================
def build_leader_export(leader_df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        leader_df.to_excel(writer, sheet_name="待处理清单", index=False)
    return output.getvalue()

# ============================================================
# ⑨-C 待处理清单渲染
# ============================================================
def render_leader_tab(prod_lw, prod_dt, col_amount):
    """合并 LW+DT 低销量产品，生成领导版处理清单"""
    p_lw = prod_lw.copy(); p_lw["品牌"] = "LW"
    p_dt = prod_dt.copy(); p_dt["品牌"] = "DT"
    all_prod = pd.concat([p_lw, p_dt], ignore_index=True)

    low_mask = all_prod["90天内销量"] < 50
    leader = all_prod[low_mask].copy()
    if leader.empty:
        st.info("当前无需处理的产品")
        return

    leader["处理优先级"] = leader.apply(lambda r: compute_leader_priority(r, col_amount), axis=1)
    leader["建议动作"] = leader.apply(lambda r: compute_leader_action(r, r["处理优先级"], col_amount), axis=1)
    leader["处理原因"] = leader.apply(lambda r: compute_leader_reason(r, r["处理优先级"], col_amount), axis=1)

    # 排序：P0 → P1 → P2，同优先级按总价降序
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    leader["_sort"] = leader["处理优先级"].map(priority_order)
    sort_col = col_amount if col_amount else "可用库存"
    leader = leader.sort_values(["_sort", sort_col], ascending=[True, False])
    leader = leader.drop(columns=["_sort"])

    # ---- 统计卡片 ----
    p0 = leader[leader["处理优先级"] == "P0"]
    p1 = leader[leader["处理优先级"] == "P1"]
    p2 = leader[leader["处理优先级"] == "P2"]
    total_amt = leader[col_amount].sum() if col_amount else 0

    c0, c1, c2, c3 = st.columns(4)
    c0.metric("🔴 P0 必须立刻处理", len(p0))
    c1.metric("🟠 P1 本月优先处理", len(p1))
    c2.metric("🟡 P2 观察处理", len(p2))
    if col_amount:
        c3.metric("💰 待处理库存金额", f"¥{total_amt:,.0f}")
    else:
        c3.metric("📦 待处理库存合计", f"{leader['可用库存'].sum():,}")

    # ---- 下载按钮 ----
    excel_data = build_leader_export(leader)
    st.download_button(
        label="下载待处理清单 Excel",
        data=excel_data,
        file_name="待处理清单.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ---- 表格 ----
    display_cols = ["产品ID", "品牌", "可用库存", "90天内销量", "产品健康评分", "处理优先级", "建议动作", "处理原因"]
    if col_amount:
        display_cols.insert(3, col_amount)
    st.dataframe(
        leader[[c for c in display_cols if c in leader.columns]],
        use_container_width=True, hide_index=True,
    )

# ============================================================
# ⑩ 主流程
# ============================================================
file = st.file_uploader("上传 Excel 文件", type=["xlsx"])

if file:
    df, col_sku, col_amount, filtered = load_data(file.getvalue())
    if filtered:
        st.caption(f"已过滤 {filtered} 行无法识别为 LW/DT 产品的数据")

    # ---- 按品牌聚合 + 决策字段 ----
    results = {}
    for brand in ["LW", "DT"]:
        df_brand = df[df["品牌"] == brand].copy()
        if df_brand.empty:
            results[brand] = (pd.DataFrame(), None, col_amount)
        else:
            results[brand] = aggregate_and_enrich(df_brand, col_sku, col_amount)

    prod_lw, sku_lw, _ = results["LW"]
    prod_dt, sku_dt, _ = results["DT"]

    # ---- 导出按钮 ----
    excel_data = build_export(prod_lw, prod_dt, sku_lw, sku_dt, col_sku, col_amount)
    st.download_button(
        label="下载 V5 决策结果 Excel",
        data=excel_data,
        file_name="V5_库存决策结果.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ---- 顶层 Tab ----
    tab_lw, tab_dt, tab_leader = st.tabs(["LW", "DT", "待处理清单"])
    for tab, brand, prod, sku in [
        (tab_lw, "LW", prod_lw, sku_lw),
        (tab_dt, "DT", prod_dt, sku_dt),
    ]:
        with tab:
            st.header(brand)
            if prod.empty:
                st.info("无该品牌产品")
                continue
            sub_tab1, sub_tab2 = st.tabs(["库存分析", "决策面板"])
            with sub_tab1:
                render_analysis(prod, sku, col_sku, col_amount)
            with sub_tab2:
                if sku is not None:
                    render_decision_panel(prod, sku, col_sku, col_amount)
                else:
                    st.info("未识别到 SKU 列，决策面板部分功能不可用")
    with tab_leader:
        st.header("待处理清单")
        render_leader_tab(prod_lw, prod_dt, col_amount)
else:
    st.info("📂 请上传一个 Excel 文件开始分析")
    st.stop()
