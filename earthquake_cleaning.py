import numpy as np
import pandas as pd

Earthquake_raw = pd.read_csv('data/07earthquake.csv')

earthquake = Earthquake_raw.copy()

print(earthquake.shape)
print()

print(earthquake.head())
print()

earthquake.info()
print()

print(earthquake.describe())
print()

print(earthquake.isnull().sum())
print()

negative_depth = earthquake["Depth"] < 0
print(negative_depth.sum())
print()

print(earthquake.loc[negative_depth, ["Date", "Type", "Depth", "Magnitude"]])
print()

print(earthquake.groupby("Type")["Magnitude"].count())
print()

earthquake_only = earthquake.loc[earthquake["Type"] == "Earthquake"].copy()
print(earthquake_only.shape)
print(earthquake_only)
print()

False_Date = []
for i in earthquake_only["Date"]:
    if len(i) != 10:
        False_Date.append(i)
print(len(False_Date))
print(False_Date)
print()

for idx in earthquake_only.index:
    date = earthquake_only.loc[idx, "Date"]
    if len(date) != 10:
        new_date = date[5:7] + "/" + date[8:10]+ "/" + date[0:4]
        earthquake_only.loc[idx, "Date"] = new_date
        print(earthquake_only.loc[idx, ["Date", "Time", "Latitude", "Longitude", "Type", "Depth", "Magnitude"]])
