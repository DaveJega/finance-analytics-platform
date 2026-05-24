import streamlit as st
import pandas as pd

st.title("Finance Analytics Dashboard")

df = pd.read_csv("crypto_prices.csv")

st.dataframe(df)

st.bar_chart(df["current_price"]) 


st.metric(
label="Total Coins", value=len(df)    
)
st.metric(label="Highest Price", value=df["current_price"].max()
)


import plotly.express as px
fig = px.bar(
    df,
    x="name",
    y="current_price"
)
st.plotly_chart(fig)

# Display prediction results
st.subheader("Machine Learning Predictions")
try:
    pred_df = pd.read_csv("dashboard/prediction_result.csv")
    prediction = pred_df["predicted_value"].iloc[0]
    st.metric(label="Predicted Next Price", value=f"${prediction:,.2f}")
except FileNotFoundError:
    st.warning("Run predictor.py first to see results.")