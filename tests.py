import asyncio
from math import e
import gspread
import discord
from discord.ext import commands
from discord import Option
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
from main import ITEM_TYPES, UV_TYPES, UV_LEVELS, USERNAME_DICT
from main import get_row_number, make_new_row, verify_amount, verify_username, verify_uvs
# --- Environment Setup ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SHEET_NAME = os.getenv("SHEET_NAME")
SERVER_ID = int(os.getenv("SERVER_ID"))
TEST_SERVER_ID = int(os.getenv("TEST_SERVER_ID"))

# --- Google Sheets Setup ---
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/spreadsheets",
         "https://www.googleapis.com/auth/drive.file",
         "https://www.googleapis.com/auth/drive"]

creds = ServiceAccountCredentials.from_json_keyfile_name("arched-elixir-471411-e0-0a32c7ac4698.json", scope)
client_gs = gspread.authorize(creds)
intents = discord.Intents.default()
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)
spreadsheet = client_gs.open(SHEET_NAME)

def test_get_row_number_non_gear():
    try:
        row = get_row_number("Costumes", "item2")
        assert row == 3, f"Expected row 3, got {row}"
        print("test_get_row_number_non_gear passed")
    except Exception as e:
        print(f"test_get_row_number_non_gear failed: {e}")
        return
    
def test_get_row_number_gear():
    try:
        row = get_row_number("Gear", "sword")
        assert row == 2, f"Expected row 2, got {row}"
        print("test_get_row_number_gear passed")
    except Exception as e:
        print(f"test_get_row_number_gear failed: {e}")
        return
bot.run(DISCORD_TOKEN)
test_get_row_number_gear()
test_get_row_number_non_gear()