# 文件名: oil_prices_app_mobile_v3.py
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import os
import io
from datetime import datetime

# ========== 配置 ==========
API_KEY = "GOqcqu0QJ0yQvzYCCYB72exYzlEun88nwKAqXMQP"
SERIES = {
    "布伦特原油": "PET.RBRTE.D",
    "WTI原油": "PET.RWTC.D"
}
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)


# ========== 小工具 / 数据获取 ==========
def _safe_float(s):
    try:
        return float(s)
    except Exception:
        return None


@st.cache_data(ttl=60)
def fetch_realtime_prices():
    endpoints = {
        "布伦特原油期货": "http://hq.sinajs.cn/list=hf_OIL",
        "WTI原油期货": "http://hq.sinajs.cn/list=hf_CL",
    }
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    out = {}
    for name, url in endpoints.items():
        price, ts = None, None
        try:
            r = requests.get(url, headers=headers, timeout=6)
            r.encoding = "gbk"
            if "=" in r.text:
                payload = r.text.split("=", 1)[1].strip().strip('";')
                parts = payload.split(",")
                if len(parts) >= 2 and _safe_float(parts[1]) is not None:
                    price = round(float(parts[1]), 2)
                else:
                    for p in parts[:6]:
                        val = _safe_float(p)
                        if val is not None:
                            price = round(val, 2)
                            break
                if parts and ":" in parts[-1]:
                    ts = parts[-1]
        except Exception:
            pass
        out[name] = {"price": price, "time": ts}
    return out


@st.cache_data(ttl=3600)
def fetch_eia_data_v2(series_id, api_key, start=None, end=None):
    url = f"https://api.eia.gov/v2/seriesid/{series_id}"
    params = {"api_key": api_key}
    if start: params["start"] = start
    if end: params["end"] = end
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()
    if "response" in data and "data" in data["response"]:
        records = data["response"]["data"]
        df = pd.DataFrame(records)[["period", "value"]].rename(columns={"period": "日期", "value": "价格"})
        df["日期"] = pd.to_datetime(df["日期"])
        return df.sort_values("日期")
    else:
        return pd.DataFrame(columns=["日期", "价格"])


def load_or_update_data(series_id, name):
    csv_path = os.path.join(DATA_DIR, f"{name}.csv")
    if os.path.exists(csv_path):
        df_local = pd.read_csv(csv_path, parse_dates=["日期"])
        last_date = df_local["日期"].max().strftime("%Y-%m-%d")
    else:
        df_local = pd.DataFrame(columns=["日期", "价格"])
        last_date = None
    df_new = fetch_eia_data_v2(series_id, API_KEY, start=last_date)
    if df_new is not None and not df_new.empty:
        df_all = pd.concat([df_local, df_new]).drop_duplicates(subset="日期").sort_values("日期").reset_index(drop=True)
        df_all.to_csv(csv_path, index=False)
        return df_all
    else:
        return df_local


def aggregate_data(df, freq):
    """返回按 freq 聚合后的 DataFrame，'日期' 为 datetime，'价格' 为数值"""
    if df.empty:
        return df.copy()
    df = df.copy()
    if freq == "日":
        return df.sort_values("日期").reset_index(drop=True)
    elif freq == "月":
        df2 = df.resample("M", on="日期").mean().reset_index()
        return df2.sort_values("日期").reset_index(drop=True)
    elif freq == "年":
        df2 = df.resample("Y", on="日期").mean().reset_index()
        return df2.sort_values("日期").reset_index(drop=True)
    else:
        return df.sort_values("日期").reset_index(drop=True)


# ========== UI 辅助：分页显示表格（美化样式） ==========
def _inject_css():
    st.markdown(
        """
        <style>
        /* 按钮美化（影响页面上的所有按钮） */
        .stButton>button {
            border-radius: 12px;
            padding: 8px 14px;
            font-weight: 600;
            box-shadow: 0 3px 10px rgba(0,0,0,0.12);
            transition: transform .06s ease, box-shadow .06s ease;
            border: none;
        }
        .stButton>button:active { transform: translateY(1px); }
        /* 下载按钮更突出 */
        div[data-testid="stDownloadButton"] button {
            border-radius: 12px;
            padding: 8px 14px;
            font-weight:700;
        }
        /* 表格样式 */
        .big-table table {font-size:4.2vw; border-collapse: collapse; width:100%;}
        .big-table th, .big-table td { padding:8px 10px; text-align:center; border:1px solid #eee; }
        .big-table th { background:#f7f7f7;}
        /* 居中页码 */
        .page-info { text-align:center; font-size:0.95rem; margin:6px 0 8px 0; color:#333; }
        /* 小屏布局微调 */
        @media (min-width: 600px){
            .stButton>button { font-size:0.95rem; padding:10px 16px; }
            .big-table table { font-size:14px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def show_df_centered(display_df, page_size=15):
    """display_df: pandas.DataFrame，'日期' 为 datetime 类型。
       在函数内部会把 '日期' 格式化为字符串用于显示（按传入的 date_format）"""
    total_rows = len(display_df)
    if "page_num" not in st.session_state:
        st.session_state.page_num = 1

    total_pages = max(1, (total_rows - 1) // page_size + 1)

    # 保证 page_num 在合理范围
    if st.session_state.page_num > total_pages:
        st.session_state.page_num = total_pages
    if st.session_state.page_num < 1:
        st.session_state.page_num = 1

    # 横向按钮：上一页、页码、下一页
    c1, c2, c3 = st.columns([1, 1.4, 1])
    with c1:
        if st.button("⬅️ 上一页"):
            if st.session_state.page_num > 1:
                st.session_state.page_num -= 1
    with c2:
        st.markdown(f"<div class='page-info'>第 {st.session_state.page_num} / {total_pages} 页 — 共 {total_rows} 行</div>", unsafe_allow_html=True)
    with c3:
        if st.button("下一页 ➡️"):
            if st.session_state.page_num < total_pages:
                st.session_state.page_num += 1

    start = (st.session_state.page_num - 1) * page_size
    end = start + page_size
    page_df = display_df.iloc[start:end].reset_index(drop=True)

    # 输出 HTML 表格（带 class 方便 CSS）
    html = page_df.to_html(index=False)
    st.markdown(f"<div class='big-table'>{html}</div>", unsafe_allow_html=True)


# ========== Streamlit 页面布局 ==========
st.set_page_config(page_title="原油价格：实时期货 & 现货历史", layout="centered")
_inject_css()

st.title("📊 国际原油：期货实时 & 现货历史价格面板")

# —— 期货实时价格 ——
st.subheader("⏱ 期货实时价格")
rt = fetch_realtime_prices()
now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

for name, color in zip(["布伦特原油期货", "WTI原油期货"], ["#FFC107", "#F44336"]):
    price = rt.get(name, {}).get("price")
    ts = rt.get(name, {}).get("time") or now_ts
    st.markdown(
        f"""
        <div style='background-color:{color};padding:12px;border-radius:12px;margin-bottom:10px;text-align:center;'>
            <h3 style='color:white;font-size:5vw;margin:6px 0;'>⛽ {name}</h3>
            <p style='color:white;font-size:6.5vw;font-weight:bold;margin:4px 0;'>{('--' if price is None else f'{price:.2f}')} 美元/桶</p>
            <p style='color:white;font-size:3.5vw;margin:2px 0;'>更新时间 {ts}</p>
        </div>
        """, unsafe_allow_html=True
    )

st.markdown("---")

# —— 现货最新结算价 ——
st.subheader("🆕 现货最新结算价")
raw_dfs = {}
spot_latest = {}
for name, sid in SERIES.items():
    df_raw = load_or_update_data(sid, name)
    raw_dfs[name] = df_raw
    if not df_raw.empty:
        last_row = df_raw.sort_values("日期").iloc[-1]
        spot_latest[name] = {"date": last_row["日期"].strftime("%Y-%m-%d"), "price": float(last_row["价格"])}

for name, color in zip(["布伦特原油现货", "WTI原油现货"], ["#FFC107", "#F44336"]):
    d = spot_latest.get(name)
    st.markdown(
        f"""
        <div style='background-color:{color};padding:12px;border-radius:12px;margin-bottom:10px;text-align:center;'>
            <h3 style='color:white;font-size:5vw;margin:6px 0;'>🛢 {name}</h3>
            <p style='color:white;font-size:6.5vw;font-weight:bold;margin:4px 0;'>{('--' if d is None else f'{d["price"]:.2f}')} 美元/桶</p>
            <p style='color:white;font-size:3.5vw;margin:2px 0;'>结算日期 {('--' if d is None else d["date"])}</p>
        </div>
        """, unsafe_allow_html=True
    )

st.markdown("---")

# —— 历史价格（图表在此标题下方） ——
st.subheader("📈 历史原油价格走势（EIA 数据）")

# 年份范围选择（放在图表上方）
years = st.select_slider("选择展示的年份范围", options=list(range(2000, 2026)), value=(2015, 2025))

# 如果没有 freq 初始值，默认月频
if "freq" not in st.session_state:
    st.session_state.freq = "月"

# 准备按年份过滤的原始数据
dfs = {}
for name, df_raw in raw_dfs.items():
    if not df_raw.empty:
        df = df_raw[(df_raw["日期"].dt.year >= years[0]) & (df_raw["日期"].dt.year <= years[1])]
        dfs[name] = df

# 只有当两组数据都存在时显示图与表
if "布伦特原油" in dfs and "WTI原油" in dfs and not dfs["布伦特原油"].empty and not dfs["WTI原油"].empty:
    # 按当前频率聚合（用于图表）
    df_b = aggregate_data(dfs["布伦特原油"], st.session_state.freq).rename(columns={"价格": "布伦特价格"})
    df_w = aggregate_data(dfs["WTI原油"], st.session_state.freq).rename(columns={"价格": "WTI价格"})

    merged_for_plot = pd.merge(df_b, df_w, on="日期", how="outer").sort_values("日期").reset_index(drop=True)

    # 折线图（放在 "历史原油价格走势（EIA 数据）" 标题下方）
    # 为保证 x 轴为时间类型，直接使用 '日期'（datetime）
    fig = px.line(
        merged_for_plot,
        x="日期",
        y=["布伦特价格", "WTI价格"],
        labels={"value": "价格 (美元/桶)", "日期": "日期"},
        title=f"布伦特 vs WTI 历史价格趋势（{st.session_state.freq}）"
    )
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=40, b=10)
    )
    st.plotly_chart(fig, use_container_width=True, config={'responsive': True})

    st.markdown("---")

    # —— 国际原油历史价格表（频率选择按钮放此标题下方） ——
    st.subheader("📋 国际原油历史价格表")

    # 频率选择按钮（横向排列，美观）
    btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
    with btn_col1:
        if st.button("🗓 日度数据"):
            st.session_state.freq = "日"
            st.session_state.page_num = 1
    with btn_col2:
        if st.button("📅 月度数据"):
            st.session_state.freq = "月"
            st.session_state.page_num = 1
    with btn_col3:
        if st.button("🧾 年度数据"):
            st.session_state.freq = "年"
            st.session_state.page_num = 1

    # 重新聚合以确保表格与图表使用相同的 freq（用户可能刚刚点了按钮）
    df_b = aggregate_data(dfs["布伦特原油"], st.session_state.freq).rename(columns={"价格": "布伦特价格"})
    df_w = aggregate_data(dfs["WTI原油"], st.session_state.freq).rename(columns={"价格": "WTI价格"})
    merged = pd.merge(df_b, df_w, on="日期", how="outer").sort_values("日期", ascending=False).reset_index(drop=True)

    # 准备供展示的 DataFrame（把日期格式化为字符串以便表格显示）
    display_df = merged[["日期", "布伦特价格", "WTI价格"]].copy()
    if st.session_state.freq == "日":
        display_df["日期"] = display_df["日期"].dt.strftime("%Y-%m-%d")
    elif st.session_state.freq == "月":
        display_df["日期"] = display_df["日期"].dt.strftime("%Y-%m")
    elif st.session_state.freq == "年":
        display_df["日期"] = display_df["日期"].dt.strftime("%Y")

    # 下载按钮放在表格标题下方
    output = io.BytesIO()
    # 导出为 Excel（注意：使用 xlsxwriter 引擎）
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        # 导出原始（非格式化日期）表用于下载更精准的数据
        merged_download = merged.sort_values("日期")
        merged_download.to_excel(writer, index=False, sheet_name="原油价格")
    st.download_button(
        label="💾 下载数据为 Excel",
        data=output.getvalue(),
        file_name="原油价格.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # 翻页表格（每页 15 行）
    # 注意：show_df_centered 期望 display_df 的 '日期' 是可直接显示的（已格式化为字符串）
    show_df_centered(display_df, page_size=15)

else:
    st.warning("未能成功获取历史数据，请检查 API Key 或网络连接。")
