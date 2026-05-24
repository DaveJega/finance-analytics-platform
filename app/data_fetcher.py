import requests
import pandas as pd

def get_crypto_data():
    url = "https://api.coingecko.com/api/v3/coins/markets"

    params = {
        "vs_currency": "usd",
        "ids": "bitcoin,ethereum,toncoin,sui",
        "order": "market_cap_desc",
        "per_page": 10,
        "page": 1,
        "sparkline": False
    }

    # FIX: Add a User-Agent header so CoinGecko doesn't block the request
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        
        # FIX: Explicitly throw an exception if the API returns a 403, 429, or 500 error
        response.raise_for_status() 
        
        data = response.json()
        df = pd.DataFrame(data)
        return df

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error occurred: {e}")
        if response.status_code == 429:
            print("Hint: You are being rate-limited by CoinGecko. Wait a minute and try again.")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

if __name__== "__main__":
    crypto_df = get_crypto_data()

    if crypto_df is not None and not crypto_df.empty:
        # Only print selected columns so it fits nicely in your terminal
        print(crypto_df[['id', 'symbol', 'current_price', 'market_cap']])
    else:
        print("Failed to fetch data.")


        crypto_df.to_csv("data/crypto_prices.csv", index=False)
        crypto_df.to_csv("data/crypto_prices.csv", index=False)

    if crypto_df is not None:
     print(crypto_df)

    crypto_df.to_csv("crypto_prices.csv", index=False)

    print("CSV saved successfully!")

else:
    print("Failed to fetch crypto data")