import pandas as pd
from sqlalchemy import create_engine

engine = create_engine(
    "postgresql://postgres:08028408880@localhost:5432/finance_platform"
)

df = pd.read_csv("data/crypto_prices.csv")

df.to_sql(
    "crypto_prices",
    engine,
    if_exists="replace",
    index=False
)

print("Data Saved")


import pandas as pd
from sqlalchemy import create_engine

engine = create_engine(
    "postgresql://postgres:08028408880@localhost:5432/finance_platform"
)

df = pd.read_csv("data/stock_prices.csv")

df.to_sql(
    "stock_prices",
    engine,
    if_exists="replace",
    index=False
)

print("Data Saved")


