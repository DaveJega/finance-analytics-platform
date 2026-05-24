import pandas as pd
import os

print("File exists:", os.path.exists("data/crypto_prices.csv"))

df = pd.read_csv("data/crypto_prices.csv")

print(df.columns)

df["moving_average"] = (
    df["price"]
    .rolling(window=3)
    .mean()
)

print(df.head())


import pandas as pd

df = pd.read_csv("data/crypto_prices.csv")

df["moving_average"] = (
    df["price"]
    .rolling(window=3)
    .mean()
)

print(df[["price", "moving_average"]])


initial_investment = 1000
current_value = 1350

roi = (
    (current_value - initial_investment) 
/ initial_investment 
)* 100
print(f"ROI:{roi:.2f}%")