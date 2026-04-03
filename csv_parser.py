import os
import pandas as pd

df=pd.read_csv('basic_items.csv')
df = df[df["Group"] != "Vial"]
df = df[df["Group"] != "Artifact"]
df = df[df["Group"] != "Capsule"]
df = df[~df["Config"].str.contains("Guild")]
df = df[~df["Config"].str.contains("Ticket/Variants/Custom")]
# print(df.head())
ITEM_LIST = set(df['Name'].tolist())
os.remove('items.txt') if os.path.exists('items.txt') else None
with open('items.txt', 'x', encoding='utf-8') as f:
    f.write("[")
    for item in sorted(ITEM_LIST):
        f.write(f"\"{item}\",")
    f.seek(f.tell() - 1)  # Move the file pointer back to overwrite the last comma
    f.write("]")