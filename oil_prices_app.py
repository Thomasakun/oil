# 文件名: oil_prices_app.py
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
    "布伦特原油": "PET.RBRTE.D",  # EIA 现货-日度
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

def fetch_realtime_prices():
    """
    使用新浪财经接口获取延迟实时期货价格：
      - Brent: hf_OIL
      - WTI:   hf_CL
    返回: {"布伦特原油期货": {"price": 88.12, "time": "2025-08-22 15:03:05"}, "WTI原油期货": {...}}
    """
    endpoints = {
        "布伦特原油期货": "http://hq.sinajs.cn/list=hf_OIL",
        "WTI原油期货":   "http://hq.sinajs.cn/list=hf_CL",
    }
    headers = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0"
    }
    out = {}
    for name, url in endpoints.items():
        price, ts = None, None
        try:
            r = requests.get(url, headers=headers, timeout=6)
            r.encoding = "gbk"
            # 形如：var hq_str_hf_CL="NYMEX原油,82.10,0.22,0.27%,82.00,82.40,81.70,81.88,2025-08-22 15:03:05";
            if "=" in r.text:
                payload = r.text.split("=", 1)[1].strip().strip('";')
                parts = payload.split(",")
                # 通常 parts[1] 为最新价；若不行，就在前几个字段里找第一个可转 float 的值
                if len(parts) >= 2 and _safe_float(parts[1]) is not None:
                    price = round(float(parts[1]), 2)
                else:
                    for p in parts[:6]:
                        val = _safe_float(p)
                        if val is not None:
                            price = round(val, 2)
                            break
                # 末尾经常是时间戳
                if parts and ":" in parts[-1]:
                    ts = parts[-1]
        except Exception:
            pass
        out[name] = {"price": price, "time": ts}
    return out

# ========== 历史现货（EIA） ==========
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
        df = pd.DataFrame(records)[["period", "value"]]
        df = df.rename(columns={"period": "日期", "value": "价格"})
        df["日期"] = pd.to_datetime(df["日期"])
        return df.sort_values("日期")
    else:
        st.error(f"API 返回错误: {data}")
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
        df_all = pd.concat([df_local, df_new]).drop_duplicates(subset="日期")
        df_all = df_all.sort_values("日期").reset_index(drop=True)
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

def show_df_centered(display_df):
    left, mid, right = st.columns([1, 6, 1])
    with mid:
        try:
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        except TypeError:
            try:
                st.table(display_df.style.hide(axis="index"))
            except Exception:
                st.table(display_df)

# ========== Streamlit 页面 ==========
st.set_page_config(page_title="原油价格：实时期货 & 现货历史", layout="wide")

st.title("📊 国际原油：期货实时 & 现货历史价格面板")

# —— 期货：延迟实时价格（新浪） ——
st.subheader("⏱ 期货实时价格")
rt = fetch_realtime_prices()
col1, col2 = st.columns(2)
now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

with col1:
    price = rt.get("布伦特原油期货", {}).get("price")
    ts = rt.get("布伦特原油期货", {}).get("time") or now_ts
    st.markdown(
        f"""
        <div style='background-color:#1f77b4;padding:20px;border-radius:15px;text-align:center;'>
            <h2 style='color:white;'>⛽ 布伦特原油（期货）</h2>
            <p style='color:white;font-size:24px;font-weight:bold;'>{('--' if price is None else f'{price:.2f}')} 美元/桶</p>
            <p style='color:white;font-size:13px;margin-top:6px;'>更新时间 {ts}</p>
            <p style='color:white;font-size:12px;opacity:.85;margin-top:2px;'>说明：期货价格为盘中变动，为延迟报价</p>
        </div>
        """,
        unsafe_allow_html=True
    )

with col2:
    price = rt.get("WTI原油期货", {}).get("price")
    ts = rt.get("WTI原油期货", {}).get("time") or now_ts
    st.markdown(
        f"""
        <div style='background-color:#2ca02c;padding:20px;border-radius:15px;text-align:center;'>
            <h2 style='color:white;'>⛽ WTI原油（期货）</h2>
            <p style='color:white;font-size:24px;font-weight:bold;'>{('--' if price is None else f'{price:.2f}')} 美元/桶</p>
            <p style='color:white;font-size:13px;margin-top:6px;'>更新时间 {ts}</p>
            <p style='color:white;font-size:12px;opacity:.85;margin-top:2px;'>说明：期货价格为盘中变动，免为延迟报价</p>
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown("---")

# —— 现货：加载 EIA 原始日度数据（用于“最新结算价” + 下面的图表与表格） ——
raw_dfs = {}
spot_latest = {}  # {name: {"date": "YYYY-MM-DD", "price": float}}
for name, sid in SERIES.items():
    df_raw = load_or_update_data(sid, name)
    raw_dfs[name] = df_raw
    if not df_raw.empty:
        last_row = df_raw.sort_values("日期").iloc[-1]
        spot_latest[name] = {
            "date": last_row["日期"].strftime("%Y-%m-%d"),
            "price": float(last_row["价格"])
        }

# —— 现货：最新结算价（EIA 日度，非实时） ——
st.subheader("🆕 现货最新结算价（EIA 日度数据）")
c1, c2 = st.columns(2)
with c1:
    d = spot_latest.get("布伦特原油")
    st.markdown(
        f"""
        <div style='background-color:#3366cc;padding:20px;border-radius:15px;text-align:center;'>
            <h2 style='color:white;'>🛢 布伦特原油（现货）</h2>
            <p style='color:white;font-size:24px;font-weight:bold;'>{('--' if d is None else f'{d["price"]:.2f}')} 美元/桶</p>
            <p style='color:white;font-size:13px;margin-top:6px;'>结算日期 {('--' if d is None else d["date"])}</p>
            <p style='color:white;font-size:12px;opacity:.85;margin-top:2px;'>说明：EIA 日度统计价，反映交易日结算价（非盘中）</p>
        </div>
        """,
        unsafe_allow_html=True
    )
with c2:
    d = spot_latest.get("WTI原油")
    st.markdown(
        f"""
        <div style='background-color:#228833;padding:20px;border-radius:15px;text-align:center;'>
            <h2 style='color:white;'>🛢 WTI原油（现货）</h2>
            <p style='color:white;font-size:24px;font-weight:bold;'>{('--' if d is None else f'{d["price"]:.2f}')} 美元/桶</p>
            <p style='color:white;font-size:13px;margin-top:6px;'>结算日期 {('--' if d is None else d["date"])}</p>
            <p style='color:white;font-size:12px;opacity:.85;margin-top:2px;'>说明：EIA 日度统计价，反映交易日结算价（非盘中）</p>
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown("---")

# —— 历史价格（图表 + 表格） ——
st.subheader("📈 历史原油价格走势（EIA 数据）")
years = st.slider("选择展示的年份范围", 2000, 2025, (2015, 2025))
freq = st.radio("选择数据展示频率", ["日", "月", "年"], horizontal=True)

dfs = {}
for name, df_raw in raw_dfs.items():
    if not df_raw.empty:
        df = df_raw[(df_raw["日期"].dt.year >= years[0]) & (df_raw["日期"].dt.year <= years[1])]
        df = aggregate_data(df, freq)
        dfs[name] = df

if "布伦特原油" in dfs and "WTI原油" in dfs and not dfs["布伦特原油"].empty and not dfs["WTI原油"].empty:
    merged = dfs["布伦特原油"].merge(
        dfs["WTI原油"], on="日期", how="outer", suffixes=("_布伦特", "_WTI")
    ).sort_values("日期")

    merged = merged.rename(columns={
        "价格_布伦特": "布伦特价格",
        "价格_WTI": "WTI价格"
    })

    # 折线图
    fig = px.line(
        merged,
        x="日期",
        y=["布伦特价格", "WTI价格"],
        labels={"value": "价格 (美元/桶)", "日期": "日期"},
        title="布伦特原油 vs WTI原油 历史价格趋势（现货/EIA）"
    )
    st.plotly_chart(fig, use_container_width=True)

    # 表格（倒序、无索引、置中）
    st.subheader("📋 国际原油历史价格表（现货/EIA）")
    display_df = merged.reset_index(drop=True)
    display_df = display_df[["日期", "布伦特价格", "WTI价格"]]
    display_df = display_df.sort_values("日期", ascending=False).reset_index(drop=True)
    show_df_centered(display_df)

    # Excel 下载
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        display_df.to_excel(writer, index=False, sheet_name="原油价格")
    st.download_button(
        label="💾 下载数据为 Excel",
        data=output.getvalue(),
        file_name="原油价格.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.warning("未能成功获取历史数据，请检查 API Key 或网络连接。")
