import asyncio
from random import choices
import gspread
import discord
from discord.ext import commands
from discord.commands import Option
from fastapi import FastAPI
import gspread
import uvicorn
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import requests, time, os, threading

# --- Environment Setup ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SHEET_NAME = os.getenv("SHEET_NAME")
SERVER_ID = int(os.getenv("SERVER_ID"))
TEST_SERVER_ID = int(os.getenv("TEST_SERVER_ID"))
test = SHEET_NAME == "QPQ test sheet"
recent_changes = []

# --- Google Sheets Setup ---
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/spreadsheets",
         "https://www.googleapis.com/auth/drive.file",
         "https://www.googleapis.com/auth/drive"]

creds = ServiceAccountCredentials.from_json_keyfile_name("arched-elixir-471411-e0-0a32c7ac4698.json", scope)
client_gs = gspread.authorize(creds)

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)
spreadsheet = client_gs.open(SHEET_NAME)
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok", "bot": str(bot.user)}

@app.head("/")
async def health_check():
    return {"status": "ok"}

@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")


ITEM_TYPES = ["Gear", "Costumes", "Armor Aura", "Armor Ankle", "Armor Front", "Helm Side", "Helm Back", "Helm Front", "Helm Top", "Misc"]

UV_TYPES = [
    "CTR", "ASI", "Fire", "Shock", "Poison", "Stun",
    "Freeze", "Curse", "Beast", "Slime", "Fiend",
    "Construct", "Gremlin", "Undead"
]
USERNAME_DICT = {
    "carbonjm": ["Carb", 1],
    "ofri868": ["Pyro", 2],
    "watwaba": ["Rex", 3],
    "jimby0117": ["Jimbo", 4],
    "bardly_trying": ["Aru", 5],
    "dabomber.": ["Ori", 6]
}

UV_LEVELS = {
    "CTR": ["Low", "Medium", "High", "Very High"],
    "ASI": ["Low", "Medium", "High", "Very High"],
    "default": ["Low", "Medium", "High", "Max"]
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
        return ["Low", "Medium", "High", "Very High"]
    else:
        return ["Low", "Medium", "High", "Max"]

def get_row_number(item_type, name, uvs = None):
    sheet = spreadsheet.worksheet(item_type)
    names = sheet.col_values(1)
    if item_type == "Gear":
        if uvs is None:
            raise ValueError("UVs must be provided for Gear items.")
        else:

            UVs = sheet.col_values(2)
            for i, (n, uv) in enumerate(zip(names, UVs), start=1):
                if n == name and uv == uvs_to_string(uvs):
                    return i
    else:
        for i, n in enumerate(names, start=1):
            if n == name:
                return i
    return None

def make_new_row(name, item_type, uvs, amount, price, username):
    offset = 2 if item_type != "Gear" else 3
    _, user_index = USERNAME_DICT[username]
    sheet = spreadsheet.worksheet(item_type)
    user_col = offset-1 + user_index
    num_users = 7
    row = ["" for _ in range(offset + num_users + 1)]
    row[0] = name
    if item_type == "Gear":
        row[1] = str(uvs) if uvs!=[] else "clean"
    row[user_col] = amount
    row[-1] = price if price else ""
    next_row = len(sheet.get_all_values()) + 1
    first_col = chr(ord("A") + offset)
    last_col = chr(ord("A") + offset + num_users - 1)
    row[offset-1] = f"=SUM({first_col}{next_row}:{last_col}{next_row})"
    return row

def verify_amount(amount):
    if not amount.isdigit() or int(amount) < 1:
        raise ValueError("Amount must be a positive integer.")

def verify_username(username):
    if username not in USERNAME_DICT:
        raise ValueError(f"Unknown username: {username}")

def verify_uvs(uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level):
    if (not uv1_type and uv1_level) or (not uv2_type and uv2_level) or (not uv3_type and uv3_level):
        raise ValueError("If specifying UV levels, UV types must also be specified.")



@bot.slash_command(name="additem", description="Add an item to the sheet inventory", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def additem(
    ctx: discord.ApplicationContext,
    name: str,
    item_type: str = Option(description="Choose the item type", choices=ITEM_TYPES),
    uv1_type: str = Option(description="UV1 type", choices=UV_TYPES, required=False),
    uv1_level: str = Option(description="UV1 level", required=False, autocomplete=uv_level_autocomplete),
    uv2_type: str = Option(description="UV2 type", choices=UV_TYPES, required=False),
    uv2_level: str = Option(description="UV2 level", required=False, autocomplete=uv_level_autocomplete),
    uv3_type: str = Option(description="UV3 type", choices=UV_TYPES, required=False),
    uv3_level: str = Option(description="UV3 level", required=False, autocomplete=uv_level_autocomplete),
    amount: int = Option(default=1, description="Amount of items", required=False),
    price: int = Option(default=None, description="Price of the item", required=False),
    qpq_purchase: bool = Option(default=False, description="Was this a QPQ purchase?", required=False)
):
    try:
        verify_amount(str(amount))
        verify_username(ctx.author.name)
        verify_uvs(uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level)
    except ValueError as e:
        await ctx.respond(str(e))
        return
    await ctx.defer()
    try:
        await asyncio.wait_for(process_add_item(ctx, name, item_type, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level, amount, price, qpq_purchase), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")
    except Exception as e:
        await ctx.followup.send(f"An error occurred: {str(e)}")
    
async def process_add_item(ctx, name, item_type, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level, amount, price, qpq_purchase):
    username = "QPQ" if qpq_purchase else ctx.author.name
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
        return
    except gspread.WorksheetNotFound:
        await ctx.respond(f"Worksheet for item type '{item_type}' not found.")
        return
    row = get_row_number(item_type, name, uvs)
    offset = 2 if item_type != "Gear" else 3
    user_column, user_index = USERNAME_DICT[username]
    user_col = offset + user_index
    if row:
        current_value = sheet.cell(row, user_col).value
        current_amount = int(current_value) if current_value and current_value.isdigit() else 0
        sheet.update_cell(row, offset + user_index, current_amount + amount)
    else:
        sheet.append_row(make_new_row(name, item_type, uvs_to_string(uvs), amount, price, username), value_input_option="USER_ENTERED")
        recent_changes.append(f"Added item: {name}, Type: {item_type}, UVs: {uvs_to_string(uvs)}, Amount: {amount}, Price: {price or 'N/A'}, Added to: {user_column}{' (QPQ Purchase)' if qpq_purchase else ''}")
    parts = [f"Added item: {name}"]
    if item_type == "Gear":
        parts.append(f"UVs: {uvs_to_string(uvs)}")
    parts.append(f"Amount: {amount}")
    parts.append(f"- Price: {price or 'N/A'}")
    parts.append(f"- Added to: {user_column}")
    if test:
        parts.append(f"- Note: This action was performed in the test sheet.")
    msg = "\n".join(parts)
    await ctx.respond(msg)

@bot.slash_command(name="removeitem", description="Remove an item from the sheet inventory", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def removeitem(
    ctx: discord.ApplicationContext,
    name: str,
    item_type: str = Option(description="Choose the item type", choices=ITEM_TYPES),
    uv1_type: str = Option(description="UV1 type", choices=UV_TYPES, required=False),
    uv1_level: str = Option(description="UV1 level", required=False, autocomplete=uv_level_autocomplete),
    uv2_type: str = Option(description="UV2 type", choices=UV_TYPES, required=False),
    uv2_level: str = Option(description="UV2 level", required=False, autocomplete=uv_level_autocomplete),
    uv3_type: str = Option(description="UV3 type", choices=UV_TYPES, required=False),
    uv3_level: str = Option(description="UV3 level", required=False, autocomplete=uv_level_autocomplete),
    amount: int = Option(default=1, description="Amount of items", required=False),
    qpq_sale: bool = Option(default=False, description="Was this a QPQ sale?", required=False)
):
    try:
        verify_amount(str(amount))
        verify_username(ctx.author.name)
        verify_uvs(uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level)
    except ValueError as e:
        await ctx.respond(str(e))
        return
    await ctx.defer()
    try:
        await asyncio.wait_for(process_remove_item(ctx, name, item_type, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level, int(amount), qpq_sale), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")
    except Exception as e:
        await ctx.followup.send(f"An error occurred: {str(e)}")
    
async def process_remove_item(ctx, name, item_type, uv1_type, uv1_level, uv2_type, uv2_level, uv3_type, uv3_level, amount, qpq_sale):
    username = "QPQ" if qpq_sale else ctx.author.name
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
        return
    except gspread.WorksheetNotFound:
        await ctx.respond(f"Worksheet for item type '{item_type}' not found.")
        return
    row = get_row_number(item_type, name, uvs)
    offset = 2 if item_type != "Gear" else 3
    user_column, user_index = USERNAME_DICT[username]
    user_col = offset + user_index
    if row:
        current_value = sheet.cell(row, user_col).value
        current_amount = int(current_value) if current_value and current_value.isdigit() else 0
        if current_amount < amount:
            await ctx.respond(f"Cannot remove {amount} {name} from {user_column}. Current amount is {current_amount}.")
            return
        sheet.update_cell(row, offset + user_index, current_amount - amount if current_amount - amount > 0 else "")
        if(sheet.cell(row, offset).value == "0"):
            recent_changes.append(f"Removed item: {name}, Type: {item_type}, UVs: {uvs_to_string(uvs)}, Amount: {amount}, Removed from: {user_column}{' (QPQ Sale)' if qpq_sale else ''}")
    else:
        await ctx.respond(f"Item '{name}' not found in inventory.")
        return
    parts = [f"Removed item: {name}"]
    if item_type == "Gear":
        parts.append(f"UVs: {uvs_to_string(uvs)}")
    parts.append(f"Amount: {amount}")
    parts.append(f"- Removed from: {user_column}")
    if test:
        parts.append(f"- Note: This action was performed in the test sheet.")
    msg = "\n".join(parts)
    await ctx.respond(msg)

@bot.slash_command(name="switchsheet", description="Switch to a different sheet", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def switchsheet(
    ctx: discord.ApplicationContext,
    sheet_name: str = Option(description="Name of the new sheet", required=True, choices=["QPQ test sheet", "Quid Pro Quo Merch Sheet"])
):
    await ctx.defer()
    try:
        await asyncio.wait_for(process_switch_sheet(ctx, sheet_name), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")

async def process_switch_sheet(ctx, sheet_name):
    SHEET_NAME = sheet_name
    global test
    test = SHEET_NAME == "QPQ test sheet"
    await ctx.respond(f"Switched to sheet: {SHEET_NAME}")
    return   

@bot.slash_command(name="recap", description="Get a recap of all new or removed items", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def recap(ctx: discord.ApplicationContext):
    await ctx.defer()
    try:
        await asyncio.wait_for(process_recap(ctx), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")

async def process_recap(ctx):
    if not recent_changes:
        await ctx.respond("No recent changes.")
        return
    parts = ["Recent Changes:"]
    for change in recent_changes:
        parts.append(change)
    msg = "\n".join(parts)
    await ctx.respond(msg)

@bot.slash_command(name="clearrecap", description="clear all items in recap", guild_ids=[SERVER_ID, TEST_SERVER_ID])
async def clear_recap(
    ctx: discord.ApplicationContext
):
    await ctx.defer()
    try:
        await asyncio.wait_for(process_switch_sheet(ctx), timeout=60)
    except asyncio.TimeoutError:
        await ctx.followup.send("The command timed out.")

async def process_switch_sheet(ctx):
    global recent_changes
    recent_changes = []
    await ctx.respond(f"Recent changes cleared.")
    return

def run_web():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

# def self_ping():
#     url = "https://qpq-bot.onrender.com/"
#     while True:
#         try:
#             requests.get(url)
#         except Exception as e:
#             print("Ping failed:", e)
#         time.sleep(600)  # every 10 minutes

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    # threading.Thread(target=self_ping, daemon=True).start()
    bot.run(DISCORD_TOKEN)
