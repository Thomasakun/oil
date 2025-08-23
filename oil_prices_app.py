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

def show_df_centered(display_df, page, page_size=15):
    start = page * page_size
    end = start + page_size
    page_df = display_df.iloc[start:end]

    # 表格美化
    html = page_df.to_html(index=False)
    st.markdown(
        f"""
        <div style='overflow-x:auto;'>
        <style>
        table {{font-size:5vw; border-collapse: collapse; width: 100%;}}
        th, td {{padding: 8px 12px; text-align: center; border: 1px solid #ddd;}}
        th {{background-color:#f2f2f2;}}
        </style>
        {html}
        </div>
        """,
        unsafe_allow_html=True
    )

    # 翻页按钮
    col1, col2, col3 = st.columns([1,2,1])
    with col1:
        if st.button("⬅ 上一页", disabled=(page==0)):
            st.session_state["page"] = max(0, page-1)
            st.experimental_rerun()
    with col3:
        if st.button("下一页 ➡", disabled=(end >= len(display_df))):
            st.session_state["page"] = page+1
            st.experimental_rerun()

# ========== Streamlit 页面 ==========
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
        <div style='background-color:{color};padding:15px;border-radius:15px;margin-bottom:12px;text-align:center;'>
        <h2 style='color:white;font-size:5vw;margin:5px 0;'>⛽ {name}</h2>
        <p style='color:white;font-size:6vw;font-weight:bold;margin:5px 0;'>{('--' if price is None else f'{price:.2f}')} 美元/桶</p>
        <p style='color:white;font-size:3.5vw;margin:2px 0;'>更新时间 {ts}</p>
        <p style='color:white;font-size:3vw;opacity:.85;margin:2px 0;'>说明：期货价格为盘中变动，为延迟报价</p>
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

for name, color in zip(["布伦特原油", "WTI原油"], ["#FFC107", "#F44336"]):
    d = spot_latest.get(name)
    st.markdown(
        f"""
        <div style='background-color:{color};padding:15px;border-radius:15px;margin-bottom:12px;text-align:center;'>
        <h2 style='color:white;font-size:5vw;margin:5px 0;'>🛢 {name}</h2>
        <p style='color:white;font-size:6vw;font-weight:bold;margin:5px 0;'>{('--' if d is None else f'{d["price"]:.2f}')} 美元/桶</p>
        <p style='color:white;font-size:3.5vw;margin:2px 0;'>结算日期 {('--' if d is None else d["date"])}</p>
        <p style='color:white;font-size:3vw;opacity:.85;margin:2px 0;'>EIA 日度统计价，反映交易日结算价（非盘中）</p>
        </div>
        """, unsafe_allow_html=True
    )

st.markdown("---")

# —— 历史价格图表 + 表格 ——
st.subheader("📈 历史原油价格走势（EIA 数据）")
years = st.select_slider("选择展示的年份范围", options=list(range(2000, 2026)), value=(2015, 2025))

dfs = {}
for name, df_raw in raw_dfs.items():
    if not df_raw.empty:
        df = df_raw[(df_raw["日期"].dt.year >= years[0]) & (df_raw["日期"].dt.year <= years[1])]
        dfs[name] = df

if "布伦特原油" in dfs and "WTI原油" in dfs and not dfs["布伦特原油"].empty and not dfs["WTI原油"].empty:
    # 初始频率
    if "freq" not in st.session_state:
        st.session_state["freq"] = "日"

    # —— 改成按钮组选择频率 ——
    st.subheader("📋 国际原油历史价格表")
    freq_col = st.columns(3)
    if freq_col[0].button("日度", use_container_width=True):
        st.session_state["freq"] = "日"
    if freq_col[1].button("月度", use_container_width=True):
        st.session_state["freq"] = "月"
    if freq_col[2].button("年度", use_container_width=True):
        st.session_state["freq"] = "年"
    freq = st.session_state["freq"]

    # 聚合数据
    dfs = {k: aggregate_data(v, freq) for k, v in dfs.items()}

    merged = dfs["布伦特原油"].merge(
        dfs["WTI原油"], on="日期", how="outer", suffixes=("_布伦特", "_WTI")
    ).sort_values("日期").rename(columns={"价格_布伦特": "布伦特价格", "价格_WTI": "WTI价格"})

    # 折线图
    fig = px.line(
        merged, x="日期", y=["布伦特价格", "WTI价格"],
        labels={"value": "价格 (美元/桶)", "日期": "日期"},
        title="布伦特 vs WTI 历史价格趋势"
    )
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=40, b=10)
    )
    st.plotly_chart(fig, use_container_width=True, config={'responsive': True})

    # 下载按钮
    display_df = merged[["日期", "布伦特价格", "WTI价格"]].sort_values("日期", ascending=False).reset_index(drop=True)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        display_df.to_excel(writer, index=False, sheet_name="原油价格")
    st.download_button(
        label="💾 下载数据为 Excel",
        data=output.getvalue(),
        file_name="原油价格.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # 分页表格
    if "page" not in st.session_state:
        st.session_state["page"] = 0
    show_df_centered(display_df, st.session_state["page"], page_size=15)

else:
    st.warning("未能成功获取历史数据，请检查 API Key 或网络连接。")
