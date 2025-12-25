import logging
import random
import re
import json
import os
import asyncio
import uuid
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

# --- CONFIGURATION ---
# Get these from https://my.telegram.org/
API_ID = 25695711  # <--- REPLACE WITH YOUR API ID (Integer)
API_HASH = "f20065cc26d4a31bf0efc0b44edaffa9" # <--- REPLACE WITH YOUR API HASH (String)
BOT_TOKEN = "8322954992:AAG_F5HDr7ajcKlCJvXxAzqVR_bZ-D0fusQ" # <--- YOUR TOKEN

LEADERBOARD_FILE = "leaderboard.json"

# Global dictionary to store game states
# Structure: {chat_id: {game_id: game_data}}
GAMES = {} 

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# Also log to a file for easier monitoring
file_handler = logging.FileHandler("anime2.log")
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)

# --- DATA: CHARACTERS & POWER LEVELS (loaded from JSON) ---
def load_characters():
    """Load characters from characters.json with separate name and series fields"""
    try:
        with open("characters.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            char_dict = {}
            for char in data.get("characters", []):
                name = char.get("name", "")
                power = char.get("power", 50)
                if name:
                    char_dict[name] = power
            return char_dict
    except Exception as e:
        logging.error(f"Failed to load characters.json: {e}")
        return {}

CHAR_POWER = load_characters()

ANIME_CHARACTERS = list(CHAR_POWER.keys())

# Build a mapping of normalized series keys -> list of characters for filtering
def _normalize_series(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower())

# Load characters with series mapping from JSON
SERIES_MAP = {}
SERIES_DISPLAY = {}
try:
    with open("characters.json", "r", encoding="utf-8") as f:
        json_data = json.load(f)
        for char in json_data.get("characters", []):
            char_name = char.get("name", "")
            series_name = char.get("series", "Unknown")
            if char_name in ANIME_CHARACTERS:
                key = _normalize_series(series_name)
                SERIES_MAP.setdefault(key, []).append(char_name)
                SERIES_DISPLAY[key] = series_name
except Exception as e:
    logging.error(f"Failed to build series map: {e}")

DEFAULT_POWER = 80

ROLES = [
    "Captain", "Vice Captain", "Tank", "Healer", 
    "Assassin", "Support 1", "Support 2", "Traitor"
]

# --- INIT PYROGRAM CLIENT ---
app = Client(
    "anime_draft_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --- LEADERBOARD LOGIC ---
def load_leaderboard():
    if not os.path.exists(LEADERBOARD_FILE):
        return {}
    try:
        with open(LEADERBOARD_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_leaderboard(data):
    with open(LEADERBOARD_FILE, "w") as f:
        json.dump(data, f)

def update_leaderboard(user_id, name, is_winner):
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
    p1 = game['p1']
    p2 = game['p2']
    
    txt = f"🔵 **{p1['name']}**:\n"
    for role in ROLES:
        val = p1['team'].get(role, "Empty")
        if val == "Empty": val = "..."
        txt += f"• {role}: `{val}`\n"
    
    txt += f"\n🔴 **{p2['name']}**:\n"
    for role in ROLES:
        val = p2['team'].get(role, "Empty")
        if val == "Empty": val = "..."
        txt += f"• {role}: `{val}`\n"
        
    return txt

def switch_turn(game):
    p1_count = len(game["p1"]["team"])
    p2_count = len(game["p2"]["team"])
    current_id = game["turn"]
    p1_id = game["p1"]["id"]
    p2_id = game["p2"]["id"]

    if current_id == p1_id:
        if p2_count < 8: game["turn"] = p2_id
        elif p1_count < 8: game["turn"] = p1_id
    else:
        if p1_count < 8: game["turn"] = p1_id
        elif p2_count < 8: game["turn"] = p2_id

# --- RPG SIMULATION ---
async def simulate_battle(callback_query, game):
    p1 = game["p1"]
    p2 = game["p2"]
    
    p1_score = 0
    p2_score = 0
    log = "🏟 **BATTLE ARENA SIMULATION**\n\n"
    
    def get_power(name):
        return CHAR_POWER.get(name, DEFAULT_POWER)

    matchups = [
        ("Captain", "Captain", "⚔️ **1. Captain vs Captain**"),
        ("Vice Captain", "Vice Captain", "⚡️ **2. Vice Captain vs Vice Captain**"),
        ("Tank", "Tank", "🛡 **3. Tank vs Tank**"),
        ("Support 1", "Support 1", "🤝 **4. Support vs Support**"),
        ("Healer", "Assassin", "💚 **5. P1 Healer vs P2 Assassin**"),
        ("Assassin", "Healer", "💀 **6. P1 Assassin vs P2 Healer**"),
        ("Traitor", "Support 2", "🎭 **7. P1 Traitor vs P2 Support 2**"),
        ("Support 2", "Traitor", "🎭 **8. P1 Support 2 vs P2 Traitor**")
    ]
    
    for r1, r2, title in matchups:
        c1 = p1["team"].get(r1)
        c2 = p2["team"].get(r2)
        
        # Healer vs Assassin Logic (Battle 5: P1 Healer vs P2 Assassin)
        if r1 == "Healer" and r2 == "Assassin":
             pow1 = get_power(c1) + random.randint(0, 10)
             pow2 = get_power(c2) + random.randint(0, 10)
             log += f"{title}:\n"
             if pow2 > pow1:
                 p2_score += 15
                 log += f"🔴 {c2} assassinated 🔵 {c1}! (+15 Pts)\n\n"
             else:
                 log += f"🔵 {c1} survived the assassination attempt!\n\n"
             continue
        
        # Assassin vs Healer Logic (Battle 6: P1 Assassin vs P2 Healer)
        if r1 == "Assassin" and r2 == "Healer":
             pow1 = get_power(c1) + random.randint(0, 10)
             pow2 = get_power(c2) + random.randint(0, 10)
             log += f"{title}:\n"
             if pow1 > pow2:
                 p1_score += 15
                 log += f"🔵 {c1} assassinated 🔴 {c2}! (+15 Pts)\n\n"
             else:
                 log += f"🔴 {c2} survived the assassination attempt!\n\n"
             continue

        # Traitor Logic
        if r1 == "Traitor" or r2 == "Traitor":
            if r1 == "Traitor":
                if random.random() < 0.6:
                    p1_score -= 20
                    log += f"{title}:\n"
                    log += f"🎭 **BETRAYAL!** 🔵 {c1} attacked their own team! (-20 Pts)\n\n"
                else:
                    log += f"{title}:\n"
                    log += f"🔵 {c1} stayed loyal!\n\n"
            elif r2 == "Traitor":
                if random.random() < 0.6:
                    p2_score -= 20
                    log += f"{title}:\n"
                    log += f"🎭 **BETRAYAL!** 🔴 {c2} attacked their own team! (-20 Pts)\n\n"
                else:
                    log += f"{title}:\n"
                    log += f"🔴 {c2} stayed loyal!\n\n"
            continue

        # Standard Clash
        pow1 = get_power(c1) + random.randint(-5, 15)
        pow2 = get_power(c2) + random.randint(-5, 15)
        
        log += f"{title}:\n"
        if pow1 > pow2:
            p1_score += 10
            log += f"🔵 {c1} def. {c2}\n"
        elif pow2 > pow1:
            p2_score += 10
            log += f"🔴 {c2} def. {c1}\n"
        else:
            log += f"⚖️ Draw ({c1} vs {c2})\n"
        log += "\n"

    # Winner
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

    final_text = (
        f"{log}"
        f"➖➖➖➖➖➖➖➖\n"
        f"🔵 Score: {p1_score} | 🔴 Score: {p2_score}\n\n"
        f"🏆 **WINNER: {winner_name}**"
    )
    
    await callback_query.message.edit_text(final_text)

# --- MENU HELPERS ---

async def show_draw_menu(client, message, game, game_id):
    turn_name = game["p1"]["name"] if game["turn"] == game["p1"]["id"] else game["p2"]["name"]
    text = f"🏁 **Drafting Phase**\n\n{get_team_display(game)}\n🎮 **Turn:** {turn_name}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Draw Character", callback_data=f"action_draw_{game_id}")]])
    await message.edit_text(text, reply_markup=kb)

async def show_assignment_menu(client, message, game, char):
    cp_key = "p1" if game["turn"] == game["p1"]["id"] else "p2"
    team = game[cp_key]["team"]
    skips = game[cp_key]["skips"]
    
    keyboard = []
    row = []
    for role in ROLES:
        if role not in team:
            row.append(InlineKeyboardButton(f"🟢 {role}", callback_data=f"set_{role}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
    if row: keyboard.append(row)
    if skips > 0: keyboard.append([InlineKeyboardButton(f"🗑 Skip ({skips})", callback_data="action_skip")])

    text = f"{get_team_display(game)}\n✨ Pulled: **{char}**\nAssign a position:"
    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def finish_game(client, message, game):
    if len(game["p1"]["team"]) != 8 or len(game["p2"]["team"]) != 8:
        return
    
    game["status"] = "finished"
    game["battle_ready"] = {"p1": False, "p2": False}
    
    keyboard = [
        [InlineKeyboardButton(f"🔵 {game['p1']['name']} READY", callback_data="start_rpg_battle_p1")],
        [InlineKeyboardButton(f"🔴 {game['p2']['name']} READY", callback_data="start_rpg_battle_p2")]
    ]
    
    text = f"🏁 **TEAMS READY!** 🏁\n\n{get_team_display(game)}\n\n⚔️ **BOTH PLAYERS MUST CLICK TO START BATTLE**"
    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_battle_confirmation(client, message, game):
    p1_status = "✅ READY" if game["battle_ready"]["p1"] else "⏳ WAITING"
    p2_status = "✅ READY" if game["battle_ready"]["p2"] else "⏳ WAITING"
    
    if game["battle_ready"]["p1"] and game["battle_ready"]["p2"]:
        # We need a CallbackQuery object to reuse the simulate_battle logic easily, 
        # or we just assume the context from the message. 
        # Since simulate_battle uses .message.edit_text, passing the wrapper object is tricky.
        # Let's adjust simulate_battle slightly or wrap it.
        # Actually, simulate_battle takes 'callback_query'. 
        # We can just construct a dummy one or adapt the function. 
        # Better: let's pass a dummy wrapper that has .message.edit_text
        class DummyCQ:
            def __init__(self, msg): self.message = msg
        await simulate_battle(DummyCQ(message), game)
        return
    
    keyboard = [
        [InlineKeyboardButton(f"🔵 {game['p1']['name']} {p1_status}", callback_data="start_rpg_battle_p1")],
        [InlineKeyboardButton(f"🔴 {game['p2']['name']} {p2_status}", callback_data="start_rpg_battle_p2")]
    ]
    
    text = f"🏁 **TEAMS READY!** 🏁\n\n{get_team_display(game)}\n\n⚔️ **P1: {p1_status}** | **P2: {p2_status}**\n\nWaiting for both players to confirm..."
    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# --- PYROGRAM HANDLERS ---

@app.on_message(filters.command("start"))
async def start_command(client, message):
    await message.reply_text(
        "⚔️ **Anime Draft Wars** ⚔️\n\n"
        "Commands:\n"
        "/draft - Reply to a user to start a battle\n"
        "/leaderboard - See top players"
    )

@app.on_message(filters.command("leaderboard"))
async def leaderboard_handler(client, message):
    data = load_leaderboard()
    if not data:
        await message.reply_text("📉 Leaderboard is empty yet!")
        return
    
    sorted_users = sorted(data.items(), key=lambda x: x[1]['wins'], reverse=True)
    msg = "🏆 **GLOBAL LEADERBOARD** 🏆\n\n"
    rank = 1
    for uid, stats in sorted_users[:10]:
        msg += f"{rank}. **{stats['name']}**: {stats['wins']} Wins\n"
        rank += 1
    await message.reply_text(msg)

@app.on_message(filters.command("draft"))
async def draft_handler(client, message):
    if not message.reply_to_message:
        await message.reply_text("⚠️ Reply to a user to challenge them!")
        return

    challenger = message.from_user
    opponent = message.reply_to_message.from_user

    if opponent.is_bot or challenger.id == opponent.id:
        await message.reply_text("⚠️ You can't battle bots or yourself.")
        return

    # Optional argument: /draft <series>
    parts = message.text.split()
    series_filter = None
    if len(parts) > 1:
        arg = parts[1].strip()
        key = re.sub(r'[^a-z0-9]', '', arg.lower())
        if key not in SERIES_MAP:
            # give helpful list of available series (shortened)
            sample = ', '.join(sorted(set(SERIES_DISPLAY[k] for k in SERIES_DISPLAY))[:8])
            await message.reply_text(f"⚠️ Unknown series '{arg}'. Examples: {sample}")
            return
        series_filter = key

    chat_id = message.chat.id
    game_id = str(uuid.uuid4())[:8]  # Generate unique game ID

    # Initialize chat games dict if not exists
    if chat_id not in GAMES:
        GAMES[chat_id] = {}

    # Store game in global dict with unique ID
    GAMES[chat_id][game_id] = {
        "game_id": game_id,
        "status": "waiting",
        "p1": {"id": challenger.id, "name": challenger.first_name, "team": {}, "skips": 2},
        "p2": {"id": opponent.id, "name": opponent.first_name, "team": {}, "skips": 2},
        "turn": challenger.id,
        "used_chars": [],
        "current_draw": None,
        "series_filter": series_filter,
        "battle_ready": {"p1": False, "p2": False}
    }

    keyboard = [[InlineKeyboardButton("✅ Accept Battle", callback_data=f"accept_battle_{game_id}")]]
    await message.reply_text(
        f"⚔️ **DRAFT CHALLENGE** (ID: {game_id})\n👤 {challenger.first_name} VS 👤 {opponent.first_name}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@app.on_callback_query()
async def callback_handler(client, callback_query):
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    # Extract game_id from callback data
    game_id = None
    if "_" in data:
        parts = data.split("_")
        if len(parts[-1]) <= 8:  # game_id is max 8 chars
            game_id = parts[-1]
            data = "_".join(parts[:-1])
    
    if chat_id not in GAMES or game_id not in GAMES[chat_id]:
        await callback_query.answer("❌ Game expired or not found.", show_alert=True)
        return
    
    game = GAMES[chat_id][game_id]
    
    # Battle Ready Logic
    if data == "start_rpg_battle_p1":
        if user_id != game["p1"]["id"]:
            await callback_query.answer("❌ Only P1 can click this!", show_alert=True)
            return
        if game["battle_ready"]["p1"]:
            await callback_query.answer("⏳ Already clicked!", show_alert=True)
            return
        game["battle_ready"]["p1"] = True
        await show_battle_confirmation(client, callback_query.message, game)
        return

    if data == "start_rpg_battle_p2":
        if user_id != game["p2"]["id"]:
            await callback_query.answer("❌ Only P2 can click this!", show_alert=True)
            return
        if game["battle_ready"]["p2"]:
            await callback_query.answer("⏳ Already clicked!", show_alert=True)
            return
        game["battle_ready"]["p2"] = True
        await show_battle_confirmation(client, callback_query.message, game)
        return

    # Accept
    if data == "accept_battle":
        if user_id != game["p2"]["id"]:
            await callback_query.answer("❌ Not for you!", show_alert=True)
            return
        game["status"] = "active"
        await show_draw_menu(client, callback_query.message, game)
        return

    # Turn Check
    if user_id != game["turn"]:
        await callback_query.answer("✋ Not your turn!", show_alert=True)
        return

    # Draw
    if data == "action_draw":
        if game.get("series_filter"):
            sf = game["series_filter"]
            pool = [c for c in SERIES_MAP.get(sf, []) if c not in game["used_chars"]]
        else:
            pool = [c for c in ANIME_CHARACTERS if c not in game["used_chars"]]
        if not pool:
            await callback_query.answer("❌ No characters left!", show_alert=True)
            return
        drawn = random.choice(pool)
        game["current_draw"] = drawn
        await show_assignment_menu(client, callback_query.message, game, drawn)
        return

    # Assign Role
    if data.startswith("set_"):
        role = data.replace("set_", "")
        cp_key = "p1" if game["turn"] == game["p1"]["id"] else "p2"
        
        game[cp_key]["team"][role] = game["current_draw"]
        game["used_chars"].append(game["current_draw"])
        game["current_draw"] = None

        if len(game["p1"]["team"]) == 8 and len(game["p2"]["team"]) == 8:
            await finish_game(client, callback_query.message, game)
            # Clean up completed game from GAMES dict
            del GAMES[chat_id][game_id]
            return

        switch_turn(game)
        await show_draw_menu(client, callback_query.message, game)
        return

    # Skip
    if data == "action_skip":
        cp_key = "p1" if game["turn"] == game["p1"]["id"] else "p2"
        if game[cp_key]["skips"] > 0:
            game[cp_key]["skips"] -= 1
            if game["current_draw"]: game["used_chars"].append(game["current_draw"])
            game["current_draw"] = None
            switch_turn(game)
            await show_draw_menu(client, callback_query.message, game)
        else:
            await callback_query.answer("❌ No skips left!", show_alert=True)

if __name__ == '__main__':
    logging.info("Bot is starting...")
    app.run()