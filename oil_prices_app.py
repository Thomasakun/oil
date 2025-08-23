# 文件名: oil_prices_app_mobile_v4.py
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

# ========== 实时期货价格（新浪财经） ==========
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

# ========== 历史现货（EIA） ==========
@st.cache_data(ttl=3600)
def fetch_eia_data_v2(series_id, api_key, start=None, end=None):
    url = f"https://api.eia.gov/v2/seriesid/{series_id}"
    params = {"api_key": api_key}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
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
    if df.empty:
        return df.copy()
    if freq == "日":
        df_show = df.copy()
        df_show["日期"] = df_show["日期"].dt.strftime("%Y-%m-%d")
    elif freq == "月":
        df_show = df.resample("M", on="日期").mean().reset_index()
        df_show["日期"] = df_show["日期"].dt.strftime("%Y-%m")
    elif freq == "年":
        df_show = df.resample("Y", on="日期").mean().reset_index()
        df_show["日期"] = df_show["日期"].dt.strftime("%Y")
    else:
        df_show = df.copy()
    return df_show

# ========== 分页表格显示函数（不使用 experimental_rerun） ==========
def show_df_centered(display_df, page, page_size=15):
    # 保证 page 合法
    total = len(display_df)
    max_page = 0 if total == 0 else (total - 1) // page_size
    page = max(0, min(page, max_page))
    start = page * page_size
    end = min(start + page_size, total)
    page_df = display_df.iloc[start:end]

    # 表格美化：使用 to_html（移除索引）
    html = page_df.to_html(index=False)
    st.markdown(
        f"""
        <div style='overflow-x:auto;'>
        <style>
        table {{font-size:4.8vw; border-collapse: collapse; width: 100%;}}
        th, td {{padding: 8px 12px; text-align: center; border: 1px solid #ddd;}}
        th {{background-color:#f2f2f2;}}
        @media (min-width:600px) {{
            table {{font-size:14px;}}
        }}
        </style>
        {html}
        </div>
        """,
        unsafe_allow_html=True
    )

    # 翻页回调（不调用 experimental_rerun）
    def go_prev():
        st.session_state["page"] = max(0, st.session_state.get("page", 0) - 1)

    def go_next():
        st.session_state["page"] = min(st.session_state.get("page", 0) + 1, max_page)

    # 三列布局：上一页 | 中间状态 | 下一页
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        st.button("⬅ 上一页", key=f"prev_btn_{page}", disabled=(page == 0), on_click=go_prev, use_container_width=False)
    with col2:
        st.markdown(f"**第 {page+1} / {max_page+1} 页**")
    with col3:
        st.button("下一页 ➡", key=f"next_btn_{page}", disabled=(page >= max_page), on_click=go_next, use_container_width=False)

# ========== Streamlit 页面主体 ==========
st.set_page_config(page_title="原油价格：实时期货 & 现货历史", layout="centered")
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
        <h3 style='color:white;font-size:4.8vw;margin:4px 0;'>⛽ {name}</h3>
        <p style='color:white;font-size:6.5vw;font-weight:bold;margin:4px 0;'>{('--' if price is None else f'{price:.2f}')} 美元/桶</p>
        <p style='color:white;font-size:3.2vw;margin:2px 0;'>更新时间 {ts}</p>
        </div>
        """,
        unsafe_allow_html=True
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
for name, color in zip(["布伦特原油", "WTI原油"], ["#FFC107", "#F44336"]):
    d = spot_latest.get(name)
    st.markdown(
        f"""
        <div style='background-color:{color};padding:12px;border-radius:12px;margin-bottom:10px;text-align:center;'>
        <h3 style='color:white;font-size:4.8vw;margin:4px 0;'>🛢 {name}</h3>
        <p style='color:white;font-size:6.5vw;font-weight:bold;margin:4px 0;'>{('--' if d is None else f'{d["price"]:.2f}')} 美元/桶</p>
        <p style='color:white;font-size:3.2vw;margin:2px 0;'>结算日期 {('--' if d is None else d["date"])}</p>
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown("---")

# —— 历史价格图表 + 表格 ——
st.subheader("📈 历史原油价格走势（EIA 数据）")

# 年份范围选择
years = st.select_slider("选择展示的年份范围", options=list(range(2000, datetime.now().year + 1)), value=(2015, datetime.now().year))

# 载入并过滤数据
dfs = {}
for name, df_raw in raw_dfs.items():
    if not df_raw.empty:
        df = df_raw[(df_raw["日期"].dt.year >= years[0]) & (df_raw["日期"].dt.year <= years[1])]
        dfs[name] = df

if "布伦特原油" in dfs and "WTI原油" in dfs and not dfs["布伦特原油"].empty and not dfs["WTI原油"].empty:
    # 初始化 session state
    if "freq" not in st.session_state:
        st.session_state["freq"] = "日"
    if "page" not in st.session_state:
        st.session_state["page"] = 0

    # 先生成折线图 — 保证图紧跟标题
    # 使用“日/月/年”聚合来生成图，图的 x 轴使用 datetime 类型以获得良好显示
    freq_for_chart = st.session_state["freq"]
    dfs_agg = {k: aggregate_data(v, freq_for_chart) for k, v in dfs.items()}

    # 把日期列解析为 datetime（聚合后得到的格式：日->YYYY-MM-DD, 月->YYYY-MM, 年->YYYY）
    merged = dfs_agg["布伦特原油"].merge(
        dfs_agg["WTI原油"],
        on="日期",
        how="outer",
        suffixes=("_布伦特", "_WTI")
    ).sort_values("日期").rename(columns={"价格_布伦特": "布伦特价格", "价格_WTI": "WTI价格"})

    # 尝试将 '日期' 转为 datetime，兼容 YYYY, YYYY-MM, YYYY-MM-DD
    merged["日期"] = pd.to_datetime(merged["日期"], errors="coerce", format=None)

    # 绘图
    fig = px.line(
        merged,
        x="日期",
        y=["布伦特价格", "WTI价格"],
        labels={"value": "价格 (美元/桶)", "日期": "日期"},
        title="布伦特 vs WTI 历史价格趋势"
    )
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=40, b=10),
        autosize=True
    )
    st.plotly_chart(fig, use_container_width=True, config={'responsive': True})

    # —— 表格标题、频率选择与下载放在图下方 ——
    st.subheader("📋 国际原油历史价格表")

    # 下载按钮（导出当前 freq 的 display 数据）
    # 先准备 display_df：把日期格式化为字符串，表格按日期降序显示
    if freq_for_chart == "日":
        date_fmt = "%Y-%m-%d"
    elif freq_for_chart == "月":
        date_fmt = "%Y-%m"
    else:
        date_fmt = "%Y"

    display_df = merged.copy()
    # 有些行日期解析可能为 NaT，先填充为空字符串以防导出报错
    display_df["日期"] = display_df["日期"].dt.strftime(date_fmt)
    display_df = display_df[["日期", "布伦特价格", "WTI价格"]].sort_values("日期", ascending=False).reset_index(drop=True)

    # 下载按钮（放在表名下方）
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        display_df.to_excel(writer, index=False, sheet_name="原油价格")
    st.download_button(
        label="💾 下载数据为 Excel",
        data=output.getvalue(),
        file_name=f"原油价格_{freq_for_chart}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # —— 频率按钮组（标题下方） ——
    c1, c2, c3 = st.columns(3)
    def set_freq_day(): st.session_state.update({"freq": "日", "page": 0})
    def set_freq_month(): st.session_state.update({"freq": "月", "page": 0})
    def set_freq_year(): st.session_state.update({"freq": "年", "page": 0})

    with c1:
        st.button("日度", key="freq_day", on_click=set_freq_day, use_container_width=True)
    with c2:
        st.button("月度", key="freq_month", on_click=set_freq_month, use_container_width=True)
    with c3:
        st.button("年度", key="freq_year", on_click=set_freq_year, use_container_width=True)

    # —— 分页表格显示（第一页为 session_state["page"]） ——
    show_df_centered(display_df, st.session_state.get("page", 0), page_size=15)

else:
    st.warning("未能成功获取历史数据，请检查 API Key 或网络连接。")
