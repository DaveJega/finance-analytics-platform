from pathlib import Path
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import streamlit as st
import pandas as pd
import plotly.express as px


# ---------------- PAGE CONFIG ----------------
st.set_page_config(
    page_title="Finance Analytics Platform",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- PATHS ----------------
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR.parent / "crypto_prices.csv"
PREDICTION_FILE = BASE_DIR / "prediction_result.csv"

# ---------------- LOAD DATA (CACHED) ----------------
@st.cache_data
def load_data():
    df = pd.read_csv(DATA_FILE)
    df.columns = df.columns.str.strip()  # prevent hidden space bugs
    return df

df = load_data()

# ---------------- TITLE ----------------
st.title("Finance Analytics Dashboard")

# ---------------- RAW DATA ----------------
st.dataframe(df)

# ---------------- QUICK METRICS ----------------
st.bar_chart(df["current_price"])

st.metric("Total Coins", len(df))
st.metric("Highest Price", f"{df['current_price'].max():,.2f}")

# ---------------- SIMPLE BAR CHART ----------------
fig_main = px.bar(
    df,
    x="name",
    y="current_price",
    title="Current Prices"
)
st.plotly_chart(fig_main, use_container_width=True, key="main_bar")

# ---------------- PREDICTION SECTION ----------------
st.subheader("Machine Learning Predictions")

try:
    pred_df = pd.read_csv(PREDICTION_FILE)
    prediction = pred_df["predicted_value"].iloc[0]

    st.metric(
        label="Predicted Next Price",
        value=f"${prediction:,.2f}"
    )

except FileNotFoundError:
    st.warning("Run predictor.py first to see results.")

# ---------------- SIDEBAR FILTERS ----------------
st.sidebar.header("Dashboard Filters")

coins = st.sidebar.multiselect(
    "Select Coins",
    options=df["name"].unique(),
    default=df["name"].unique()
)

price_range = st.sidebar.slider(
    "Price Range",
    float(df["current_price"].min()),
    float(df["current_price"].max()),
    (float(df["current_price"].min()), float(df["current_price"].max()))
)

# ---------------- FILTER DATA ----------------
filtered_df = df[
    (df["name"].isin(coins)) &
    (df["current_price"] >= price_range[0]) &
    (df["current_price"] <= price_range[1])
]

# ---------------- DASHBOARD METRICS ----------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Assets", len(filtered_df))

with col2:
    st.metric("Avg Price", f"${filtered_df['current_price'].mean():,.2f}")

with col3:
    st.metric("Highest Price", f"${filtered_df['current_price'].max():,.2f}")

with col4:
    st.metric("Market Cap", f"${filtered_df['market_cap'].sum():,.0f}")

# ---------------- PIE CHART ----------------
st.subheader("Portfolio Distribution")

fig_pie = px.pie(
    filtered_df,
    names="name",
    values="market_cap",
    hole=0.4
)

st.plotly_chart(fig_pie, use_container_width=True, key="pie_chart")

# ---------------- BAR CHART ----------------
st.subheader("Current Asset Prices")

fig_bar = px.bar(
    filtered_df,
    x="name",
    y="current_price"
)

st.plotly_chart(fig_bar, use_container_width=True, key="bar_chart")

# ---------------- SCATTER PLOT ----------------
st.subheader("Market Cap Analysis")

fig_scatter = px.scatter(
    filtered_df,
    x="current_price",
    y="market_cap",
    size="market_cap",
    color="name",
    hover_name="name"
)

st.plotly_chart(fig_scatter, use_container_width=True, key="scatter_chart")

# ---------------- FOOTER ----------------
st.markdown("Track crypto and stock portfolio performance in real time.")
st.markdown("""
<style>
.big-font {
    font-size:28px !important;
    font-weight: bold;
}
.metric-card 
     background-color: #1e1e1e;
    padding:20px;
    border-radius: 10px;
    }       
            
</style>
""", unsafe_allow_html=True)

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", 
     "Portfolio Analysis",
     "Market Insights",
     ]
)

## Page Logic
if page == "Dashboard":
    st.title("Main Dashboard")

elif page == "Portfolio Analysis":
    st.title("Portfolio Analysis")

elif page == "Market Insights":
    st.title("Market Insights")

    ## Create Portfolio Inputs
    btc_amount = st.number_input(
        "Bitcoin Holdings",
        min_value=0.0,
    )    
        
    eth_amount = st.number_input(
        "Ethereum Holdings",
        min_value=0.0,
    )

##Calculate Portfolio Value
    
    btc_price = filtered_df[filtered_df["name"] == "Bitcoin"]["current_price"].values[0] 

    portfolio_value = btc_amount * btc_price

    st.metric(
        "Portfolio Value",
        f"${portfolio_value:,.2f}"
    )

    ## Add expanders for more insights
    with st.expander("View Raw Trends"):
        st.dataframe(filtered_df)

        ## Add tabs
        tab1, tab2 = st.tabs([
            "Market Data",
            "Charts"
        ])
       