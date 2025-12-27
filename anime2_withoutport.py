# -*- coding: utf-8 -*-

import logging
import random
import re
import json
from pymongo import MongoClient, errors as pymongo_errors
import os
import asyncio
import threading
from pyrogram.client import Client
from pyrogram import filters, StopPropagation
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.enums import ParseMode
from pyrogram.enums import ParseMode

# --- CONFIGURATION ---
# Get these from https://my.telegram.org/
API_ID = 25695711  # <--- REPLACE WITH YOUR API ID (Integer)
API_HASH = "f20065cc26d4a31bf0efc0b44edaffa9" # <--- REPLACE WITH YOUR API HASH (String)
BOT_TOKEN = "8536034020:AAF9vBEWFpGafMUgKKEfQgptQXL_hCwYbd0" # <--- YOUR TOKEN

LEADERBOARD_FILE = "leaderboard.json"
CHATS_FILE = "active_chats.json"
USERS_FILE = "active_users.json"

# --- MONGODB CONFIG ---
# Provided MongoDB connection string (will be used by the bot)
MONGO_URI = "mongodb+srv://yesvashisht2005_db_user:yash2005@cluster0.nd8dam5.mongodb.net/?appName=Cluster0"
MONGO_DB_NAME = "anime_bot"

# MongoDB client/collections (initialized below)
MONGO_CLIENT = None
MONGO_DB = None
COL_ACTIVE_CHATS = None
COL_ACTIVE_USERS = None
COL_LEADERBOARD = None
USE_MONGO = False

def init_mongo():
    global MONGO_CLIENT, MONGO_DB, COL_ACTIVE_CHATS, COL_ACTIVE_USERS, COL_LEADERBOARD, USE_MONGO
    try:
        MONGO_CLIENT = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Try server selection to confirm connection
        MONGO_CLIENT.admin.command('ping')
        # choose a database; if URI contains a default DB, get_default_database may work
        try:
            MONGO_DB = MONGO_CLIENT.get_default_database() or MONGO_CLIENT[MONGO_DB_NAME]
        except Exception:
            MONGO_DB = MONGO_CLIENT[MONGO_DB_NAME]

        COL_ACTIVE_CHATS = MONGO_DB.get_collection('active_chats')
        COL_ACTIVE_USERS = MONGO_DB.get_collection('active_users')
        COL_LEADERBOARD = MONGO_DB.get_collection('leaderboard')
        # ensure indexes
        COL_ACTIVE_CHATS.create_index('chat_id', unique=True)
        COL_ACTIVE_USERS.create_index('user_id', unique=True)
        COL_LEADERBOARD.create_index('user_id', unique=True)
        USE_MONGO = True
        logging.info("Connected to MongoDB and initialized collections.")
    except Exception as e:
        USE_MONGO = False
        logging.error(f"Could not connect to MongoDB: {e}")

# initialize mongo on import
init_mongo()

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# Also log to a file for easier monitoring
file_handler = logging.FileHandler("anime2.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)

# --- GLOBALS AND LOCKS ---
# Global dictionary to store game states
GAMES = {}
# Lock for thread-safe GAMES dict access
GAMES_LOCK = threading.RLock()
# Semaphore to limit concurrent callback processing
CALLBACK_SEMAPHORE = asyncio.Semaphore(10)


# --- DATA LOADING ---
def load_id_set(filename):
    """Loads a set of IDs from a JSON file."""
    # Prefer MongoDB-backed storage when available
    try:
        if USE_MONGO:
            if filename == CHATS_FILE:
                docs = COL_ACTIVE_CHATS.find({}, {"_id": 0, "chat_id": 1})
                return set(d.get('chat_id') for d in docs if 'chat_id' in d)
            if filename == USERS_FILE:
                docs = COL_ACTIVE_USERS.find({}, {"_id": 0, "user_id": 1})
                return set(d.get('user_id') for d in docs if 'user_id' in d)
        # fallback to file
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                return set(json.load(f))
    except (json.JSONDecodeError, IOError, Exception) as e:
        logging.error(f"Failed to load {filename}: {e}")
    return set()

def save_id_set(filename, id_set):
    """Saves a set of IDs to a JSON file."""
    try:
        if USE_MONGO:
            # Upsert entries into respective collections
            if filename == CHATS_FILE:
                COL_ACTIVE_CHATS.delete_many({})
                docs = [{"chat_id": cid} for cid in id_set]
                if docs: COL_ACTIVE_CHATS.insert_many(docs)
                return
            if filename == USERS_FILE:
                COL_ACTIVE_USERS.delete_many({})
                docs = [{"user_id": uid} for uid in id_set]
                if docs: COL_ACTIVE_USERS.insert_many(docs)
                return
        # fallback: write to file
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(list(id_set), f, indent=4)
    except IOError as e:
        logging.error(f"Failed to save {filename}: {e}")
    except Exception as e:
        logging.error(f"Failed to save to MongoDB {filename}: {e}")

ACTIVE_CHATS = load_id_set(CHATS_FILE)
ACTIVE_USERS = load_id_set(USERS_FILE)

def load_characters_with_stats():
    """Load characters from characters.json with per-role stats."""
    try:
        with open("characters.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            char_stats = {}
            for char in data:
                name = char.get("name", "")
                stats = char.get("stats", {})
                if name and stats:
                    char_stats[name] = stats
            return char_stats
    except Exception as e:
        logging.error(f"Failed to load characters.json: {e}")
        return {}

CHAR_STATS = load_characters_with_stats()
ANIME_CHARACTERS = list(CHAR_STATS.keys())

def _normalize_series(name: str) -> str:
    """Normalizes a series name into a simple key."""
    return re.sub(r'[^a-z0-9]', '', name.lower())

SERIES_MAP = {}
SERIES_DISPLAY = {}
try:
    with open("characters.json", "r", encoding="utf-8") as f:
        json_data = json.load(f)
        for char in json_data:
            char_name = char.get("name", "")
            series_name = char.get("series", "Unknown")
            if char_name in ANIME_CHARACTERS:
                key = _normalize_series(series_name)
                SERIES_MAP.setdefault(key, []).append(char_name)
                SERIES_DISPLAY[key] = series_name
except Exception as e:
    logging.error(f"Failed to build series map: {e}")

DEFAULT_POWER = 80
ROLES = ["Captain", "Vice Captain", "Tank", "Healer", "Assassin", "Support 1", "Support 2", "Traitor"]

# --- INIT PYROGRAM CLIENT ---
app = Client(
    "anime_draft_bot2",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# --- MESSAGE HANDLERS ---
# GROUPS are used to control execution order.
# Group -1: Runs first to log everything.
# Group 0 (default): Specific commands like /status, /draft.
# Group 1: Runs after commands to track users/chats from all messages.

@app.on_message(group=-1)
async def debug_log_all_messages(client, message):
    """Logs all incoming messages for debugging purposes."""
    logging.info(
        f"[DEBUG] Message received: "
        f"chat_id={getattr(message.chat, 'id', None)}, "
        f"user_id={getattr(message.from_user, 'id', None)}, "
        f"text={getattr(message, 'text', None)}"
    )
    # Do not stop propagation, so other handlers can process the message
    pass


@app.on_message(filters.command(["status"]))
async def status_handler(client, message: Message):
    """Handles the /status command to show bot stats."""
    logging.info(f"/status command received in chat {message.chat.id}")
    chat_count = len(ACTIVE_CHATS)
    user_count = len(ACTIVE_USERS)
    await message.reply_text(
        f"📊 <b>Bot Status:</b>\n\n"
        f"Active Chats: <b>{chat_count + 15}</b>\n"
        f"Active Users: <b>{user_count + 30}</b>",
        parse_mode=ParseMode.HTML
    )
    # Stop propagation so the tracker doesn't run unnecessarily on this command
    raise StopPropagation

@app.on_message(group=1)
async def track_chats_users(client, message: Message):
    """Tracks unique chat and user IDs from all messages."""
    updated = False
    try:
        if message.chat and message.chat.id not in ACTIVE_CHATS:
            ACTIVE_CHATS.add(message.chat.id)
            updated = True
        if message.from_user and message.from_user.id not in ACTIVE_USERS:
            ACTIVE_USERS.add(message.from_user.id)
            updated = True
    except Exception as e:
        logging.error(f"Error tracking chat/user: {e}")
    
    if updated:
        # Persist to MongoDB or files
        save_id_set(CHATS_FILE, ACTIVE_CHATS)
        save_id_set(USERS_FILE, ACTIVE_USERS)

# --- LEADERBOARD LOGIC ---
def load_leaderboard():
    # Prefer MongoDB leaderboard collection
    try:
        if USE_MONGO:
            data = {}
            for doc in COL_LEADERBOARD.find({}, {"_id": 0}):
                uid = str(doc.get("user_id"))
                data[uid] = {"name": doc.get("name", ""), "wins": int(doc.get("wins", 0)), "matches": int(doc.get("matches", 0))}
            return data
        # fallback to file
        if not os.path.exists(LEADERBOARD_FILE):
            return {}
        with open(LEADERBOARD_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load leaderboard: {e}")
        return {}

def save_leaderboard(data):
    try:
        if USE_MONGO:
            # Replace contents of leaderboard collection
            COL_LEADERBOARD.delete_many({})
            docs = []
            for uid, stats in data.items():
                docs.append({"user_id": int(uid) if str(uid).isdigit() else uid, "name": stats.get("name", ""), "wins": int(stats.get("wins", 0)), "matches": int(stats.get("matches", 0))})
            if docs:
                COL_LEADERBOARD.insert_many(docs)
            return
        with open(LEADERBOARD_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save leaderboard: {e}")

def update_leaderboard(user_id, name, is_winner):
    try:
        if USE_MONGO:
            uid = int(user_id) if isinstance(user_id, (int, str)) and str(user_id).isdigit() else user_id
            doc = COL_LEADERBOARD.find_one({"user_id": uid})
            if not doc:
                new = {"user_id": uid, "name": name, "wins": 1 if is_winner else 0, "matches": 1}
                COL_LEADERBOARD.insert_one(new)
            else:
                update = {"$inc": {"matches": 1}}
                if is_winner:
                    update["$inc"]["wins"] = 1
                COL_LEADERBOARD.update_one({"user_id": uid}, update)
                COL_LEADERBOARD.update_one({"user_id": uid}, {"$set": {"name": name}})
            return
    except Exception as e:
        logging.error(f"MongoDB leaderboard update failed: {e}")

    # fallback to file-based
    data = load_leaderboard()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {"name": name, "wins": 0, "matches": 0}
    data[uid]["name"] = name
    data[uid]["matches"] += 1
    if is_winner:
        data[uid]["wins"] += 1
    save_leaderboard(data)

# --- HELPERS ---
def get_team_display(game):
    p1, p2 = game['p1'], game['p2']
    txt = f"🔵 **{p1['name']}**:\n"
    for role in ROLES:
        val = p1['team'].get(role, "...")
        txt += f"• {role}: `{val}`\n"
    txt += f"\n🔴 **{p2['name']}**:\n"
    for role in ROLES:
        val = p2['team'].get(role, "...")
        txt += f"• {role}: `{val}`\n"
    return txt

async def safe_edit_text(message, text, reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    """Safely edit message with error handling and flood wait management."""
    if not message:
        logging.error("Cannot edit: message is None")
        return None
    try:
        return await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except FloodWait as e:
        wait_time = e.value + 1
        logging.warning(f"FloodWait detected, sleeping {wait_time}s.")
        await asyncio.sleep(wait_time)
        return await safe_edit_text(message, text, reply_markup, parse_mode)
    except Exception as e:
        logging.error(f"Failed to edit message: {type(e).__name__}: {e}")
        return None

def switch_turn(game):
    p1_count = len(game["p1"]["team"])
    p2_count = len(game["p2"]["team"])
    current_id, p1_id, p2_id = game["turn"], game["p1"]["id"], game["p2"]["id"]
    if current_id == p1_id:
        if p2_count < 8: game["turn"] = p2_id
    else:
        if p1_count < 8: game["turn"] = p1_id

# --- RPG SIMULATION ---
async def simulate_battle(callback_query, game):
    """Simulate battle with error handling."""
    try:
        p1, p2 = game.get("p1"), game.get("p2")
        if not p1 or not p2:
            logging.error("Game missing p1 or p2 data")
            return
        
        p1_score, p2_score = 0, 0
        log = "🏟 **BATTLE ARENA SIMULATION**\n\n"
        
        def get_stat(name, role):
            stats = CHAR_STATS.get(name)
            if not stats: return DEFAULT_POWER
            role_map = {
                "Captain": "captain", "Vice Captain": "vice_captain", "Tank": "tank",
                "Healer": "healer", "Assassin": "assassin", "Support 1": "support",
                "Support 2": "support", "Traitor": "traitor"
            }
            return stats.get(role_map.get(role), DEFAULT_POWER)

        matchups = [
            ("Captain", "Captain", "⚔️ **1. Captain vs Captain**", 30),
            ("Vice Captain", "Vice Captain", "⚡️ **2. Vice Captain vs Vice Captain**", 25),
            ("Tank", "Tank", "🛡 **3. Tank vs Tank**", 15),
            ("Support 1", "Support 1", "🤝 **4. Support 1 vs Support 1**", 10),
            ("Support 2", "Support 2", "🤝 **5. Support 2 vs Support 2**", 10),
            ("Assassin", "Healer", "💀 **6. P1 Assassin vs P2 Healer**", 20),
            ("Healer", "Assassin", "💚 **7. P2 Assassin vs P1 Healer**", 20),
            ("Traitor", None, "🎭 **8. P1 Traitor Check**", -30),
            (None, "Traitor", "🎭 **9. P2 Traitor Check**", -30)
        ]

        for r1, r2, title, points in matchups:
            c1 = p1["team"].get(r1) if r1 else None
            c2 = p2["team"].get(r2) if r2 else None
            if r1 and r2 and c1 and c2:
                stat1 = get_stat(c1, r1) + random.randint(-3, 7)
                stat2 = get_stat(c2, r2) + random.randint(-3, 7)
                if r1 == "Healer" and r2 == "Assassin": stat1 = int(round(stat1 * 2.3))
                if r1 == "Assassin" and r2 == "Healer": stat2 = int(round(stat2 * 2.3))
                log += f"{title}:\n"
                if stat1 > stat2:
                    p1_score += points
                    log += f"🔵 {c1} def. {c2} (+{points} Pts)\n\n"
                elif stat2 > stat1:
                    p2_score += points
                    log += f"🔴 {c2} def. {c1} (+{points} Pts)\n\n"
                else:
                    log += f"⚖️ Draw ({c1} vs {c2})\n\n"
            elif r1 == "Traitor" and c1:
                if random.random() < 0.5:
                    p1_score += points
                    log += f"{title}: 🎭 **BETRAYAL!** 🔵 {c1} betrayed their team! ({points} Pts)\n\n"
                else:
                    log += f"{title}: 🔵 {c1} stayed loyal!\n\n"
            elif r2 == "Traitor" and c2:
                if random.random() < 0.5:
                    p2_score += points
                    log += f"{title}: 🎭 **BETRAYAL!** 🔴 {c2} betrayed their team! ({points} Pts)\n\n"
                else:
                    log += f"{title}: 🔴 {c2} stayed loyal!\n\n"

        winner_name = "Draw"
        if p1_score > p2_score:
            winner_name = p1['name']
            update_leaderboard(p1['id'], p1['name'], True)
            update_leaderboard(p2['id'], p2['name'], False)
        elif p2_score > p1_score:
            winner_name = p2['name']
            update_leaderboard(p2['id'], p2['name'], True)
            update_leaderboard(p1['id'], p1['name'], False)
        else:
            update_leaderboard(p1['id'], p1['name'], False)
            update_leaderboard(p2['id'], p2['name'], False)

        final_text = f"{log}➖➖➖➖➖➖➖➖\n🔵 Score: {p1_score} | 🔴 Score: {p2_score}\n\n🏆 **WINNER: {winner_name}**"
        await safe_edit_text(callback_query.message, final_text)
        
        try:
            chat_id, gid = callback_query.message.chat.id, game.get("game_id")
            with GAMES_LOCK:
                if chat_id in GAMES and gid in GAMES[chat_id]:
                    del GAMES[chat_id][gid]
                    if not GAMES[chat_id]: del GAMES[chat_id]
        except Exception as e:
            logging.error(f"Error cleaning up game: {e}")
    except Exception as e:
        logging.error(f"Error in simulate_battle: {type(e).__name__}: {e}")
        try: await callback_query.answer(f"❌ Battle error: {str(e)[:50]}", show_alert=True)
        except: pass

# --- MENU HELPERS ---
async def show_draw_menu(client, message, game, game_id):
    turn_name = game["p1"]["name"] if game["turn"] == game["p1"]["id"] else game["p2"]["name"]
    text = f"🏁 **Drafting Phase**\n\n{get_team_display(game)}\n🎮 **Turn:** {turn_name}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Draw Character", callback_data=f"action_draw_{game_id}")]])
    await safe_edit_text(message, text, reply_markup=kb)

async def show_assignment_menu(client, message, game, char, game_id):
    cp_key = "p1" if game["turn"] == game["p1"]["id"] else "p2"
    team, skips, player_name = game[cp_key]["team"], game[cp_key]["skips"], game[cp_key]["name"]
    keyboard, row = [], []
    for role in ROLES:
        if role not in team:
            row.append(InlineKeyboardButton(f"🟢 {role}", callback_data=f"set_{role}_{game_id}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
    if row: keyboard.append(row)
    if skips > 0:
        keyboard.append([InlineKeyboardButton(f"🗑 Skip ({skips})", callback_data=f"action_skip_{game_id}")])
    text = f"{get_team_display(game)}\n✨ {player_name}'s turn\nPulled: **{char}**\nAssign a position:"
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def finish_game(client, message, game, game_id):
    game["status"], game["battle_ready"] = "finished", {"p1": False, "p2": False}
    keyboard = [
        [InlineKeyboardButton(f"🔵 {game['p1']['name']} READY", callback_data=f"start_rpg_battle_p1_{game_id}")],
        [InlineKeyboardButton(f"🔴 {game['p2']['name']} READY", callback_data=f"start_rpg_battle_p2_{game_id}")]
    ]
    text = f"🏁 **TEAMS READY!** 🏁\n\n{get_team_display(game)}\n\n⚔️ **BOTH PLAYERS MUST CLICK TO START BATTLE**"
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_battle_confirmation(client, message, game, game_id):
    if game["battle_ready"]["p1"] and game["battle_ready"]["p2"]:
        class DummyCQ:
            def __init__(self, msg): self.message = msg
        await simulate_battle(DummyCQ(message), game)
        return
    
    p1_status = "✅ READY" if game["battle_ready"]["p1"] else "⏳ WAITING"
    p2_status = "✅ READY" if game["battle_ready"]["p2"] else "⏳ WAITING"
    keyboard = [
        [InlineKeyboardButton(f"🔵 {game['p1']['name']} {p1_status}", callback_data=f"start_rpg_battle_p1_{game_id}")],
        [InlineKeyboardButton(f"🔴 {game['p2']['name']} {p2_status}", callback_data=f"start_rpg_battle_p2_{game_id}")]
    ]
    text = f"🏁 **TEAMS READY!** 🏁\n\n{get_team_display(game)}\n\n⚔️ **P1: {p1_status}** | **P2: {p2_status}**\n\nWaiting for both players to confirm..."
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard))

# --- PYROGRAM COMMAND HANDLERS ---
@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    await message.reply_text(
        "⚔️ **Anime Draft Wars** ⚔️\n\n"
        "Commands:\n"
        "/draft - Reply to a user to start a battle\n"
        "/leaderboard - See top players\n"
        "/status - View bot statistics"
    )

@app.on_message(filters.command("leaderboard"))
async def leaderboard_handler(client, message: Message):
    data = load_leaderboard()
    if not data:
        await message.reply_text("📉 Leaderboard is empty yet!")
        return
    
    sorted_users = sorted(data.items(), key=lambda x: x[1]['wins'], reverse=True)
    msg = "🏆 **GLOBAL LEADERBOARD** 🏆\n\n"
    for rank, (uid, stats) in enumerate(sorted_users[:10], 1):
        msg += f"{rank}. **{stats['name']}**: {stats['wins']} Wins\n"
    await message.reply_text(msg)

@app.on_message(filters.command("draft"))
async def draft_handler(client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("⚠️ Reply to a user to challenge them!")
        return

    challenger, opponent = message.from_user, message.reply_to_message.from_user
    if not opponent:
        await message.reply_text("⚠️ Unable to identify opponent. Reply directly to a user's message.")
        return
    if opponent.is_bot or challenger.id == opponent.id:
        await message.reply_text("⚠️ You can't battle bots or yourself.")
        return

    parts = message.text.split(maxsplit=1)
    series_filter = None
    if len(parts) > 1:
        key = _normalize_series(parts[1])
        if key not in SERIES_MAP:
            sample = ', '.join(list(SERIES_DISPLAY.values())[:5])
            await message.reply_text(f"⚠️ Unknown series. Examples: {sample}")
            return
        series_filter = key

    chat_id = message.chat.id
    with GAMES_LOCK:
        GAMES.setdefault(chat_id, {})
        game_id = ''.join(random.choices('0123456789abcdef', k=8))
        GAMES[chat_id][game_id] = {
            "game_id": game_id, "status": "waiting",
            "p1": {"id": challenger.id, "name": challenger.first_name, "team": {}, "skips": 2},
            "p2": {"id": opponent.id, "name": opponent.first_name, "team": {}, "skips": 2},
            "turn": challenger.id, "used_chars": [], "current_draw": None,
            "series_filter": series_filter, "battle_ready": {"p1": False, "p2": False}
        }
    keyboard = [[InlineKeyboardButton("✅ Accept Battle", callback_data=f"accept_battle_{game_id}")]]
    await message.reply_text(
        f"⚔️ **DRAFT CHALLENGE**\n👤 {challenger.first_name} VS 👤 {opponent.first_name}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- CALLBACK HANDLER ---
@app.on_callback_query()
async def callback_handler(client, callback_query: CallbackQuery):
    async with CALLBACK_SEMAPHORE:
        try:
            chat_id, user_id, data = callback_query.message.chat.id, callback_query.from_user.id, callback_query.data
            match = re.match(r"(.+?)_([0-9a-f]{8})$", data)
            if not match: return await callback_query.answer("❌ Invalid callback.", show_alert=True)
            
            action, game_id = match.groups()
            
            with GAMES_LOCK:
                game = GAMES.get(chat_id, {}).get(game_id)
            if not game: return await callback_query.answer("❌ Game expired or not found.", show_alert=True)
            
            p1_id, p2_id = game["p1"]["id"], game["p2"]["id"]
            is_p1, is_p2 = user_id == p1_id, user_id == p2_id
            
            if action == "accept_battle":
                if not is_p2: return await callback_query.answer("❌ Not for you!", show_alert=True)
                game["status"] = "active"
                await show_draw_menu(client, callback_query.message, game, game_id)
            elif action.startswith("start_rpg_battle"):
                if is_p1 and action.endswith("p1"): game["battle_ready"]["p1"] = True
                elif is_p2 and action.endswith("p2"): game["battle_ready"]["p2"] = True
                else: return await callback_query.answer("❌ You can't click this!", show_alert=True)
                await show_battle_confirmation(client, callback_query.message, game, game_id)
            elif user_id != game["turn"]:
                return await callback_query.answer("✋ Not your turn!", show_alert=True)
            elif action == "action_draw":
                pool = (SERIES_MAP.get(game["series_filter"], []) if game.get("series_filter") 
                        else ANIME_CHARACTERS)
                available = [c for c in pool if c not in game["used_chars"]]
                if not available: return await callback_query.answer("❌ No characters left!", show_alert=True)
                drawn = random.choice(available)
                game["current_draw"] = drawn
                await show_assignment_menu(client, callback_query.message, game, drawn, game_id)
            elif action.startswith("set_"):
                role = action.replace("set_", "")
                cp_key = "p1" if is_p1 else "p2"
                game[cp_key]["team"][role] = game["current_draw"]
                game["used_chars"].append(game["current_draw"])
                game["current_draw"] = None
                if len(game["p1"]["team"]) == 8 and len(game["p2"]["team"]) == 8:
                    await finish_game(client, callback_query.message, game, game_id)
                else:
                    switch_turn(game)
                    await show_draw_menu(client, callback_query.message, game, game_id)
            elif action == "action_skip":
                cp_key = "p1" if is_p1 else "p2"
                if game[cp_key]["skips"] > 0:
                    game[cp_key]["skips"] -= 1
                    if game["current_draw"]: game["used_chars"].append(game["current_draw"])
                    game["current_draw"] = None
                    switch_turn(game)
                    await show_draw_menu(client, callback_query.message, game, game_id)
                else:
                    await callback_query.answer("❌ No skips left!", show_alert=True)
        except Exception as e:
            logging.error(f"Error in callback handler: {type(e).__name__}: {e}")
            try: await callback_query.answer(f"❌ Error: {str(e)[:50]}", show_alert=True)
            except: pass

if __name__ == '__main__':
    logging.info("Bot is starting...")
    try:
        app.run()
        logging.info("Bot has stopped.")
    except Exception as e:
        logging.critical(f"Bot startup failed: {type(e).__name__}: {e}")
        raise
