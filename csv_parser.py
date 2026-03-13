import pandas as pd

df=pd.read_csv('basic_items.csv')
print(df.head())
ITEM_LIST = set(df['Name'].tolist())
with open('items.txt', 'x', encoding='utf-8') as f:
    f.write("[")
    for item in sorted(ITEM_LIST):
        f.write(f"\"{item}\",")
    f.seek(f.tell() - 1)  # Move the file pointer back to overwrite the last comma
    f.write("]")