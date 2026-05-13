import os
import asyncio
import gspread
import discord
from discord.ext import commands
from discord.commands import Option
from fastapi import FastAPI
import uvicorn
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
import threading
import time
import pandas as pd
import re
from csv_parser import parse_csv
import logging

# --- Environment Setup ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SHEET_NAME = "Quid Pro Quo Merch Sheet"
SERVER_ID = int(os.getenv("SERVER_ID"))
SALE_LOG_CHANNEL_ID = int(os.getenv("SALE_LOG_CHANNEL_ID"))
TEST_SERVER_ID = int(os.getenv("TEST_SERVER_ID"))
TEST_SALE_LOG_CHANNEL_ID = int(os.getenv("TEST_SALE_LOG_CHANNEL_ID"))
FILENAME = "recent_changes.txt"
test = SHEET_NAME == "QPQ test sheet"
logging.basicConfig(level=logging.ERROR)

# --- Google Sheets Setup ---
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/spreadsheets",
         "https://www.googleapis.com/auth/drive.file",
         "https://www.googleapis.com/auth/drive"]

# creds_dict = ServiceAccountCredentials.from_json_keyfile_name("arched-elixir-471411-e0-0a32c7ac4698.json", scope)
# creds_dict = json.loads(os.getenv("GOOGLE_CREDS_JSON"))

creds = Credentials.from_service_account_file("arched-elixir-471411-e0-0a32c7ac4698.json", scopes=scope)
client_gs = gspread.authorize(creds)

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.messages = True
bot = commands.Bot(intents=intents)
spreadsheet = client_gs.open(SHEET_NAME)
app = FastAPI()

# --- global variables ---
sheet_cache = {}
recent_changes = []

@app.get("/")
async def root():
    return {"status": "ok", "bot": str(bot.user)}

@app.head("/")
async def health_check():
    return {"status": "ok"}

@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")


ITEM_TYPES = ["Gear", "Costumes", "Armor Aura", "Armor Ankle", "Armor Back", "Armor Front Arms", "Armor Rear", "Helm Side", "Helm Back", "Helm Front", "Helm Top Brow", "Misc"]
ITEM_LIST = {}
UV_TYPES = [
    "CTR", "ASI", "Fire", "Shock", "Poison", "Stun",
    "Freeze", "Curse", "Beast", "Slime", "Fiend",
    "Construct", "Gremlin", "Undead", "Elemental", "Piercing", "Shadow"
]
USERNAME_DICT = {
    "carbonjm": ["Carb", 1],
    "ofri868": ["Pyro", 2],
    "watwaba": ["Rex", 3],
    "jimby0117": ["Jimbo", 4],
    "bardly_trying": ["Aru", 5],
    "dabomber.": ["Ori", 6],
    "QPQ": ["QPQ", 7]
}
UV_LEVELS = {
    "CTR_ASI": ["Low", "Med", "High", "Very High"],
    "default": ["Low", "Med", "High", "Max"]
}

# Create a lookup table (dict: UV → position)
order_map = {uv: i for i, uv in enumerate(UV_TYPES)}


def uvs_to_string(uvs):
    if uvs == []:
        return "clean"
    uvs_sorted = sorted(uvs, key=lambda x: order_map[x[0]])
    return " ".join([f"{uv_type} {uv_level}" for uv_type, uv_level in uvs_sorted])

async def uv_level_autocomplete(ctx: discord.AutocompleteContext):
    focused = ctx.focused.name
    uv_type_option = focused.replace("_level", "_type")
    uv_type = ctx.options.get(uv_type_option)

    if uv_type in ("CTR", "ASI"):
        return UV_LEVELS["CTR_ASI"]
    else:
        return UV_LEVELS["default"]

async def item_name_autocomplete(ctx: discord.AutocompleteContext):
    user_input = ctx.value.lower()
    if not user_input:
        return []
    results = []
    for item in ITEM_LIST.keys():
        if user_input in item.lower():
            results.append(item)
            if len(results) >= 25:
                break
    return results

def get_sheet(name):
    now = time.time()

    # If cached — return it
    if name in sheet_cache:
        entry = sheet_cache[name]
        return entry["data"]
    # Load fresh data from Google Sheets
    data = load_sheet_from_google(name)
    # Save to cache
    sheet_cache[name] = {
        "data": data,
        "timestamp": now
    }
    return data

def load_sheet_from_google(sheet_name):
    worksheet = spreadsheet.worksheet(sheet_name)
    last_col = chr(ord("A") + len(USERNAME_DICT) + (3 if sheet_name == "Gear" else 2))
    values = worksheet.get(f"A:{last_col}")

    if not values:
        raise ValueError("Sheet is empty")

    header = values[0]
    rows = values[1:]

    df = pd.DataFrame(rows, columns=header)
    return df

def get_row_number(item_type, name, uvs = None):
    sheet = get_sheet(item_type)
    names = sheet["Item"]
    if item_type == "Gear":
        if uvs is None:
            raise ValueError("UVs must be provided for Gear items.")
        else:
            UVs = sheet["UV"]
            for i, (n, uv) in enumerate(zip(names, UVs), start=1):
                if (name in n) and uv == uvs_to_string(uvs):
                    return i
    else:
        for i, n in enumerate(names, start=1):
            if name in n.strip():
                return i
    return None

def get_item(item_type, name, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level):
    uvs = []
    sheet = get_sheet(item_type)
    item = None
    if item_type == "Gear":
        uv_args = [(uv1_type, uv1_level), (uv2_type, uv2_level), (uv3_type, uv3_level)]
        for uv_type, uv_level in uv_args:
            if uv_type and uv_level:
                uvs.append((uv_type, uv_level))
        item = sheet[(sheet["Item"].str.contains(name, na=False)) & (sheet["UV"] == uvs_to_string(uvs))]
    else:
        item = sheet[sheet["Item"].str.contains(name, na=False)]
    return item

def make_new_row(name, item_type, uvs, amount, price, user_index, local=False):
    offset = 2 if item_type != "Gear" else 3
    sheet = get_sheet(item_type)
    user_col = offset-1 + user_index
    num_users = 7
    row = ["" for _ in range(offset + num_users + 1)]
    row[0] = name
    if item_type == "Gear":
        row[1] = str(uvs) if uvs!=[] else "clean"
    row[user_col] = amount
    row[-1] = price if price else ""
    next_row = len(sheet) + 2
    if not local:
        first_col = chr(ord("A") + offset)
        last_col = chr(ord("A") + offset + num_users - 1)
        row[offset-1] = f"=SUM({first_col}{next_row}:{last_col}{next_row})"
    else:
        row[offset-1] = str(amount)
    return row

def get_name(name, owner):
    if owner:
        for (name, index) in USERNAME_DICT.values():
            if name == owner:
                return owner, index
    else:
        verify_username(name)
        return USERNAME_DICT[name]

def verify_amount(amount):
    if not amount.isdigit() or int(amount) < 1:
        raise ValueError("Amount must be a positive integer.")

def verify_username(username):
    if username not in USERNAME_DICT:
        raise ValueError(f"Unknown username: {username}")

def verify_uvs(uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level):
    if (not uv1_type and uv1_level) or (uv1_type and not uv1_level) or (not uv2_type and uv2_level) or (uv2_type and not uv2_level) or (not uv3_type and uv3_level) or (uv3_type and not uv3_level):
        raise ValueError("If specifying UV levels, UV types must also be specified.")

def get_price(price):
    item_price = re.search(r'\d+', price)
    if item_price:
        return int(item_price.group())
    return -1

def search_item(item_type, name,uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level):
    sheet = get_sheet(item_type)
    results = []
    uvs = []
    if item_type == "Gear":
        uv_args = [(uv1_type, uv1_level), (uv2_type, uv2_level), (uv3_type, uv3_level)]
        for uv_type, uv_level in uv_args:
            if uv_type and uv_level:
                uvs.append((uv_type, uv_level))
    filtered = sheet[sheet["Item"].str.contains(name, case=False, na=False)]
    for i, row in filtered.iterrows():
        if item_type == "Gear":
            if uvs and (row["UV"] != uvs_to_string(uvs)):
                continue
        owners = []
        for name in USERNAME_DICT.values():
            if row[name[0]]:
                owners.append(name[0])
        results.append((row, owners))
    return results

def load_string(default_value=""):
    # If the file doesn't exist, create it with the default value
    if not os.path.exists(FILENAME):
        with open(FILENAME, "w", encoding="utf-8") as f:
            f.write(default_value)
        return default_value
    
    # Otherwise, just read it
    with open(FILENAME, "r", encoding="utf-8") as f:
        return f.read().strip().split("\n")

def save_string(text):
    # 'a' mode appends to the file if it exists or creates it if it doesn't
    with open(FILENAME, "a", encoding="utf-8") as f:
        f.write(text+"\n")

@bot.slash_command(name="additem", description="Add an item to the sheet inventory", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def additem(
    ctx: discord.ApplicationContext,
    name: str = Option(description="Name of the item", required=True, autocomplete=item_name_autocomplete),
    uv1_type: str = Option(description="UV1 type", choices=UV_TYPES, required=False),
    uv1_level: str = Option(description="UV1 level", required=False, autocomplete=uv_level_autocomplete),
    uv2_type: str = Option(description="UV2 type", choices=UV_TYPES, required=False),
    uv2_level: str = Option(description="UV2 level", required=False, autocomplete=uv_level_autocomplete),
    uv3_type: str = Option(description="UV3 type", choices=UV_TYPES, required=False),
    uv3_level: str = Option(description="UV3 level", required=False, autocomplete=uv_level_autocomplete),
    amount: int = Option(default=1, description="Amount of items", required=False),
    price: int = Option(default=None, description="Price of the item", required=False),
    owner: str = Option(default=None, description="Specify a different user to add the item to", required=False, choices=list(map(lambda x: x[0], USERNAME_DICT.values())))
):
    try:
        verify_amount(str(amount))
        verify_username(ctx.author.name)
        verify_uvs(uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level)
        if price:
            item_price = get_price(price)
            if item_price < 0:
                raise ValueError("Price must be a non-negative integer.")
    except ValueError as e:
        await ctx.respond(str(e), ephemeral=True)
        return
    await ctx.defer(ephemeral=True)
    try:
        result = await asyncio.wait_for(process_add_item(ctx, name, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level, amount, price, owner), timeout=60)
        if result['status'] == 'success':
            channel = bot.get_channel(SALE_LOG_CHANNEL_ID)
            await channel.send(result['message'])
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")
    except Exception as e:
        await ctx.followup.send(f"An error occurred: {str(e)}")
async def process_add_item(ctx, name, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level, amount, price, owner=None):
    username, user_index = get_name(ctx.author.name, owner)
    item_type = ITEM_LIST[name]
    uvs = []
    if item_type == "Gear": 
        uv_args = [(uv1_type, uv1_level), (uv2_type, uv2_level), (uv3_type, uv3_level)]
        for uv_type, uv_level in uv_args:
            if uv_type and uv_level:
                uvs.append((uv_type, uv_level))
    try:
        sheet = spreadsheet.worksheet(item_type)
    except gspread.SpreadsheetNotFound:
        await ctx.respond(f"Spreadsheet '{SHEET_NAME}' not found.")
        return {'status': 'error', 'message': f"Spreadsheet '{SHEET_NAME}' not found."}
    except gspread.WorksheetNotFound:
        await ctx.respond(f"Worksheet for item type '{item_type}' not found.")
        return {'status': 'error', 'message': f"Worksheet for item type '{item_type}' not found."}
    row = get_item(item_type, name, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level)
    offset = 2 if item_type != "Gear" else 3
    if not row.empty:
        current_value = row[username].values[0]
        current_amount = int(current_value) if current_value  else 0
        sheet.update_cell(int(row.index[0]+2), offset + user_index, current_amount + int(amount))
        cached_sheet = get_sheet(item_type)
        cached_sheet.at[int(row.index[0]), username] = str(current_amount + int(amount))
    else:
        sheet.append_row(make_new_row(name, item_type, uvs_to_string(uvs), amount, price, user_index, local=False), value_input_option="USER_ENTERED", table_range='A1')
        cached_sheet = get_sheet(item_type)
        new_row = make_new_row(name, item_type, uvs_to_string(uvs), amount, price, user_index, local=True)
        cached_sheet.loc[len(cached_sheet)] = new_row
        if not test:
            recent_changes.append(f"Added item: {name}, Type: {item_type}{', UVs: ' + uvs_to_string(uvs) if item_type == 'Gear' else ''}, Price: {price or 'N/A'}, Added to: {username}")
            save_string(f"Added item: {name}, Type: {item_type}{', UVs: ' + uvs_to_string(uvs) if item_type == 'Gear' else ''}, Price: {price or 'N/A'}, Added to: {username}")
    parts = [f"Added item: {name}"]
    if item_type == "Gear":
        parts.append(f"UVs: {uvs_to_string(uvs)}")
    parts.append(f"- Amount: {amount}")
    parts.append(f"- Price: {price or 'N/A'}")
    parts.append(f"- Added to: {username}")
    if test:
        parts.append(f"- Note: This action was performed in the test sheet.")
    msg = "\n".join(parts)
    await ctx.followup.send("Item added successfully!")
    return {'status': 'success', 'message': msg}

@bot.slash_command(name="removeitem", description="Remove an item from the sheet inventory", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def removeitem(
    ctx: discord.ApplicationContext,
    name: str =  Option(description="Name of the item", required=True, autocomplete=item_name_autocomplete),
    uv1_type: str = Option(description="UV1 type", choices=UV_TYPES, required=False),
    uv1_level: str = Option(description="UV1 level", required=False, autocomplete=uv_level_autocomplete),
    uv2_type: str = Option(description="UV2 type", choices=UV_TYPES, required=False),
    uv2_level: str = Option(description="UV2 level", required=False, autocomplete=uv_level_autocomplete),
    uv3_type: str = Option(description="UV3 type", choices=UV_TYPES, required=False),
    uv3_level: str = Option(description="UV3 level", required=False, autocomplete=uv_level_autocomplete),
    amount: int = Option(default=1, description="Amount of items", required=False),
    owner: str = Option(default=None, description="Specify a different user to add the item to", required=False, choices=list(map(lambda x: x[0], USERNAME_DICT.values()))),
    price: str = Option(default=None, description="Final sale price", required=False)
):
    try:
        verify_amount(str(amount))
        verify_username(ctx.author.name)
        verify_uvs(uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level)
        if price:
            item_price = get_price(price)
            if item_price < 0:
                raise ValueError("Price must be a non-negative integer.")
    except ValueError as e:
        await ctx.respond(str(e), ephemeral=True)
        return
    await ctx.defer(ephemeral = True)
    try:
        result = await asyncio.wait_for(process_remove_item(ctx, name, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level, int(amount), owner, price), timeout=60)
        if result['status'] == 'success':
            channel = bot.get_channel(SALE_LOG_CHANNEL_ID)
            await channel.send(result['message'])
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")
    except Exception as e:
        await ctx.followup.send(f"An error occurred: {str(e)}")
async def process_remove_item(ctx, name, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level, amount, owner, price=None):
    username, user_index = get_name(ctx.author.name, owner)
    uvs = []
    item_type = ITEM_LIST[name]
    if item_type == "Gear":
        uv_args = [(uv1_type, uv1_level), (uv2_type, uv2_level), (uv3_type, uv3_level)]
        for uv_type, uv_level in uv_args:
            if uv_type and uv_level:
                uvs.append((uv_type, uv_level))
    try:
        sheet = spreadsheet.worksheet(item_type)
    except gspread.SpreadsheetNotFound:
        await ctx.respond(f"Spreadsheet '{SHEET_NAME}' not found.")
        return {'status': 'error', 'message': f"Spreadsheet '{SHEET_NAME}' not found."}
    except gspread.WorksheetNotFound:
        await ctx.respond(f"Worksheet for item type '{item_type}' not found.")
        return {'status': 'error', 'message': f"Worksheet for item type '{item_type}' not found."}
    row = get_item(item_type, name, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level)
    offset = 2 if item_type != "Gear" else 3
    if not row.empty:
        current_value = row[username].values[0]
        current_amount = int(current_value) if current_value else 0
        if current_amount < amount:
            await ctx.respond(f"Cannot remove {amount} {name} from {username}. Current amount is {current_amount}.")
            return {'status': 'error', 'message': f"Cannot remove {amount} {name} from {username}. Current amount is {current_amount}."}
        sheet.update_cell(int(row.index[0])+2, offset + user_index, current_amount - amount if current_amount - amount > 0 else "")
        cached_sheet = get_sheet(item_type)
        cached_sheet.at[int(row.index[0]), username] = str(current_amount - amount) if current_amount - amount > 0 else ""
        if(int(row["Quantity"].values[0]) - amount == 0):
            sheet.delete_rows(int(row.index[0])+2)
            cached_sheet.drop(index=int(row.index[0]), inplace=True)
            if not test:
                recent_changes.append(f"Removed item: {name}, Type: {item_type}{', UVs: ' + uvs_to_string(uvs) if item_type == 'Gear' else ''}, Removed from: {username}")
                save_string(f"Removed item: {name}, Type: {item_type}{', UVs: ' + uvs_to_string(uvs) if item_type == 'Gear' else ''}, Removed from: {username}")
    else:
        await ctx.respond(f"Item '{name}' not found in inventory.")
        return {'status': 'error', 'message': f"Item '{name}' not found in inventory."}
    parts = [f"Removed item: {name}"]
    if item_type == "Gear":
        parts.append(f"UVs: {uvs_to_string(uvs)}")
    parts.append(f"- Amount: {amount}")
    parts.append(f"- Removed from: {username}")
    if test:
        parts.append(f"- Note: This action was performed in the test sheet.")
    if price:
        parts.append(f"- Final sale price: {price}")
    msg = "\n".join(parts)
    await ctx.followup.send("Item removed successfully!")
    return {'status': 'success', 'message': msg}

@bot.slash_command(name="switchsheet", description="Switch to a different sheet", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def switchsheet(
    ctx: discord.ApplicationContext,
    sheet_name: str = Option(description="Name of the new sheet", required=True, choices=["QPQ test sheet", "Quid Pro Quo Merch Sheet"])
):
    await ctx.defer(ephemeral = True)
    try:
        await asyncio.wait_for(process_switch_sheet(ctx, sheet_name), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")
async def process_switch_sheet(ctx, sheet_name):
    global SALE_LOG_CHANNEL_ID
    SHEET_NAME = sheet_name
    global test, spreadsheet
    spreadsheet = client_gs.open(SHEET_NAME)
    test = SHEET_NAME == "QPQ test sheet"
    if test:
        SALE_LOG_CHANNEL_ID = TEST_SALE_LOG_CHANNEL_ID
    else:
        SALE_LOG_CHANNEL_ID = int(os.getenv("SALE_LOG_CHANNEL_ID"))
    await ctx.followup.send(f"Switched to sheet: {SHEET_NAME}")
    return   

@bot.slash_command(name="recap", description="Get a recap of all new or removed items", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def recap(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral = True)
    try:
        await asyncio.wait_for(process_recap(ctx), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")
async def process_recap(ctx):
    if not recent_changes:
        await ctx.respond("No recent changes.")
        return
    parts = ["Recent Changes:\n"]
    for change in recent_changes:
        parts.append(change)
    msg = "\n".join(parts)
    await ctx.respond(msg)

@bot.slash_command(name="generatenode", description="Generates a txt for the forum node", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def generate_node(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral = True)
    try:
        await asyncio.wait_for(process_generate_node(ctx), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")
async def process_generate_node(ctx):
    with open("node.txt", "w+", encoding="utf-8") as f:
        for sheet in sheet_cache.keys():
            if(sheet == "Armor Aura"):
                f.write("\n<strong>Accessories:</strong>\n")
            f.write(f"\n<strong>{sheet}:</strong>\n")
            data = get_sheet(sheet)
            for i, row in data.iterrows():
                item_str = f"• {row['Item']}"
                if not row['Item'] or "*" in item_str or item_str.isspace():
                    continue
                if sheet == "Gear":
                    item_str += f" {row['UV']}" if row['UV'] and row['UV'] != "clean" else ""
                price = re.search(r'\d+(?:\.\d+)?(?:e|ke|cr|kcr)', str(row['Price'])) if len(str(row['Price'])) > 0 else ""
                price = price[0] if price else ""
                item_str += f" - {price}" if price != "" else ""
                f.write(item_str + "\n")
    await ctx.followup.send(content="Node generated", file=discord.File("node.txt"))

@bot.slash_command(name="clearrecap", description="clear all items in recap", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def clear_recap(
    ctx: discord.ApplicationContext
):
    await ctx.defer(ephemeral = True)
    try:
        await asyncio.wait_for(process_clear_recap(ctx), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")
async def process_clear_recap(ctx):
    global recent_changes
    recent_changes = []
    with open (FILENAME, "w", encoding="utf-8") as f:
        f.write("")
    await ctx.followup.send(f"Recent changes cleared.")
    return

@bot.slash_command(name="search", description="Search an item or by keyword in the sheet inventory", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def search(
    ctx: discord.ApplicationContext,
    name: str =  Option(description="Name of the item", required=True, autocomplete=item_name_autocomplete),
    item_type: str = Option(description="Choose the item type", choices=ITEM_TYPES, required=False, default=None),
    uv1_type: str = Option(description="UV1 type", choices=UV_TYPES, required=False),
    uv1_level: str = Option(description="UV1 level", required=False, autocomplete=uv_level_autocomplete),
    uv2_type: str = Option(description="UV2 type", choices=UV_TYPES, required=False),
    uv2_level: str = Option(description="UV2 level", required=False, autocomplete=uv_level_autocomplete),
    uv3_type: str = Option(description="UV3 type", choices=UV_TYPES, required=False),
    uv3_level: str = Option(description="UV3 level", required=False, autocomplete=uv_level_autocomplete),
):
    await ctx.defer(ephemeral = True)
    try:
        await asyncio.wait_for(process_search(ctx, name, item_type, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level), timeout=600)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")
    except Exception as e:
        await ctx.followup.send(f"An error occurred: {str(e)}")
async def process_search(ctx, name, item_type, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level):
    if item_type is None:
        parts = [f"Search results for {name}:"]
        for itype in ITEM_TYPES:
            try:
                results = search_item(itype, name, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level)
                if results:
                    for (item, owners) in results:
                        item_found = [f"{item['Item']},{'' if itype != 'Gear' else ' ' + item['UV']}"]
                        item_found.append("owned by:")
                        for owner in owners:
                            item_found.append(f"{owner},")
                        item_found.append(f"Price: {item['Price'] if item['Price'] else 'N/A'}")
                        item_string = " ".join(item_found)
                        if len("\n".join(parts)) + len(item_string) > 2000:
                            await ctx.followup.send("\n".join(parts), ephemeral=True)
                            parts = []
                        parts.append(item_string)
            except gspread.WorksheetNotFound:
                continue
        if len(parts) == 1:
            await ctx.followup.send(f"No results found for {name} in inventory.")
            return
        if test:
            parts.append(f"- Note: This action was performed in the test sheet.")
        msg = "\n".join(parts)
        await ctx.followup.send(msg, ephemeral=True)
        return
    else:
        try:
            results = search_item(item_type, name, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level)
            if results:
                parts = [f"Search results for {name}:"]
                for (item, owners) in results:
                    item_found = [f"{item['Item']},{'' if item_type != 'Gear' else ' ' + item['UV']}"]
                    item_found.append("owned by:")
                    for owner in owners:
                        item_found.append(f"{owner},")
                    item_found.append(f"Price: {item['Price'] if item['Price'] else 'N/A'}")
                    item_string = " ".join(item_found)
                    if len("\n".join(parts)) + len(item_string) > 2000:
                        await ctx.followup.send("\n".join(parts), ephemeral=True)
                        parts = []
                    parts.append(item_string)
                if test:
                    parts.append(f"- Note: This action was performed in the test sheet.")
                msg = "\n".join(parts)
                await ctx.followup.send(msg, ephemeral=True)
                return
            else:
                await ctx.followup.send(f"No results found for {name} in inventory.")
                return
        except gspread.WorksheetNotFound:
            await ctx.followup.send(f"Worksheet for item type '{item_type}' not found.")
            return

@bot.slash_command(name="itemlist", description="Get a player's list of all items in the inventory", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def item_list(
    ctx: discord.ApplicationContext,
    owner: str = Option(description="Specify a user to get their item list", required=False, choices=list(map(lambda x: x[0], USERNAME_DICT.values())))
):
    await ctx.defer(ephemeral = True)
    try:
        await asyncio.wait_for(process_item_list(ctx, owner), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.", ephemeral=True)
    except Exception as e:
        logging.error("An error occurred during calculation", exc_info=True)
        await ctx.followup.send(f"An error occurred: {str(e)}", ephemeral=True)
async def process_item_list(ctx, owner):
    username, user_index = get_name(ctx.author.name, owner)
    line_count = 0
    with open("item_list_response.txt", 'w+', encoding="utf-8") as f:
        f.write(f"Inventory for {username}:")
        for item_type in ITEM_TYPES:
            try:
                sheet = get_sheet(item_type)
                owned_items = sheet[sheet[username].notna() & sheet[username] > 0]
                if not owned_items.empty:
                    f.write(f"\n\n{item_type}:")
                    for i, row in owned_items.iterrows():
                        item_str = f"{row['Item']}"
                        if item_type == "Gear":
                            item_str += f" {row['UV']}" if row['UV'] and row['UV'] != "clean" else ""
                        price = re.search(r'\d+(?:\.\d+)?(?:e|ke|cr|kcr)', str(row['Price'])) if len(str(row['Price'])) > 0 else ""
                        price = price[0] if price else ""
                        item_str += f" - {price}" if price != "" else ""
                        f.write("\n" + item_str)
            except gspread.WorksheetNotFound:
                continue
        line_count = sum(1 for _ in f)
    if line_count == 2:
        await ctx.followup.send(f"{username} has no items in inventory.", ephemeral=True)
        return
    msg = "item list generated"
    if test:
        msg += f"\n- Note: This action was performed in the test sheet."
    await ctx.followup.send(content=msg, file=discord.File("item_list_response.txt"))

@bot.slash_command(name="addprice", description="Add or update the price of an item in the sheet inventory", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def add_price(
    ctx: discord.ApplicationContext,
    name: str =  Option(description="Name of the item", required=True, autocomplete=item_name_autocomplete),
    item_type: str = Option(description="Choose the item type", choices=ITEM_TYPES),
    price: int = Option(description="Price of the item", required=True),
    uv1_type: str = Option(description="UV1 type", choices=UV_TYPES, required=False),
    uv1_level: str = Option(description="UV1 level", required=False, autocomplete=uv_level_autocomplete),
    uv2_type: str = Option(description="UV2 type", choices=UV_TYPES, required=False),
    uv2_level: str = Option(description="UV2 level", required=False, autocomplete=uv_level_autocomplete),
    uv3_type: str = Option(description="UV3 type", choices=UV_TYPES, required=False),
    uv3_level: str = Option(description="UV3 level", required=False, autocomplete=uv_level_autocomplete)
):
    try:
        verify_username(ctx.author.name)
        verify_uvs(uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level)
        item_price = get_price(price)
        if item_price < 0:
            raise ValueError("Price must be a non-negative integer.")
    except ValueError as e:
        await ctx.respond(str(e))
        return
    await ctx.defer(ephemeral = True)
    try:
        await asyncio.wait_for(process_add_price(ctx, name, item_type, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level, price), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")
    except Exception as e:
        await ctx.followup.send(f"An error occurred: {str(e)}")
async def process_add_price(ctx, name, item_type, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level, price):
    offset = 2 if item_type != "Gear" else 3
    uvs = []
    if item_type == "Gear":
        uv_args = [(uv1_type, uv1_level), (uv2_type, uv2_level), (uv3_type, uv3_level)]
        for uv_type, uv_level in uv_args:
            if uv_type and uv_level:
                uvs.append((uv_type, uv_level))
    try:
        sheet = get_sheet(item_type)
    except gspread.SpreadsheetNotFound:
        await ctx.respond(f"Spreadsheet '{SHEET_NAME}' not found.")
        return
    except gspread.WorksheetNotFound:
        await ctx.respond(f"Worksheet for item type '{item_type}' not found.")
        return
    row = get_item(item_type, name, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level)
    if not row.empty:
        sheet.loc[row.index[0], "Price"] = str(price)
        google_sheet = spreadsheet.worksheet(item_type)
        google_sheet.update_cell(int(row.index[0]+2), offset+8, price)
        if not test:
            recent_changes.append(f"Updated price for item: {name}, Type: {item_type}{', UVs: ' + uvs_to_string(uvs) if item_type == 'Gear' else ''}, New Price: {price}")
    else:
        await ctx.respond(f"Item '{name}' not found in inventory.")
        return
    parts = [f"Updated price for item: {name}"]
    if item_type == "Gear":
        parts.append(f"UVs: {uvs_to_string(uvs)}")
    parts.append(f"- New Price: {price}")
    if test:
        parts.append(f"- Note: This action was performed in the test sheet.")
    msg = "\n".join(parts)
    await ctx.respond(msg)

@bot.slash_command(name="help", description="Get help about the bot commands", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def help_command(ctx: discord.ApplicationContext):
    help_text = (
        "Available Commands:\n"
        "/additem - Add an item to the sheet inventory.\n"
        "/removeitem - Remove an item from the sheet inventory.\n"
        "/switchsheet - Switch to a different sheet.\n"
        "/recap - Get a recap of all new or removed items.\n"
        "/clearrecap - Clear all items in the recap.\n"
        "/search - Search an item or by keyword in the sheet inventory.\n"
        "/addprice - Add or update the price of an item in the sheet inventory.\n"
    )
    await ctx.respond(help_text)

def run_web():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def refresh_cache():
    while True:
        time.sleep(3600)  # Sleep for 1 hour
        sheet_cache.clear()
        for item_type in ITEM_TYPES:
            load_sheet_from_google(item_type)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=refresh_cache, daemon=True).start()
    recent_changes = load_string()
    ITEM_LIST = parse_csv()
    bot.run(DISCORD_TOKEN)
