# 文件名: oil_prices_app_mobile_v3.py
"""
移动端友好版：原油价格面板
- 折线图固定放在 "历史原油价格走势（EIA 数据）" 标题下方
- 频率选择使用横向 radio（手机端也为横向布局）
- 表格分页使用滑块选择页码（水平滑块，手机端体验好），并保留上一页 / 下一页按钮
- 下载按钮在表格标题下方
"""
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
    if df is None or df.empty:
        return pd.DataFrame(columns=["日期", "价格"])
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


# ========== UI 辅助：CSS 和 分页表格 ==========
def _inject_css():
    st.markdown(
        """
        <style>
        /* 全局按钮圆角与阴影 */
        .stButton>button, div[data-testid="stDownloadButton"] button {
            border-radius: 10px;
            padding: 8px 12px;
            font-weight: 600;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            border: none;
        }
        /* 美化下载按钮更醒目 */
        div[data-testid="stDownloadButton"] button { font-weight:700; }
        /* 表格样式（适配手机大字体） */
        .big-table table { font-size:4.4vw; width:100%; border-collapse:collapse; }
        .big-table th, .big-table td { padding:8px 10px; text-align:center; border:1px solid #eee; }
        .big-table th { background:#fafafa; font-weight:700; }
        /* 页码信息 */
        .page-info { text-align:center; margin:6px 0 8px 0; font-size:0.95rem; color:#333; }
        /* 保证 radio 横向在窄屏也显示为横向（st.radio horizontal=True 已有，但这里做补强） */
        .stRadio > div[role="radiogroup"] { display:flex; flex-wrap:nowrap; gap:6px; }
        /* 防止列在超窄屏下折叠得太难看，允许横向滚动 */
        .horizontal-scroll { overflow-x:auto; white-space:nowrap; }
        </style>
        """,
        unsafe_allow_html=True
    )


def show_df_centered(display_df, page_size=15, slider_key="page_slider"):
    """
    display_df: pandas.DataFrame (日期 字段应已为字符串或可显示)
    page_size: 每页行数
    slider_key: 用于 slider 的 session_state key（支持多个表时传不同 key）
    """
    total_rows = len(display_df)
    if total_rows == 0:
        st.info("当前没有可显示的数据。")
        return

    total_pages = max(1, (total_rows - 1) // page_size + 1)

    # 初始化 page_num
    if "page_num" not in st.session_state:
        st.session_state.page_num = 1
    if st.session_state.page_num < 1:
        st.session_state.page_num = 1
    if st.session_state.page_num > total_pages:
        st.session_state.page_num = total_pages

    # 页码滑块（水平控件，移动端友好）
    # 使用独立 slider_key 保证多表或多处使用不会冲突
    st.markdown("<div class='horizontal-scroll'>", unsafe_allow_html=True)
    new_page = st.slider("跳转页码", min_value=1, max_value=total_pages, value=st.session_state.page_num, key=slider_key)
    st.markdown("</div>", unsafe_allow_html=True)

    # 如果滑块改变，则更新 page_num
    st.session_state.page_num = int(new_page)

    # 同一行显示 上一页 / 页码信息 / 下一页（若空间不足会换行，但滑块保证了横向交互）
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        if st.button("⬅️ 上一页"):
            if st.session_state.page_num > 1:
                st.session_state.page_num -= 1
                st.session_state[slider_key] = st.session_state.page_num
    with c2:
        st.markdown(f"<div class='page-info'>第 {st.session_state.page_num} / {total_pages} 页 — 共 {total_rows} 行</div>", unsafe_allow_html=True)
    with c3:
        if st.button("下一页 ➡️"):
            if st.session_state.page_num < total_pages:
                st.session_state.page_num += 1
                st.session_state[slider_key] = st.session_state.page_num

    # 计算当前页的数据并显示
    start = (st.session_state.page_num - 1) * page_size
    end = start + page_size
    page_df = display_df.iloc[start:end].reset_index(drop=True)

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

for name, color in zip(["布伦特原油", "WTI原油"], ["#FFC107", "#F44336"]):
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

# —— 历史价格（折线图固定在此标题下方） ——
st.subheader("📈 历史原油价格走势（EIA 数据）")

# 年份范围选择（放在图表上方）
years = st.select_slider("选择展示的年份范围", options=list(range(2000, 2026)), value=(2015, 2025))

# 保证 freq 有初始值
if "freq" not in st.session_state:
    st.session_state.freq = "月"

# 过滤按年份
dfs = {}
for name, df_raw in raw_dfs.items():
    if not df_raw.empty:
        df = df_raw[(df_raw["日期"].dt.year >= years[0]) & (df_raw["日期"].dt.year <= years[1])]
        dfs[name] = df

# 仅当两组数据都有时显示图与表
if "布伦特原油" in dfs and "WTI原油" in dfs and not dfs["布伦特原油"].empty and not dfs["WTI原油"].empty:
    # 先聚合为当前 freq，用于图表（保持时间列为 datetime）
    df_b_plot = aggregate_data(dfs["布伦特原油"], st.session_state.freq).rename(columns={"价格": "布伦特价格"})
    df_w_plot = aggregate_data(dfs["WTI原油"], st.session_state.freq).rename(columns={"价格": "WTI价格"})
    merged_for_plot = pd.merge(df_b_plot, df_w_plot, on="日期", how="outer").sort_values("日期").reset_index(drop=True)

    # 折线图 — 直接放在 "历史原油价格走势（EIA 数据）" 标题下方
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

    # —— 国际原油历史价格表（频率选择放在此标题下方） ——
    st.subheader("📋 国际原油历史价格表")

    # 横向频率选择（使用 st.radio horizontal=True，移动端会横向显示）
    freq = st.radio(
        "选择数据频率",
        options=["日", "月", "年"],
        index={"日": 0, "月": 1, "年": 2}.get(st.session_state.freq, 1),
        horizontal=True,
        key="freq_radio"
    )
    # 将 radio 的选择写回 session_state.freq（保持兼容）
    st.session_state.freq = freq
    # 每次切换频率回到第1页
    st.session_state.page_num = 1
    # 页面每页行数（可改成下拉）
    PAGE_SIZE = 15

    # 重新为表格聚合（基于最新 freq）
    df_b = aggregate_data(dfs["布伦特原油"], st.session_state.freq).rename(columns={"价格": "布伦特价格"})
    df_w = aggregate_data(dfs["WTI原油"], st.session_state.freq).rename(columns={"价格": "WTI价格"})
    merged = pd.merge(df_b, df_w, on="日期", how="outer").sort_values("日期", ascending=False).reset_index(drop=True)

    # 为显示格式化日期（用于表格 HTML）
    display_df = merged[["日期", "布伦特价格", "WTI价格"]].copy()
    if not display_df.empty:
        if st.session_state.freq == "日":
            display_df["日期"] = display_df["日期"].dt.strftime("%Y-%m-%d")
        elif st.session_state.freq == "月":
            display_df["日期"] = display_df["日期"].dt.strftime("%Y-%m")
        elif st.session_state.freq == "年":
            display_df["日期"] = display_df["日期"].dt.strftime("%Y")

    # 下载按钮放在表格标题下方
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        merged_download = merged.sort_values("日期")
        merged_download.to_excel(writer, index=False, sheet_name="原油价格")
    st.download_button(
        label="💾 下载数据为 Excel",
        data=output.getvalue(),
        file_name="原油价格.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # 翻页表格（使用水平滑块和上一/下一按钮）
    # 使用唯一 slider key 以避免与其他地方冲突
    show_df_centered(display_df, page_size=PAGE_SIZE, slider_key="page_slider_main")

else:
    st.warning("未能成功获取历史数据，请检查 API Key 或网络连接。")
