import os
import re
import pandas as pd

df=pd.read_csv('basic_items.csv')
df = df[df["Group"] != "Vial"]
df = df[df["Group"] != "Artifact"]
df = df[df["Group"] != "Capsule"]
df = df[df["Group"] != "Token"]
df = df[~df["Config"].str.contains("/Guild/")]
df = df[~df["Config"].str.contains("Harness")]
df = df[~df["Config"].str.contains("Ticket/Variants/Custom")]
df = df[~df["Config"].str.contains("Furni/Trophy/Boss Trophy")]
df = df[~df["Config"].str.contains("Game Master")]
# print(df.head())
os.remove('items.txt') if os.path.exists('items.txt') else None
with open('items.txt', 'x', encoding='utf-8') as f:
    f.write("[")
    for index, row in df.iterrows():
        if re.match(r'^Weapon|^Gear', row['Config']):
            f.write("{"+f"\"{row['Name']}\": \"Gear\""+"},")
        elif re.match(r'^Costume', row['Config']):
            f.write("{"+f"\"{row['Name']}\": \"Costumes\""+"},")
        elif re.match(r'^Accessory/Armor/Aura', row['Config']):
            f.write("{"+f"\"{row['Name']}\": \"Armor Aura\""+"},")
        elif re.match(r'^Accessory/Armor/Back', row['Config']):
            if re.search(r'.Tail.|.tail.|.Extension Cord.', row['Config'], re.IGNORECASE):
                f.write("{"+f"\"{row['Name']}\": \"Armor Rear\""+"},")
            elif re.search(r'.Ankle.|.Slippers.|.Trotters.', row['Config'], re.IGNORECASE):
                f.write("{"+f"\"{row['Name']}\": \"Armor Ankle\""+"},")
            else:
                f.write("{"+f"\"{row['Name']}\": \"Armor Back\""+"},")
        elif re.match(r'^Accessory/Armor/Front', row['Config']):
            f.write("{"+f"\"{row['Name']}\": \"Armor Front Arms\""+"},")
        elif re.match(r'^Accessory/Helm/Back', row['Config']):
            f.write("{"+f"\"{row['Name']}\": \"Helm Back\""+"},")
        elif re.match(r'^Accessory/Helm/Front', row['Config']):
            f.write("{"+f"\"{row['Name']}\": \"Helm Front\""+"},")
        elif re.match(r'^Accessory/Helm/Side', row['Config']):
            f.write("{"+f"\"{row['Name']}\": \"Helm Side\""+"},")
        elif re.match(r'^Accessory/Helm/Top', row['Config']):
            f.write("{"+f"\"{row['Name']}\": \"Helm Top Brow\""+"},")
        else:
            f.write("{"+f"\"{row['Name']}\": \"Misc\""+"},")
    f.seek(f.tell() - 1)  # Move the file pointer back to overwrite the last comma
    f.write("]")
def parse_csv():
    with open('items.txt', 'r', encoding='utf-8') as f:
        items = {}
        for index, row in df.iterrows():
            if re.match(r'^Weapon|^Gear', row['Config']):
                items[row['Name']] = 'Gear'
            elif re.match(r'^Costume', row['Config']):
                items[row['Name']] = 'Costumes'
            elif re.match(r'^Accessory/Armor/Aura', row['Config']):
                items[row['Name']] = 'Armor Aura'
            elif re.match(r'^Accessory/Armor/Back', row['Config']):
                if re.search(r'.Tail.|.tail.|.Extension Cord.', row['Config'], re.IGNORECASE):
                    items[row['Name']] = 'Armor Rear'
                elif re.search(r'.Ankle.|.Slippers.|.Trotters.', row['Config'], re.IGNORECASE):
                    items[row['Name']] = 'Armor Ankle'
                else:
                    items[row['Name']] = 'Armor Back'
            elif re.match(r'^Accessory/Armor/Front', row['Config']):
                items[row['Name']] = 'Armor Front Arms'
            elif re.match(r'^Accessory/Helm/Back', row['Config']):
                items[row['Name']] = 'Helm Back'
            elif re.match(r'^Accessory/Helm/Front', row['Config']):
                items[row['Name']] = 'Helm Front'
            elif re.match(r'^Accessory/Helm/Side', row['Config']):
                items[row['Name']] = 'Helm Side'
            elif re.match(r'^Accessory/Helm/Top', row['Config']):
                items[row['Name']] = 'Helm Top Brow'
            else:
                items[row['Name']] = 'Misc'
        return items