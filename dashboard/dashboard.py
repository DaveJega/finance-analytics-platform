"""
Finance Analytics Platform
===========================
Upgrades over base version:
  1. Live OHLCV data from CoinGecko free-tier API (no key required)
  2. PostgreSQL persistence for portfolios and price alerts
  3. Telegram bot notifications for triggered alerts

─────────────────────────────────────────────────────────────────
SETUP INSTRUCTIONS
─────────────────────────────────────────────────────────────────

A) PostgreSQL
   1. Install PostgreSQL and create a database:
        createdb finance_dashboard
   2. Set the connection string in your environment (or .env file):
        export DATABASE_URL="postgresql://user:password@localhost:5432/finance_dashboard"
   3. The app auto-creates tables on first run.

B) Telegram Bot (optional — alerts still work without it, they just
   won't send Telegram messages)
   1. Open Telegram and message @BotFather
   2. Send /newbot, follow the prompts, copy the token you receive.
   3. Start a chat with your new bot, then visit:
        https://api.telegram.org/bot<TOKEN>/getUpdates
      Send a message to the bot first, then reload that URL.
      Find "chat" → "id" in the JSON — that is your CHAT_ID.
   4. Export both values:
        export TELEGRAM_BOT_TOKEN="123456:ABC-..."
        export TELEGRAM_CHAT_ID="987654321"

C) Install dependencies:
        pip install streamlit streamlit-authenticator pyyaml
                    pandas numpy plotly psycopg2-binary requests
                    python-telegram-bot==20.* python-dotenv

─────────────────────────────────────────────────────────────────
"""

import os
import time
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timedelta

import requests
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st
import yaml
import streamlit_authenticator as stauth

# Optional Telegram
try:
    from telegram import Bot as TelegramBot
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ── Load .env if present (dev convenience) ──────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ================================================================
# PAGE CONFIG (must be first Streamlit call)
# ================================================================
st.set_page_config(
    page_title="Finance Analytics Platform",
    page_icon="chart_with_upwards_trend",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ================================================================
# AUTHENTICATION
# ================================================================
with open("config.yaml", "r") as _f:
    config = yaml.safe_load(_f)

authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
    auto_hash=True,
)

try:
    authenticator.login()
except Exception as e:
    st.error(e)

auth_status = st.session_state.get("authentication_status")

# ================================================================
# ROLE / PERMISSION HELPERS
# ================================================================
ROLE_PERMISSIONS = {
    "admin":   {"dashboard", "portfolio", "insights", "alerts", "simulator", "pnl"},
    "analyst": {"dashboard", "portfolio", "insights", "alerts"},
    "viewer":  {"dashboard", "insights"},
}

USER_ROLES = {
    "admin":   "admin",
    "analyst": "analyst",
}


def get_role(username: str) -> str:
    return USER_ROLES.get(username, "viewer")


def can_access(username: str, feature: str) -> bool:
    return feature in ROLE_PERMISSIONS.get(get_role(username), set())


# ================================================================
# POSTGRESQL — connection & schema bootstrap
# ================================================================
DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_db_conn():
    """Return a psycopg2 connection, or None if DATABASE_URL is unset."""
    if not DATABASE_URL:
        return None
    try:
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    except Exception as e:
        log.error("DB connection failed: %s", e)
        return None


def bootstrap_db():
    """Create tables if they don't exist yet."""
    conn = get_db_conn()
    if conn is None:
        return
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS portfolios (
                    id          SERIAL PRIMARY KEY,
                    username    TEXT NOT NULL,
                    coin        TEXT NOT NULL,
                    allocation  NUMERIC NOT NULL,
                    budget      NUMERIC NOT NULL,
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id          SERIAL PRIMARY KEY,
                    username    TEXT NOT NULL,
                    coin        TEXT NOT NULL,
                    direction   TEXT NOT NULL,
                    target      NUMERIC NOT NULL,
                    triggered   BOOLEAN DEFAULT FALSE,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                );
            """)
    conn.close()


bootstrap_db()


# ── Portfolio helpers ────────────────────────────────────────────

def db_save_portfolio(username: str, allocations: dict, budget: float):
    conn = get_db_conn()
    if conn is None:
        return False
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM portfolios WHERE username = %s", (username,))
            for coin, pct in allocations.items():
                cur.execute(
                    "INSERT INTO portfolios (username, coin, allocation, budget) VALUES (%s,%s,%s,%s)",
                    (username, coin, pct, budget),
                )
    conn.close()
    return True


def db_load_portfolio(username: str):
    conn = get_db_conn()
    if conn is None:
        return None, None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT coin, allocation, budget FROM portfolios WHERE username = %s ORDER BY id",
            (username,),
        )
        rows = cur.fetchall()
    conn.close()
    if not rows:
        return None, None
    budget = float(rows[0]["budget"])
    allocations = {r["coin"]: float(r["allocation"]) for r in rows}
    return allocations, budget


# ── Alert helpers ────────────────────────────────────────────────

def db_save_alert(username: str, coin: str, direction: str, target: float):
    conn = get_db_conn()
    if conn is None:
        return False
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO alerts (username, coin, direction, target) VALUES (%s,%s,%s,%s)",
                (username, coin, direction, target),
            )
    conn.close()
    return True


def db_load_alerts(username: str):
    conn = get_db_conn()
    if conn is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, coin, direction, target, triggered, created_at FROM alerts "
            "WHERE username = %s ORDER BY id",
            (username,),
        )
        rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_delete_alert(alert_id: int):
    conn = get_db_conn()
    if conn is None:
        return
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
    conn.close()


def db_mark_alert_triggered(alert_id: int):
    conn = get_db_conn()
    if conn is None:
        return
    with conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE alerts SET triggered = TRUE WHERE id = %s", (alert_id,))
    conn.close()


# ================================================================
# TELEGRAM NOTIFICATIONS
# ================================================================
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log.warning("Telegram send failed: %s", e)

# ================================================================
# COINGECKO — live OHLCV (free tier, no key)
# ================================================================
CG_BASE = "https://api.coingecko.com/api/v3"


@st.cache_data(ttl=300)   # cache 5 min to stay well within free-tier rate limits
def cg_get_coin_id(name: str) -> str | None:
    """Map a display name to a CoinGecko coin id."""
    try:
        r = requests.get(f"{CG_BASE}/coins/list", timeout=10)
        r.raise_for_status()
        coins = r.json()
        name_lower = name.lower()
        for c in coins:
            if c["name"].lower() == name_lower or c["symbol"].lower() == name_lower:
                return c["id"]
    except Exception as e:
        log.warning("CoinGecko id lookup failed: %s", e)
    return None


@st.cache_data(ttl=300)
def fetch_live_ohlcv(coin_name: str, days: int = 30) -> pd.DataFrame | None:
    """
    Fetch OHLCV from CoinGecko /coins/{id}/ohlc endpoint.
    Supported day values: 1, 7, 14, 30, 90, 180, 365.
    Returns a DataFrame with columns: date, open, high, low, close, volume.
    Falls back to None so callers can use synthetic data.
    """
    coin_id = cg_get_coin_id(coin_name)
    if coin_id is None:
        return None
    # Snap to nearest supported granularity
    supported = [1, 7, 14, 30, 90, 180, 365]
    snapped = min(supported, key=lambda x: abs(x - days))
    try:
        r = requests.get(
            f"{CG_BASE}/coins/{coin_id}/ohlc",
            params={"vs_currency": "usd", "days": snapped},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()   # [[timestamp_ms, open, high, low, close], ...]
        if not data:
            return None
        df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close"])
        df["date"]   = pd.to_datetime(df["ts"], unit="ms")
        df["volume"] = 0   # OHLC endpoint doesn't include volume; add zeros as placeholder
        return df[["date", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        log.warning("CoinGecko OHLCV fetch failed for %s: %s", coin_name, e)
        return None


@st.cache_data(ttl=60)
def fetch_live_volume(coin_name: str, days: int = 30) -> pd.DataFrame | None:
    """Fetch daily total volume from CoinGecko /coins/{id}/market_chart."""
    coin_id = cg_get_coin_id(coin_name)
    if coin_id is None:
        return None
    try:
        r = requests.get(
            f"{CG_BASE}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": "daily"},
            timeout=15,
        )
        r.raise_for_status()
        data  = r.json()
        vols  = data.get("total_volumes", [])
        if not vols:
            return None
        df = pd.DataFrame(vols, columns=["ts", "volume"])
        df["date"] = pd.to_datetime(df["ts"], unit="ms")
        return df[["date", "volume"]]
    except Exception as e:
        log.warning("CoinGecko volume fetch failed for %s: %s", coin_name, e)
        return None


# ── Synthetic fallback (used when CoinGecko is unavailable) ─────
def generate_ohlcv(base_price: float, days: int = 60) -> pd.DataFrame:
    np.random.seed(42)
    dates  = [datetime.today() - timedelta(days=i) for i in range(days, 0, -1)]
    prices = [base_price]
    for _ in range(days - 1):
        prices.append(prices[-1] * (1 + np.random.normal(0, 0.03)))
    records = []
    for d, p in zip(dates, prices):
        o   = p * np.random.uniform(0.98, 1.02)
        c   = p * np.random.uniform(0.98, 1.02)
        h   = max(o, c) * np.random.uniform(1.00, 1.03)
        low = min(o, c) * np.random.uniform(0.97, 1.00)
        vol = np.random.randint(100_000, 5_000_000)
        records.append({"date": d, "open": o, "high": h, "low": low, "close": c, "volume": vol})
    return pd.DataFrame(records)


def get_ohlcv(coin_name: str, base_price: float, days: int) -> tuple[pd.DataFrame, bool]:
    """Return (ohlcv_df, is_live). Falls back to synthetic if API unavailable."""
    live = fetch_live_ohlcv(coin_name, days)
    if live is not None and not live.empty:
        return live, True
    return generate_ohlcv(base_price, days), False


# ================================================================
# MAIN APP (authenticated)
# ================================================================
if auth_status:
    username = st.session_state["username"]
    role     = get_role(username)

    authenticator.logout(location="sidebar")
    st.sidebar.markdown(f"**{st.session_state['name']}**  \nRole: `{role.upper()}`")

    # ── Reset password ───────────────────────────────────────────
    st.sidebar.markdown("---")
    if st.sidebar.button("Reset Password"):
        st.session_state["show_reset"] = True

    if st.session_state.get("show_reset"):
        st.subheader("Reset Password")
        try:
            if authenticator.reset_password(username):
                st.success("Password updated successfully.")
                with open("config.yaml", "w") as _f:
                    yaml.dump(config, _f, default_flow_style=False)
                st.session_state["show_reset"] = False
        except Exception as e:
            st.error(e)

    with open("config.yaml", "w") as _f:
        yaml.dump(config, _f, default_flow_style=False)

    # ── Load market data ─────────────────────────────────────────
    BASE_DIR  = Path(__file__).resolve().parent
    DATA_FILE = BASE_DIR.parent / "crypto_prices.csv"

    @st.cache_data(ttl=60)
    def load_data():
        df = pd.read_csv(DATA_FILE)
        df.columns = df.columns.str.strip()
        return df

    df = load_data()

    if "price_change_percentage_24h" not in df.columns:
        np.random.seed(0)
        df["price_change_percentage_24h"] = np.random.uniform(-15, 15, len(df))

    if "total_volume" not in df.columns:
        np.random.seed(1)
        df["total_volume"] = (df["market_cap"] * np.random.uniform(0.01, 0.15, len(df))).astype(int)

    # ── Sidebar nav ──────────────────────────────────────────────
    all_pages   = ["Dashboard", "Portfolio Analysis", "Market Insights"]
    admin_pages = ["Price Alerts", "Portfolio Simulator", "P&L Calculator"]

    if can_access(username, "alerts"):
        all_pages += admin_pages

    page = st.sidebar.radio("Navigation", all_pages)

    # ── Filters ──────────────────────────────────────────────────
    coins = st.sidebar.multiselect(
        "Select Coins",
        options=df["name"].unique(),
        default=list(df["name"].unique())[:10],
    )

    price_range = st.sidebar.slider(
        "Price Range (USD)",
        float(df["current_price"].min()),
        float(df["current_price"].max()),
        (float(df["current_price"].min()), float(df["current_price"].max())),
    )

    filtered_df = df[
        (df["name"].isin(coins)) &
        (df["current_price"] >= price_range[0]) &
        (df["current_price"] <= price_range[1])
    ].copy()

    # ── Auto-refresh ─────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("Auto-Refresh")
    auto_refresh     = st.sidebar.toggle("Enable Auto-Refresh", value=False)
    refresh_interval = st.sidebar.selectbox(
        "Interval", [30, 60, 120, 300], format_func=lambda x: f"{x}s", index=1
    )

    if auto_refresh:
        st.sidebar.success(f"Refreshing every {refresh_interval}s")
        time.sleep(refresh_interval)
        st.cache_data.clear()
        st.rerun()

    # ── DB status banner ─────────────────────────────────────────
    if not DATABASE_URL:
        st.sidebar.caption("DB: not configured (portfolios/alerts stored in session only)")
    else:
        st.sidebar.caption("DB: PostgreSQL connected")

    # ── Telegram status ──────────────────────────────────────────
    tg_configured = TELEGRAM_AVAILABLE and bool(TELEGRAM_TOKEN) and bool(TELEGRAM_CHAT_ID)
    st.sidebar.caption(f"Telegram: {'configured' if tg_configured else 'not configured'}")

    # ============================================================
    # DASHBOARD
    # ============================================================
    if page == "Dashboard":
        st.title("Finance Dashboard")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Assets", len(filtered_df))
        with col2:
            st.metric("Avg Price", f"${filtered_df['current_price'].mean():,.2f}")
        with col3:
            st.metric("Highest Price", f"${filtered_df['current_price'].max():,.2f}")
        with col4:
            st.metric("Market Cap", f"${filtered_df['market_cap'].sum():,.0f}")

        st.markdown("---")

        # Top Gainers / Losers
        st.subheader("Top Gainers & Losers (24h)")
        n_top = st.slider("How many to show", 3, 10, 5, key="top_n")
        sorted_by_change = df.dropna(subset=["price_change_percentage_24h"]).sort_values(
            "price_change_percentage_24h", ascending=False
        )
        gainers = sorted_by_change.head(n_top)
        losers  = sorted_by_change.tail(n_top).iloc[::-1]

        g_col, l_col = st.columns(2)
        with g_col:
            st.markdown("**Top Gainers**")
            fig_gainers = px.bar(
                gainers, x="name", y="price_change_percentage_24h",
                color="price_change_percentage_24h",
                color_continuous_scale="Greens",
                text_auto=".2f",
                labels={"price_change_percentage_24h": "Change %"},
            )
            fig_gainers.update_layout(showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig_gainers, use_container_width=True)

        with l_col:
            st.markdown("**Top Losers**")
            fig_losers = px.bar(
                losers, x="name", y="price_change_percentage_24h",
                color="price_change_percentage_24h",
                color_continuous_scale="Reds_r",
                text_auto=".2f",
                labels={"price_change_percentage_24h": "Change %"},
            )
            fig_losers.update_layout(showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig_losers, use_container_width=True)

        st.markdown("---")

        # Live Price Table
        st.subheader("Live Price Table")
        display_cols = ["name", "current_price", "price_change_percentage_24h", "market_cap", "total_volume"]
        available    = [c for c in display_cols if c in filtered_df.columns]
        price_table  = filtered_df[available].copy()
        price_table.rename(columns={
            "name":                        "Coin",
            "current_price":               "Price (USD)",
            "price_change_percentage_24h": "24h Change %",
            "market_cap":                  "Market Cap",
            "total_volume":                "Volume (24h)",
        }, inplace=True)

        def style_change(val):
            color = "green" if val > 0 else "red" if val < 0 else "grey"
            return f"color: {color}; font-weight: bold"

        if "24h Change %" in price_table.columns:
            styled = price_table.style.map(style_change, subset=["24h Change %"]).format({
                "Price (USD)":  "${:,.2f}",
                "24h Change %": "{:+.2f}%",
                "Market Cap":   "${:,.0f}",
                "Volume (24h)": "${:,.0f}",
            })
            st.dataframe(styled, use_container_width=True)
        else:
            st.dataframe(price_table, use_container_width=True)

        st.markdown("---")

        # Candlestick — live data preferred
        st.subheader("Candlestick Chart")
        candle_coin = st.selectbox("Coin", filtered_df["name"].tolist(), key="candle_sel")
        candle_days = st.slider("Days of history", 7, 90, 30, key="candle_days")

        base_p = float(filtered_df.loc[filtered_df["name"] == candle_coin, "current_price"].values[0])

        with st.spinner("Fetching live OHLCV data..."):
            ohlcv, is_live = get_ohlcv(candle_coin, base_p, candle_days)

        if is_live:
            st.caption("Source: CoinGecko (live)")
        else:
            st.caption("Source: synthetic (CoinGecko unavailable for this coin)")

        fig_candle = go.Figure(data=[
            go.Candlestick(
                x=ohlcv["date"],
                open=ohlcv["open"],
                high=ohlcv["high"],
                low=ohlcv["low"],
                close=ohlcv["close"],
                name=candle_coin,
            )
        ])
        fig_candle.update_layout(
            title=f"{candle_coin} — Candlestick ({candle_days}d)",
            xaxis_title="Date",
            yaxis_title="Price (USD)",
            xaxis_rangeslider_visible=True,
        )
        st.plotly_chart(fig_candle, use_container_width=True)

        st.markdown("---")

        # Volume Chart — live data preferred
        st.subheader("Volume Chart")
        vol_col_ui, bar_col = st.columns([3, 1])
        with bar_col:
            vol_chart_type = st.radio("Chart type", ["Bar", "Area"], key="vol_type")
        with vol_col_ui:
            vol_coin = st.selectbox("Coin", filtered_df["name"].tolist(), key="vol_sel")

        with st.spinner("Fetching volume data..."):
            live_vol = fetch_live_volume(vol_coin, days=30)

        if live_vol is not None and not live_vol.empty:
            vol_ohlcv = live_vol
            vol_source = "CoinGecko (live)"
        else:
            vol_base  = float(filtered_df.loc[filtered_df["name"] == vol_coin, "current_price"].values[0])
            vol_ohlcv = generate_ohlcv(vol_base, days=30)[["date", "volume"]]
            vol_source = "synthetic"

        st.caption(f"Source: {vol_source}")

        if vol_chart_type == "Bar":
            fig_vol = px.bar(vol_ohlcv, x="date", y="volume",
                             title=f"{vol_coin} — Daily Volume (30d)",
                             labels={"volume": "Volume", "date": "Date"})
        else:
            fig_vol = px.area(vol_ohlcv, x="date", y="volume",
                              title=f"{vol_coin} — Daily Volume (30d)",
                              labels={"volume": "Volume", "date": "Date"})
        st.plotly_chart(fig_vol, use_container_width=True)

    # ============================================================
    # PORTFOLIO ANALYSIS
    # ============================================================
    elif page == "Portfolio Analysis":
        st.title("Portfolio Analysis")

        fig = px.pie(filtered_df, names="name", values="market_cap", hole=0.4,
                     title="Market Cap Distribution")
        st.plotly_chart(fig, use_container_width=True)

        fig2 = px.scatter(filtered_df, x="current_price", y="market_cap",
                          size="market_cap", color="name",
                          title="Price vs Market Cap")
        st.plotly_chart(fig2, use_container_width=True)

    # ============================================================
    # MARKET INSIGHTS
    # ============================================================
    elif page == "Market Insights":
        st.title("Market Insights")

        btc_row   = df[df["name"] == "Bitcoin"]["current_price"]
        btc_price = float(btc_row.values[0]) if not btc_row.empty else 0.0

        btc_amount    = st.number_input("Bitcoin Holdings", min_value=0.0, step=0.001)
        portfolio_val = btc_amount * btc_price
        st.metric("Portfolio Value", f"${portfolio_val:,.2f}")

        with st.expander("View Filtered Data"):
            st.dataframe(filtered_df)

    # ============================================================
    # PRICE ALERTS
    # ============================================================
    elif page == "Price Alerts":
        if not can_access(username, "alerts"):
            st.error("You don't have permission to access Price Alerts.")
            st.stop()

        st.title("Price Alerts")
        st.info(
            "Set a target price. The app checks it on each refresh and sends "
            "a Telegram message when triggered (if Telegram is configured)."
        )

        # ── Add alert form ───────────────────────────────────────
        with st.form("alert_form"):
            a_coin      = st.selectbox("Coin", df["name"].tolist())
            a_direction = st.radio("Alert when price is", ["Above", "Below"], horizontal=True)
            a_target    = st.number_input("Target Price (USD)", min_value=0.0, step=1.0)
            submitted   = st.form_submit_button("Add Alert")
            if submitted:
                saved = db_save_alert(username, a_coin, a_direction, a_target)
                if not saved:
                    # fallback to session state if DB unavailable
                    if "session_alerts" not in st.session_state:
                        st.session_state["session_alerts"] = []
                    st.session_state["session_alerts"].append({
                        "id":        None,
                        "coin":      a_coin,
                        "direction": a_direction,
                        "target":    a_target,
                        "triggered": False,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
                st.success(f"Alert added: {a_coin} {a_direction.lower()} ${a_target:,.2f}")

        st.markdown("---")
        st.subheader("Active Alerts")

        # Merge DB alerts + session fallback
        db_alerts = db_load_alerts(username)
        session_alerts = st.session_state.get("session_alerts", [])
        all_alerts = db_alerts if db_alerts else session_alerts

        if not all_alerts:
            st.write("No alerts set yet.")
        else:
            to_delete = []
            for alert in all_alerts:
                row       = df[df["name"] == alert["coin"]]
                cur_price = float(row["current_price"].values[0]) if not row.empty else 0.0
                triggered = (
                    (alert["direction"] == "Above" and cur_price >= alert["target"]) or
                    (alert["direction"] == "Below"  and cur_price <= alert["target"])
                )

                # Send Telegram on first trigger
                if triggered and not alert.get("triggered"):
                    msg = (
                        f"*Price Alert Triggered*\n"
                        f"Coin: {alert['coin']}\n"
                        f"Condition: {alert['direction']} ${alert['target']:,.2f}\n"
                        f"Current price: ${cur_price:,.2f}"
                    )
                    send_telegram(msg)
                    if alert.get("id"):
                        db_mark_alert_triggered(alert["id"])

                status = "TRIGGERED" if triggered else "Watching"
                cols   = st.columns([3, 2, 2, 2, 1])
                cols[0].write(f"**{alert['coin']}**")
                cols[1].write(f"{alert['direction']} ${alert['target']:,.2f}")
                cols[2].write(f"Now: ${cur_price:,.2f}")
                cols[3].write(status)
                if cols[4].button("Delete", key=f"del_{alert.get('id', id(alert))}"):
                    to_delete.append(alert)

            for a in to_delete:
                if a.get("id"):
                    db_delete_alert(a["id"])
                elif a in st.session_state.get("session_alerts", []):
                    st.session_state["session_alerts"].remove(a)
            if to_delete:
                st.rerun()

    # ============================================================
    # PORTFOLIO SIMULATOR
    # ============================================================
    elif page == "Portfolio Simulator":
        if not can_access(username, "simulator"):
            st.error("You don't have permission to access the Portfolio Simulator.")
            st.stop()

        st.title("Portfolio Simulator")
        st.markdown("Allocate a budget across coins and simulate your portfolio value over time.")

        # Load saved portfolio if DB is available
        saved_allocs, saved_budget = db_load_portfolio(username)
        default_budget = saved_budget if saved_budget else 10_000.0

        budget = st.number_input("Total Budget (USD)", min_value=100.0,
                                 value=default_budget, step=100.0)

        st.subheader("Allocate your portfolio (%)")
        allocations = {}
        sim_coins   = filtered_df["name"].tolist()[:8]
        default_pct = round(100 / len(sim_coins), 1)

        alloc_cols = st.columns(len(sim_coins))
        for i, coin in enumerate(sim_coins):
            saved_pct = saved_allocs.get(coin, default_pct) if saved_allocs else default_pct
            with alloc_cols[i]:
                pct = st.number_input(coin, min_value=0.0, max_value=100.0,
                                       value=saved_pct, step=1.0, key=f"alloc_{coin}")
                allocations[coin] = pct

        total_pct = sum(allocations.values())
        if abs(total_pct - 100) > 0.5:
            st.warning(f"Allocations sum to {total_pct:.1f}% — adjust to reach 100%.")
        else:
            st.success("Allocations sum to 100%")

        save_col, _ = st.columns([1, 3])
        with save_col:
            if st.button("Save Portfolio"):
                ok = db_save_portfolio(username, allocations, budget)
                if ok:
                    st.success("Portfolio saved to database.")
                else:
                    st.warning("Database not configured; portfolio was not persisted.")

        st.markdown("---")
        st.subheader("Simulated Portfolio Snapshot")

        sim_rows = []
        for coin, pct in allocations.items():
            if pct == 0:
                continue
            price     = float(filtered_df.loc[filtered_df["name"] == coin, "current_price"].values[0])
            usd_alloc = budget * pct / 100
            units     = usd_alloc / price
            sim_rows.append({"Coin": coin, "Allocation %": pct,
                              "USD Value": usd_alloc, "Units Held": units, "Price": price})

        if sim_rows:
            sim_df = pd.DataFrame(sim_rows)
            st.dataframe(sim_df.style.format({
                "Allocation %": "{:.1f}%",
                "USD Value":    "${:,.2f}",
                "Units Held":   "{:.6f}",
                "Price":        "${:,.2f}",
            }), use_container_width=True)

            fig_sim = px.pie(sim_df, names="Coin", values="USD Value",
                             title="Portfolio Allocation", hole=0.35)
            st.plotly_chart(fig_sim, use_container_width=True)

            # Monte Carlo
            st.subheader("30-day Monte Carlo Simulation")
            n_sims = 200
            final_values = []
            for _ in range(n_sims):
                total = 0
                for row in sim_rows:
                    daily_rets   = np.random.normal(0.001, 0.03, 30)
                    future_price = row["Price"] * np.prod(1 + daily_rets)
                    total       += row["Units Held"] * future_price
                final_values.append(total)

            fig_mc = px.histogram(
                x=final_values, nbins=40,
                title="Distribution of Simulated Portfolio Values (30d)",
                labels={"x": "Portfolio Value (USD)", "y": "Count"},
            )
            fig_mc.add_vline(x=budget, line_dash="dash", line_color="red",
                             annotation_text="Initial Budget")
            fig_mc.add_vline(x=np.percentile(final_values, 5),  line_dash="dot", line_color="orange",
                             annotation_text="5th pct")
            fig_mc.add_vline(x=np.percentile(final_values, 95), line_dash="dot", line_color="green",
                             annotation_text="95th pct")
            st.plotly_chart(fig_mc, use_container_width=True)

            p5, med, p95 = (np.percentile(final_values, p) for p in [5, 50, 95])
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("5th Percentile",  f"${p5:,.0f}",  f"{(p5-budget)/budget*100:+.1f}%")
            mc2.metric("Median Outcome",  f"${med:,.0f}", f"{(med-budget)/budget*100:+.1f}%")
            mc3.metric("95th Percentile", f"${p95:,.0f}", f"{(p95-budget)/budget*100:+.1f}%")

    # ============================================================
    # P&L CALCULATOR
    # ============================================================
    elif page == "P&L Calculator":
        if not can_access(username, "pnl"):
            st.error("You don't have permission to access the P&L Calculator.")
            st.stop()

        st.title("Profit / Loss Calculator")

        pnl_coin  = st.selectbox("Select Coin", df["name"].tolist(), key="pnl_coin")
        cur_price = float(df.loc[df["name"] == pnl_coin, "current_price"].values[0])

        col_a, col_b = st.columns(2)
        with col_a:
            buy_price = st.number_input("Buy Price (USD)", min_value=0.0,
                                         value=cur_price * 0.9, step=0.01)
            quantity  = st.number_input("Quantity", min_value=0.0, value=1.0, step=0.001)
            fees_pct  = st.number_input("Trading Fee (%)", min_value=0.0, value=0.1, step=0.01)
        with col_b:
            sell_price = st.number_input("Sell / Current Price (USD)",
                                          min_value=0.0, value=cur_price, step=0.01)
            st.markdown(f"**Current Market Price:** ${cur_price:,.2f}")

        cost      = buy_price  * quantity
        revenue   = sell_price * quantity
        fee_cost  = cost    * fees_pct / 100
        fee_rev   = revenue * fees_pct / 100
        net_pnl   = (revenue - fee_rev) - (cost + fee_cost)
        pnl_pct   = (net_pnl / (cost + fee_cost) * 100) if (cost + fee_cost) > 0 else 0
        breakeven = buy_price * (1 + fees_pct / 100) ** 2

        st.markdown("---")
        st.subheader("Results")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Total Cost",  f"${cost + fee_cost:,.2f}")
        r2.metric("Net Revenue", f"${revenue - fee_rev:,.2f}")
        r3.metric("Net P&L",     f"${net_pnl:,.2f}", f"{pnl_pct:+.2f}%",
                  delta_color="normal" if net_pnl >= 0 else "inverse")
        r4.metric("Break-even",  f"${breakeven:,.4f}")

        if net_pnl >= 0:
            st.success(f"Profitable trade: +${net_pnl:,.2f} ({pnl_pct:+.2f}%)")
        else:
            st.error(f"Loss: ${net_pnl:,.2f} ({pnl_pct:+.2f}%)")

        # Sensitivity
        st.markdown("---")
        st.subheader("Sensitivity — P&L at Different Sell Prices")
        price_range_sens = np.linspace(buy_price * 0.7, buy_price * 1.5, 17)
        sens_rows = []
        for sp in price_range_sens:
            rev = sp * quantity
            f_c = cost * fees_pct / 100
            f_r = rev  * fees_pct / 100
            pnl = (rev - f_r) - (cost + f_c)
            pct = pnl / (cost + f_c) * 100 if (cost + f_c) > 0 else 0
            sens_rows.append({"Sell Price": sp, "Net P&L": pnl, "Return %": pct})

        sens_df  = pd.DataFrame(sens_rows)
        fig_sens = px.line(sens_df, x="Sell Price", y="Net P&L",
                           title="P&L Sensitivity to Sell Price",
                           labels={"Net P&L": "Net P&L (USD)"})
        fig_sens.add_hline(y=0, line_dash="dash", line_color="grey")
        fig_sens.add_vline(x=buy_price, line_dash="dot", line_color="blue",
                           annotation_text="Buy price")
        st.plotly_chart(fig_sens, use_container_width=True)


# ================================================================
# NOT LOGGED IN
# ================================================================
elif auth_status is None:
    st.warning("Please enter your username and password to continue.")
    st.markdown("---")
    st.subheader("New here? Create an account")

    try:
        email, username, name = authenticator.register_user()
        if email:
            st.success("Account created! You can now log in.")
            with open("config.yaml", "w") as _f:
                yaml.dump(config, _f, default_flow_style=False)
    except Exception as e:
        st.error(e)