import yfinance as yf
import pandas as pd
stocks = ["AAPL", "TSLA", "MSFT",]
data = yf.download(stocks, period="1mo")
print(data.head())
data.to_csv("data/stock_prices.csv" ,index=True)
print("Stock data saved to stock_prices.csv")