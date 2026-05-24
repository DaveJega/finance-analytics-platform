from sklearn.linear_model import LinearRegression
import pandas as pd
import numpy as np
x = np.array([1, 2, 3, 4, 5]).reshape(-1, 1)
y = np.array([100, 120, 140, 160, 180])
model = LinearRegression()
model.fit(x, y)
predicted_price = model.predict([[6]])
print(predicted_price)


# ... your existing linear regression code ...
model.fit(x, y)
predicted_price = model.predict([[6]])

# Create a DataFrame to hold the prediction result
# predicted_price[0] extracts the single value from the array
df_pred = pd.DataFrame({"predicted_value": [predicted_price[0]]})

# Save it to your dashboard folder
df_pred.to_csv("dashboard/prediction_result.csv", index=False)
print("Prediction saved successfully!")