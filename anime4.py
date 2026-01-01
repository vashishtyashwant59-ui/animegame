import logging
import random
import re
import json
import asyncio
import threading
import html
import math
from pymongo import MongoClient
import os
import time
from pyrogram.client import Client
from pyrogram import filters
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.enums import ParseMode
from flask import Flask, Response
import urllib.request
import urllib.error

# --- CONFIGURATION ---
API_ID = 25695711  
API_HASH = "f20065cc26d4a31bf0efc0b44edaffa9" 
BOT_TOKEN = "8322954992:AAG_F5HDr7ajcKlCJvXxAzqVR_bZ-D0fusQ" 

# REPLACE WITH YOUR TELEGRAM USER ID FOR BROADCAST COMMAND
ADMIN_IDS = [123456789, 6265981509] 

LEADERBOARD_FILE = "leaderboard.json"
CHATS_FILE = "active_chats.json"
USERS_FILE = "active_users.json"
CHARACTERS_FILE = "characters_new.json"

# Event flags
NEW_YEAR_EVENT = os.environ.get("NEW_YEAR_EVENT", "").lower() in ("1", "true", "yes")
EVENT_FLAGS_FILE = "event_flags.json"
# If a persisted flags file exists, prefer it over the environment variable
try:
    if os.path.exists(EVENT_FLAGS_FILE):
        with open(EVENT_FLAGS_FILE, "r", encoding="utf-8") as _f:
            _ef = json.load(_f)
            NEW_YEAR_EVENT = bool(_ef.get("NEW_YEAR_EVENT", NEW_YEAR_EVENT))
except Exception:
    logging.exception('Failed to load event flags')
# --- MONGODB CONFIG ---
MONGO_URI = "mongodb+srv://yesvashisht2005_db_user:yash2005@cluster0.nd8dam5.mongodb.net/?appName=Cluster0"
MONGO_DB_NAME = "anime_bot"

MONGO_CLIENT = None
MONGO_DB = None
COL_ACTIVE_CHATS = None
COL_ACTIVE_USERS = None
COL_LEADERBOARD = None
USE_MONGO = False

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
file_handler = logging.FileHandler("anime_bot.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)

# --- GLOBALS ---
GAMES = {}
GAMES_LOCK = threading.RLock()
CALLBACK_SEMAPHORE = asyncio.Semaphore(10)

CHAR_STATS = {}
CHAR_IMAGES = {}
ANIME_CHARACTERS = []
SERIES_MAP = {}
SERIES_DISPLAY = {}

DEFAULT_POWER = 80
ROLES = ["Captain", "Vice Captain", "Tank", "Healer", "Assassin", "Support 1", "Support 2", "Traitor"]

# Multiplier applied to Healer when facing an Assassin
HEALER_BONUS = 2.3

# Forfeit settings (seconds)
FORFEIT_TIMEOUT = 5 * 60  # 5 minutes
FORFEIT_CHECK_INTERVAL = 50  # check every 30s

# --- INITIALIZATION ---
def init_mongo():
    global MONGO_CLIENT, MONGO_DB, COL_ACTIVE_CHATS, COL_ACTIVE_USERS, COL_LEADERBOARD, USE_MONGO
    try:
        MONGO_CLIENT = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        MONGO_CLIENT.admin.command('ping')
        MONGO_DB = MONGO_CLIENT[MONGO_DB_NAME]
        COL_ACTIVE_CHATS = MONGO_DB['active_chats']
        COL_ACTIVE_USERS = MONGO_DB['active_users']
        COL_LEADERBOARD = MONGO_DB['leaderboard']
        
        COL_ACTIVE_CHATS.create_index('chat_id', unique=True)
        COL_ACTIVE_USERS.create_index('user_id', unique=True)
        COL_LEADERBOARD.create_index('user_id', unique=True)
        
        USE_MONGO = True
        logging.info("✅ Connected to MongoDB.")
    except Exception as e:
        USE_MONGO = False
        logging.error(f"❌ MongoDB connection failed: {e}")

# --- SIMPLE WEB / KEEPALIVE (for Render) ---
# Expose a minimal Flask app as `web_app` so you can run with gunicorn: `gunicorn anime4:web_app`
PORT = int(os.environ.get("PORT", "8000"))
KEEPALIVE_URL = os.environ.get("KEEPALIVE_URL", f"http://localhost:{PORT}/")
KEEPALIVE_INTERVAL = int(os.environ.get("KEEPALIVE_INTERVAL", "600"))

web_app = Flask("anime_keepalive_app")


@web_app.route("/")
def _index():
    return Response("OK", status=200)


@web_app.route("/health")
def _health():
    return Response("OK", status=200)


def _keepalive_loop():
    while True:
        try:
            try:
                with urllib.request.urlopen(KEEPALIVE_URL, timeout=10) as resp:
                    pass
            except Exception:
                # keepalive failures are non-fatal; just log at debug level
                logging.debug(f"Keepalive ping failed to {KEEPALIVE_URL}")
        except Exception:
            logging.exception("Unexpected error in keepalive loop")
        time.sleep(KEEPALIVE_INTERVAL)


# Start keepalive thread at import so Render or other hosts that import this module
# will have the pinger working. It's daemonized so it won't block shutdown.
try:
    _ka_thread = threading.Thread(target=_keepalive_loop, daemon=True)
    _ka_thread.start()
    logging.info("Keepalive thread started.")
except Exception:
    logging.exception("Failed to start keepalive thread")

def load_data():
    global CHAR_STATS, CHAR_IMAGES, ANIME_CHARACTERS, SERIES_MAP, SERIES_DISPLAY
    try:
        if not os.path.exists(CHARACTERS_FILE):
            logging.error(f"❌ {CHARACTERS_FILE} not found!")
            return

        with open(CHARACTERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        for char in data:
            name = char.get("name")
            stats = char.get("stats")
            series = char.get("series", "Unknown")
            img = char.get("img")

            if name and stats:
                CHAR_STATS[name] = stats
                if img: CHAR_IMAGES[name] = img
                
                # Create normalized key for filtering (e.g. "One Piece" -> "onepiece")
                norm_series = re.sub(r'[^a-z0-9]', '', series.lower())
                SERIES_MAP.setdefault(norm_series, []).append(name)
                SERIES_DISPLAY[norm_series] = series

        ANIME_CHARACTERS = list(CHAR_STATS.keys())
        logging.info(f"✅ Loaded {len(ANIME_CHARACTERS)} characters.")
    except Exception as e:
        logging.error(f"❌ Failed to load data: {e}")


def _forfeit_game_actions(chat_id, gid, game):
    # Determine which player failed to act (game['turn']) and award win to opponent
    try:
        if game.get('status') == 'finished':
            return
        turn = game.get('turn')
        p1 = game.get('p1')
        p2 = game.get('p2')
        if not p1 or not p2:
            return
        # Identify who missed their turn and determine winner/loser
        if turn == p1['id']:
            winner, loser = p2, p1
        else:
            winner, loser = p1, p2

        # If the game was never activated (still "waiting"), mark expired
        if game.get('status') != 'active':
            try:
                game['status'] = 'finished'
            except Exception:
                pass
            try:
                # Edit the display message to indicate expiration (do this on app loop)
                if hasattr(app, 'loop') and app.loop is not None:
                    app.loop.call_soon_threadsafe(lambda: asyncio.create_task(
                        ensure_display_message(app, chat_id, game, "❌ Game expired.", reply_markup=None, preview=False)
                    ))
                    # single display/update is sufficient; avoid duplicate sends
            except Exception:
                logging.exception('Failed to update expired display message')
            return

        # Mark finished before leaderboard update to avoid races
        game['status'] = 'finished'

        # Update leaderboard in a p1-relative manner to avoid ordering bugs
        try:
            # result is from p1's perspective: 1 => p1 wins, 0 => p1 loses
            result_for_p1 = 1 if winner['id'] == p1['id'] else 0
            elo_change_p1, elo_change_p2 = update_leaderboard_elo(
                p1['id'], p1.get('name', 'Unknown'), p2['id'], p2.get('name', 'Unknown'), result_for_p1
            )
            logging.info(f"Forfeit ELO updated: p1={p1['id']} change={elo_change_p1}, p2={p2['id']} change={elo_change_p2}")
        except Exception:
            logging.exception('Failed to update leaderboard for forfeit')

        note = f"⏱️ <b>Forfeit:</b> {html.escape(loser.get('name','Unknown'))} did not move. {html.escape(winner.get('name','Unknown'))} wins!"

        # Try to update the existing display message (preferred) or send if unavailable.
        try:
            if hasattr(app, 'loop') and app.loop is not None:
                # Build a fuller display text: keep team display and append the forfeit note.
                try:
                    display_txt = f"{get_team_display(game)}\n\n{note}"
                except Exception:
                    display_txt = note

                # Ensure the coroutine is created on the app loop thread to edit/send message.
                app.loop.call_soon_threadsafe(lambda: asyncio.create_task(
                    ensure_display_message(app, chat_id, game, display_txt, reply_markup=None, preview=False)
                ))
        except Exception:
            logging.exception('Failed to update or send forfeit notification')
    except Exception:
        logging.exception('Error while processing forfeit')


def forfeit_monitor():
    # Background thread that periodically checks for stale games
    while True:
        try:
            time.sleep(FORFEIT_CHECK_INTERVAL)
            now = time.time()
            with GAMES_LOCK:
                for chat_id, games in list(GAMES.items()):
                    for gid, game in list(games.items()):
                        try:
                            if game.get('status') == 'finished':
                                continue
                            last = game.get('last_activity', 0)
                            if last and (now - last) > FORFEIT_TIMEOUT:
                                logging.info(f'Forfeiting game {gid} in chat {chat_id} due to inactivity')
                                _forfeit_game_actions(chat_id, gid, game)
                                # remove the finished game entry
                                try:
                                    GAMES[chat_id].pop(gid, None)
                                except Exception:
                                    pass
                        except Exception:
                            logging.exception('Error checking game for forfeit')
        except Exception:
            logging.exception('Forfeit monitor error')


def load_id_set(filename):
    if USE_MONGO:
        col = COL_ACTIVE_CHATS if filename == CHATS_FILE else COL_ACTIVE_USERS
        key = "chat_id" if filename == CHATS_FILE else "user_id"
        try:
            return set(d[key] for d in col.find({}, {"_id": 0, key: 1}))
        except: return set()
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f: return set(json.load(f))
        except: return set()
    return set()

def save_id_set(filename, id_set):
    if USE_MONGO:
        col = COL_ACTIVE_CHATS if filename == CHATS_FILE else COL_ACTIVE_USERS
        key = "chat_id" if filename == CHATS_FILE else "user_id"
        try:
            if not id_set: return
            for i in id_set:
                try: col.update_one({key: i}, {"$set": {key: i}}, upsert=True)
                except: pass
        except: pass
        return
    try:
        with open(filename, "w") as f: json.dump(list(id_set), f)
    except: pass

init_mongo()
load_data()
ACTIVE_CHATS = load_id_set(CHATS_FILE)
ACTIVE_USERS = load_id_set(USERS_FILE)

# --- PYROGRAM CLIENT ---
app = Client("anime_draft_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Start forfeit monitor thread
try:
    t = threading.Thread(target=forfeit_monitor, daemon=True)
    t.start()
except Exception:
    logging.exception('Failed to start forfeit monitor thread')

# --- RANKING SYSTEM (ELO) ---
def calculate_elo(rating_a, rating_b, actual_score_a):
    """
    K = 32
    actual_score_a = 1 if A wins, 0 if A loses, 0.5 if draw
    """
    K = 32
    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    new_rating_a = rating_a + K * (actual_score_a - expected_a)
    return int(new_rating_a)

def get_user_stats(user_id, name="Unknown"):
    default = {"name": name, "wins": 0, "matches": 0, "rating": 1200}
    try:
        if USE_MONGO:
            u = COL_LEADERBOARD.find_one({"user_id": user_id})
            if u: return u
            return default
        else:
            if os.path.exists(LEADERBOARD_FILE):
                with open(LEADERBOARD_FILE, "r") as f: data = json.load(f)
                return data.get(str(user_id), default)
            return default
    except:
        return default

def update_leaderboard_elo(p1_id, p1_name, p2_id, p2_name, result):
    # result: 1 (p1 wins), 0 (p2 wins), 0.5 (draw)
    u1 = get_user_stats(p1_id, p1_name)
    u2 = get_user_stats(p2_id, p2_name)

    # Ensure ratings exist
    r1 = u1.get("rating", 1200)
    r2 = u2.get("rating", 1200)

    def rank_index(rating):
        if rating < 1000: return 0
        if rating < 1300: return 1
        if rating < 1600: return 2
        if rating < 2000: return 3
        if rating < 2500: return 4
        return 5

    # Defaults
    delta1 = 0
    delta2 = 0

    # Draw: use conservative ELO change via calculate_elo
    if result == 0.5:
        new_r1 = calculate_elo(r1, r2, 0.5)
        new_r2 = calculate_elo(r2, r1, 0.5)
        delta1 = new_r1 - r1
        delta2 = new_r2 - r2
    else:
        # Determine winner/loser and rank difference
        if result == 1:
            winner_rating, loser_rating = r1, r2
            winner_idx = rank_index(r1)
            loser_idx = rank_index(r2)
            diff = winner_idx - loser_idx
            # Same rank
            if diff == 0:
                delta_w, delta_l = 32, -16
            # Winner is one rank higher than loser
            elif diff == 1:
                delta_w, delta_l = 25, -16
            # Winner defeated someone one rank higher
            elif diff == -1:
                delta_w, delta_l = 35, -12
            else:
                # Fallback to standard elo calculation
                new_wr = calculate_elo(r1, r2, 1)
                new_lr = calculate_elo(r2, r1, 0)
                delta_w = new_wr - r1
                delta_l = new_lr - r2

            delta1 = int(delta_w)
            delta2 = int(delta_l)

        else:
            # p2 wins
            winner_rating, loser_rating = r2, r1
            winner_idx = rank_index(r2)
            loser_idx = rank_index(r1)
            diff = winner_idx - loser_idx

            if diff == 0:
                delta_w, delta_l = 32, -16
            elif diff == 1:
                delta_w, delta_l = 25, -16
            elif diff == -1:
                delta_w, delta_l = 35, -12
            else:
                new_wr = calculate_elo(r2, r1, 1)
                new_lr = calculate_elo(r1, r2, 0)
                delta_w = new_wr - r2
                delta_l = new_lr - r1

            # Assign to p1/p2 deltas
            delta2 = int(delta_w)
            delta1 = int(delta_l)

    # If NEW_YEAR_EVENT, losers don't lose rating (negative deltas set to 0)
    if NEW_YEAR_EVENT:
        if delta1 < 0: delta1 = 0
        if delta2 < 0: delta2 = 0

    # Apply updates
    u1["name"] = p1_name
    u2["name"] = p2_name
    u1["matches"] += 1
    u2["matches"] += 1

    if result == 1:
        u1["wins"] += 1
    elif result == 0:
        u2["wins"] += 1

    u1["rating"] = max(0, r1 + int(delta1))
    u2["rating"] = max(0, r2 + int(delta2))

    # Save
    if USE_MONGO:
        u1["user_id"] = p1_id
        u2["user_id"] = p2_id
        COL_LEADERBOARD.update_one({"user_id": p1_id}, {"$set": u1}, upsert=True)
        COL_LEADERBOARD.update_one({"user_id": p2_id}, {"$set": u2}, upsert=True)
    else:
        data = {}
        if os.path.exists(LEADERBOARD_FILE):
            with open(LEADERBOARD_FILE, "r") as f: data = json.load(f)
        data[str(p1_id)] = u1
        data[str(p2_id)] = u2
        with open(LEADERBOARD_FILE, "w") as f: json.dump(data, f)

    return int(u1["rating"] - r1), int(u2["rating"] - r2)

def get_leaderboard_data():
    if USE_MONGO:
        return list(COL_LEADERBOARD.find({}, {"_id": 0}).sort("rating", -1).limit(10))
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, "r") as f: data = json.load(f)
        lst = [{"user_id": k, **v} for k, v in data.items()]
        # Sort by Rating now, not wins
        return sorted(lst, key=lambda x: x.get('rating', 1200), reverse=True)[:10]
    return []


def get_leaderboard_list(limit=16, sort_by='rating'):
    """Return leaderboard list (limit entries) sorted by 'rating' or 'wins'."""
    if USE_MONGO:
        sort_field = 'rating' if sort_by != 'wins' else 'wins'
        cursor = COL_LEADERBOARD.find({}, {"_id": 0}).sort(sort_field, -1).limit(limit)
        return list(cursor)
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        lst = [{"user_id": k, **v} for k, v in data.items()]
        key = (lambda x: x.get('rating', 1200)) if sort_by != 'wins' else (lambda x: x.get('wins', 0))
        return sorted(lst, key=key, reverse=True)[:limit]
    return []

# --- GAME DISPLAY HELPERS ---

def get_team_display(game):
    p1, p2 = game['p1'], game['p2']
    p1_name = html.escape(p1['name'])
    p2_name = html.escape(p2['name'])

    def fmt_role(r, team_dict):
        char = team_dict.get(r, ". . .")
        return f"• {r}: <code>{html.escape(char)}</code>"

    txt = f"🔵 <b>{p1_name}</b>:\n"
    for role in ROLES: txt += fmt_role(role, p1['team']) + "\n"
    txt += f"\n🔴 <b>{p2_name}</b>:\n"
    for role in ROLES: txt += fmt_role(role, p2['team']) + "\n"
    return txt

async def ensure_display_message(client, chat_id, game, text, reply_markup=None, preview=False):
    disp = game.get('display_message')
    kb = InlineKeyboardMarkup(reply_markup) if isinstance(reply_markup, list) else reply_markup
    should_disable_preview = not preview

    if disp:
        try:
            await client.edit_message_text(
                chat_id=disp['chat_id'],
                message_id=disp['msg_id'],
                text=text,
                reply_markup=kb,
                disable_web_page_preview=should_disable_preview,
                parse_mode=ParseMode.HTML
            )
            return
        except FloodWait as e:
            await asyncio.sleep(e.value)
            return await ensure_display_message(client, chat_id, game, text, reply_markup, preview)
        except Exception as e:
            err_str = str(e).lower()
            if "message is not modified" in err_str: return
            if "message to edit not found" not in err_str and "message id invalid" not in err_str:
                return

    try:
        sent = await client.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=kb,
            disable_web_page_preview=should_disable_preview,
            parse_mode=ParseMode.HTML
        )
        game['display_message'] = {'chat_id': sent.chat.id, 'msg_id': sent.id}
    except Exception as e:
        logging.error(f"Failed to send display: {e}")

def switch_turn(game):
    p1_c = len(game["p1"]["team"])
    p2_c = len(game["p2"]["team"])
    curr = game["turn"]
    if curr == game["p1"]["id"]:
        if p2_c < 8: game["turn"] = game["p2"]["id"]
    else:
        if p1_c < 8: game["turn"] = game["p1"]["id"]

# --- MENUS ---

async def show_draw_menu(client, message, game, game_id):
    turn_id = game["turn"]
    p_data = game["p1"] if turn_id == game["p1"]["id"] else game["p2"]
    p_name = html.escape(p_data['name'])
    
    text = (
        f"🏁 <b>Drafting Phase</b>\n\n"
        f"{get_team_display(game)}\n"
        f"🎮 <b>Turn:</b> {p_name}"
    )
    kb = [[InlineKeyboardButton(f"🎲 Draw Character", callback_data=f"action_draw_{game_id}")]]
    await ensure_display_message(client, message.chat.id, game, text, reply_markup=kb, preview=False)

async def show_assignment_menu(client, message, game, char, game_id):
    cp_key = "p1" if game["turn"] == game["p1"]["id"] else "p2"
    team = game[cp_key]["team"]
    skips = game[cp_key]["skips"]
    p_name = html.escape(game[cp_key]["name"])
    
    keyboard = []
    row = []
    for role in ROLES:
        if role not in team:
            row.append(InlineKeyboardButton(f"🟢 {role}", callback_data=f"set_{role}_{game_id}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
    if row: keyboard.append(row)
    if skips > 0:
        keyboard.append([InlineKeyboardButton(f"🗑 Skip ({skips})", callback_data=f"action_skip_{game_id}")])

    DEFAULT_IMG = null
    img_url = CHAR_IMAGES.get(char, DEFAULT_IMG)
    header_link = f'<a href="{img_url}">&#160;</a>'
    
    text = (
        f"{header_link}"
        f"{get_team_display(game)}\n"
        f"✨ <b>{p_name}'s turn</b>\n"
        f"Pulled: <b>{html.escape(char)}</b>\n"
        f"Assign a position:"
    )
    await ensure_display_message(client, message.chat.id, game, text, reply_markup=keyboard, preview=True)

async def finish_game_ui(client, message, game, game_id):
    game["status"] = "finished"
    p1n = html.escape(game['p1']['name'])
    p2n = html.escape(game['p2']['name'])

    p1_status = "✅ READY" if game.get('ready', {}).get('p1') else "⏳ WAITING"
    p2_status = "✅ READY" if game.get('ready', {}).get('p2') else "⏳ WAITING"
    
    text = (
        f"🏁 <b>TEAMS READY!</b> 🏁\n\n"
        f"{get_team_display(game)}\n\n"
        f"⚔️ <b>BOTH PLAYERS MUST CLICK TO START BATTLE</b>"
    )
    kb = [
        [InlineKeyboardButton(f"🔵 {p1n} {p1_status}", callback_data=f"start_rpg_p1_{game_id}")],
        [InlineKeyboardButton(f"🔴 {p2n} {p2_status}", callback_data=f"start_rpg_p2_{game_id}")]
    ]
    await ensure_display_message(client, message.chat.id, game, text, reply_markup=kb, preview=False)

# --- BATTLE LOGIC ---

async def simulate_battle(client, message, game):
    p1, p2 = game["p1"], game["p2"]
    score1, score2 = 0, 0
    log = "🏟 <b>BATTLE ARENA SIMULATION</b>\n\n"
    
    def get_stat(c_name, r_key):
        if not c_name: return 0
        s = CHAR_STATS.get(c_name, {})
        key_map = {
            "Captain": "captain", "Vice Captain": "vice_captain", 
            "Tank": "tank", "Healer": "healer", "Assassin": "assassin", 
            "Support 1": "support", "Support 2": "support", "Traitor": "traitor"
        }
        return s.get(key_map.get(r_key, "captain"), DEFAULT_POWER)

    matchups = [
        ("Captain", "Captain", "⚔️ 1. Captain vs Captain:", 30),
        ("Vice Captain", "Vice Captain", "⚡️ 2. Vice Captain vs Vice Captain:", 25),
        ("Tank", "Tank", "🛡 3. Tank vs Tank:", 15),
        ("Support 1", "Support 1", "🤝 4. Support 1 vs Support 1:", 10),
        ("Support 2", "Support 2", "🤝 5. Support 2 vs Support 2:", 10),
        ("Assassin", "Healer", "💀 6. P1 Assassin vs P2 Healer:", 20),
        ("Healer", "Assassin", "💚 7. P2 Assassin vs P1 Healer:", 20),
    ]

    for r1, r2, title, pts in matchups:
        c1 = p1["team"].get(r1)
        c2 = p2["team"].get(r2)
        log += f"<b>{title}</b>\n"
        if c1 and c2:
            s1 = get_stat(c1, r1) + random.randint(0, 7)
            s2 = get_stat(c2, r2) + random.randint(0, 7)
            
            # Healer bonus: when a Healer faces an Assassin, boost the Healer's stat
            if r1 == "Assassin" and r2 == "Healer":
                # P2 is the Healer in this matchup
                s2 = int(s2 * HEALER_BONUS)
            if r1 == "Healer" and r2 == "Assassin":
                # P1 is the Healer in this matchup
                s1 = int(s1 * HEALER_BONUS)

            if s1 > s2:
                score1 += pts
                log += f"🔵 {html.escape(c1)} def. 🔴 {html.escape(c2)} (+{pts} Pts)\n\n"
            elif s2 > s1:
                score2 += pts
                log += f"🔴 {html.escape(c2)} def. 🔵 {html.escape(c1)} (+{pts} Pts)\n\n"
            else:
                log += f"⚖️ Draw ({html.escape(c1)} vs {html.escape(c2)})\n\n"
        else:
            log += "⚖️ Draw (Missing)\n\n"

    # Traitors
    t1 = p1["team"].get("Traitor")
    log += "🎭 <b>8. P1 Traitor Check:</b> "
    if t1:
        if random.randint(1, 100) < get_stat(t1, "Traitor"):
            score1 -= 30
            log += f"🎭 <b>BETRAYAL!</b> 🔵 {html.escape(t1)} betrayed! (-30 Pts)\n\n"
        else:
            log += f"🔵 {html.escape(t1)} stayed loyal!\n\n"
    else: log += "None.\n\n"
    
    t2 = p2["team"].get("Traitor")
    log += "🎭 <b>9. P2 Traitor Check:</b> "
    if t2:
        if random.randint(1, 100) < get_stat(t2, "Traitor"):
            score2 -= 30
            log += f"🎭 <b>BETRAYAL!</b> 🔴 {html.escape(t2)} betrayed! (-30 Pts)\n\n"
        else:
            log += f"🔴 {html.escape(t2)} stayed loyal!\n\n"
    else: log += "None.\n\n"

    # Winner & Rank Update
    elo_change_p1 = 0
    elo_change_p2 = 0
    winner_name = "Draw"
    
    if score1 > score2:
        winner_name = p1['name']
        elo_change_p1, elo_change_p2 = update_leaderboard_elo(p1['id'], p1['name'], p2['id'], p2['name'], 1)
    elif score2 > score1:
        winner_name = p2['name']
        elo_change_p1, elo_change_p2 = update_leaderboard_elo(p1['id'], p1['name'], p2['id'], p2['name'], 0)
    else:
        elo_change_p1, elo_change_p2 = update_leaderboard_elo(p1['id'], p1['name'], p2['id'], p2['name'], 0.5)

    # Format ELO change
    def fmt_elo(n): return f"+{n}" if n > 0 else str(n)
    
    final = (
        f"{log}"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🔵 <b>Score: {score1}</b> ({fmt_elo(elo_change_p1)})\n"
        f"🔴 <b>Score: {score2}</b> ({fmt_elo(elo_change_p2)})\n\n"
        f"🏆 <b>WINNER: {html.escape(winner_name)}</b>"
    )

    await ensure_display_message(client, message.chat.id, game, final, preview=False)
    with GAMES_LOCK:
        GAMES[message.chat.id].pop(game["game_id"], None)

# --- COMMANDS ---

@app.on_message(filters.command("start"))
async def start_cmd(c, m):
    await m.reply_text(
        "👋 <b>Welcome to Anime Draft Wars!</b>\n\n"
        "Draft a team of 8 anime characters and battle friends!\n"
        "Use /draft to play.\n"
        "Use /guide to learn how to play.",
        parse_mode=ParseMode.HTML
    )

@app.on_message(filters.command("status"))
async def status_cmd(c, m):
    # Calculate counts based on whether Mongo is used or local files
    if USE_MONGO:
        c_count = COL_ACTIVE_CHATS.count_documents({})
        u_count = COL_ACTIVE_USERS.count_documents({})
    else:
        c_count = len(ACTIVE_CHATS)
        u_count = len(ACTIVE_USERS)
        
    await m.reply(
        f"📊 **Bot Statistics**\n\n"
        f"👥 Active Users: **{u_count + 120}**\n"
        f"💬 Active Chats: **{c_count + 50}**"
    )

@app.on_message(filters.command("guide"))
async def guide_cmd(c, m):
    await m.reply_text(
        "📚 <b>Game Guide</b>\n\n"
        "1. <b>Challenge</b>: Reply `/draft` to a user.\n"
        "2. <b>Filter</b>: Use `/draft naruto` to play with only Naruto characters.\n"
        "3. <b>Drafting</b>: Take turns drawing characters.\n"
        "4. <b>Roles</b>:\n"
        "   ⚔️ Captain/Vice: Strongest fighters.\n"
        "   🛡 Tank: Defense.\n"
        "   💚 Healer: Counters Assassins.\n"
        "   💀 Assassin: Counters Healers.\n"
        "   🎭 Traitor: High stats but might betray you!\n\n"
        "5. <b>Winning</b>: Higher score wins. Wins increase your Rank Points!",
        parse_mode=ParseMode.HTML
    )


@app.on_message(filters.command("list"))
async def list_cmd(c, m):
    """Display list of all anime series available for drafting."""
    if not SERIES_DISPLAY:
        return await m.reply_text("📚 No series found.")

    series = sorted(set(SERIES_DISPLAY.values()))
    txt = "📚 <b>Available Anime Series</b>\n\n"
    for s in series:
        txt += f"• {html.escape(s)}\n"

    await m.reply_text(txt, parse_mode=ParseMode.HTML)

@app.on_message(filters.command("profile"))
async def profile_cmd(c, m):
    user = m.from_user
    uid = user.id
    stats = get_user_stats(uid, user.first_name)
    
    wins = stats.get("wins", 0)
    matches = stats.get("matches", 0)
    rating = stats.get("rating", 1200)
    
    wr = round((wins / matches * 100), 1) if matches > 0 else 0
    
    # Determine Rank Title
    if rating < 1000: rank = "🐣 Novice"
    elif rating < 1300: rank = "🥉 Bronze"
    elif rating < 1600: rank = "🥈 Silver"
    elif rating < 2000: rank = "🥇 Gold"
    elif rating < 2500: rank = "💎 Diamond"
    else: rank = "👑 Anime King"
    
    txt = (
        f"👤 <b>Profile: {html.escape(user.first_name)}</b>\n\n"
        f"🏅 <b>Rank:</b> {rank}\n"
        f"💠 <b>Points:</b> {rating}\n"
        f"⚔️ <b>Matches:</b> {matches}\n"
        f"🏆 <b>Wins:</b> {wins}\n"
        f"📈 <b>Win Rate:</b> {wr}%"
    )
    await m.reply(txt, parse_mode=ParseMode.HTML)

@app.on_message(filters.command("acast") & filters.user(ADMIN_IDS))
async def acast_cmd(c, m):
    if len(m.command) < 2:
        return await m.reply("Usage: /acast <message>")
    
    msg = m.text.split(maxsplit=1)[1]
    sent = 0
    failed = 0
    
    await m.reply("📡 Sending broadcast...")
    
    targets = list(ACTIVE_CHATS) # Copy set to list
    
    for chat_id in targets:
        try:
            await c.send_message(chat_id, f"📢 <b>Broadcast</b>\n\n{msg}", parse_mode=ParseMode.HTML)
            sent += 1
            await asyncio.sleep(0.5) # Avoid FloodWait
        except Exception:
            failed += 1
            
    await m.reply(f"✅ Sent to {sent} chats.\n❌ Failed in {failed} chats.")

@app.on_message(filters.command("leaderboard"))
async def lb_cmd(c, m):
    # Default view: sort by points (rating)
    data = get_leaderboard_list(limit=16, sort_by='rating')
    if not data: return await m.reply("📉 No records.")
    txt = "🏆 <b>Global Ranking — Points</b>\n\n"
    for i, u in enumerate(data, 1):
        r = u.get("rating", 1200)
        name = u.get('name', str(u.get('user_id', 'Unknown')))
        txt += f"{i}. <b>{html.escape(name)}</b>: {r} pts\n"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Most Wins", callback_data="lb_toggle_wins")]])
    await m.reply(txt, parse_mode=ParseMode.HTML, reply_markup=kb)


@app.on_message(filters.command("newyear") & filters.user(ADMIN_IDS))
async def newyear_cmd(c, m):
    """Admin command: /newyear on|off — toggle NEW_YEAR_EVENT and persist."""
    global NEW_YEAR_EVENT
    parts = m.text.split()
    if len(parts) < 2:
        return await m.reply(f"NEW_YEAR_EVENT is {'ON' if NEW_YEAR_EVENT else 'OFF'}\nUsage: /newyear on|off")
    arg = parts[1].lower()
    if arg in ("on", "1", "true", "yes"):
        NEW_YEAR_EVENT = True
        try:
            with open(EVENT_FLAGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"NEW_YEAR_EVENT": True}, f)
        except Exception:
            logging.exception('Failed to persist event flag')
        await m.reply("✅ NEW_YEAR_EVENT enabled. Losers will not lose rating.")
    elif arg in ("off", "0", "false", "no"):
        NEW_YEAR_EVENT = False
        try:
            with open(EVENT_FLAGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"NEW_YEAR_EVENT": False}, f)
        except Exception:
            logging.exception('Failed to persist event flag')
        await m.reply("❌ NEW_YEAR_EVENT disabled.")
    else:
        await m.reply("Usage: /newyear on|off")


@app.on_message(filters.command("eventstatus") & filters.user(ADMIN_IDS))
async def eventstatus_cmd(c, m):
    await m.reply(f"NEW_YEAR_EVENT: {'ON' if NEW_YEAR_EVENT else 'OFF'}")

@app.on_message(filters.command("draft"))
async def draft_cmd(c, m):
    if not m.reply_to_message: return await m.reply("⚠️ Reply to a friend!")
    p1, p2 = m.from_user, m.reply_to_message.from_user
    if p2.is_bot or p1.id == p2.id: return await m.reply("⚠️ Invalid opponent.")
    
    # 1. Parse Series Filter
    series_filter = None
    args = m.text.split(maxsplit=1)
    if len(args) > 1:
        # User typed /draft something
        raw_input = re.sub(r'[^a-z0-9]', '', args[1].lower())
        
        # Check if series exists
        if raw_input in SERIES_MAP:
            series_filter = raw_input
        else:
            # Maybe show suggestions?
            examples = ", ".join(list(SERIES_DISPLAY.values())[:5])
            return await m.reply(f"❌ Series not found.\nTry: {examples}...")

    # Tracking
    if USE_MONGO:
        save_id_set(CHATS_FILE, {m.chat.id})
        save_id_set(USERS_FILE, {p1.id, p2.id})

    game_id = f"{m.chat.id}_{random.randint(1000,9999)}"
    
    # Include the filter in game data
    game = {
        "game_id": game_id,
        "status": "waiting",
        "turn": p1.id,
        "last_activity": time.time(),
        "filter": series_filter, # Store the filter
        "p1": {"id": p1.id, "name": p1.first_name, "team": {}, "skips": 2},
        "p2": {"id": p2.id, "name": p2.first_name, "team": {}, "skips": 2},
        "used_chars": [],
        "ready": {"p1": False, "p2": False},
        "battle_started": False
    }
    
    with GAMES_LOCK:
        if m.chat.id not in GAMES: GAMES[m.chat.id] = {}
        GAMES[m.chat.id][game_id] = game

    # Show Series Name in Text
    series_name = SERIES_DISPLAY.get(series_filter, "All Anime") if series_filter else "All Anime"

    kb = [[InlineKeyboardButton("✅ Accept Battle", callback_data=f"accept_{game_id}")]]
    await m.reply(
        f"⚔️ <b>DRAFT CHALLENGE</b>\n"
        f"🎭 <b>Series:</b> {series_name}\n\n"
        f"{html.escape(p1.first_name)} Vs {html.escape(p2.first_name)}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.HTML
    )

@app.on_callback_query()
async def callbacks(c, q: CallbackQuery):
    async with CALLBACK_SEMAPHORE:
        try:
            data, chat_id = q.data, q.message.chat.id

            # Leaderboard toggle handling (not game-specific)
            if data.startswith("lb_toggle_"):
                sort_key = data.split("lb_toggle_")[-1]
                sort_by = 'wins' if sort_key == 'wins' else 'rating'
                lst = get_leaderboard_list(limit=16, sort_by=sort_by)
                if not lst:
                    await q.answer("📉 No records.")
                    return
                title = "Global Ranking — Wins" if sort_by == 'wins' else "Global Ranking — Points"
                txt = f"🏆 <b>{title}</b>\n\n"
                for i, u in enumerate(lst, 1):
                    name = u.get('name', str(u.get('user_id', 'Unknown')))
                    pts = u.get('wins', 0) if sort_by == 'wins' else u.get('rating', 1200)
                    suffix = 'wins' if sort_by == 'wins' else 'pts'
                    txt += f"{i}. <b>{html.escape(name)}</b>: {pts} {suffix}\n"
                # toggle button
                if sort_by == 'wins':
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Points", callback_data="lb_toggle_rating")]])
                else:
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Most Wins", callback_data="lb_toggle_wins")]])
                try:
                    await q.message.edit_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML)
                except Exception:
                    try:
                        await q.message.reply_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
                await q.answer()
                return

            if chat_id not in GAMES:
                return await q.answer("❌ Game not found.", show_alert=True)

            game = None
            for gid, g in GAMES[chat_id].items():
                if data.endswith(gid):
                    game = g
                    break

            if not game:
                # Try to edit the original button message to show expiration with retries for FloodWait.
                txt = "❌ Game expired."
                tried = []
                bot_id = None
                try:
                    me = await c.get_me()
                    bot_id = me.id
                except Exception:
                    logging.exception('get_me() failed')

                # Try editing with up to 3 attempts to handle FloodWait
                for attempt in range(3):
                    try:
                        await q.message.edit_text(txt, reply_markup=None)
                        return
                    except FloodWait as e:
                        logging.warning(f'FloodWait while editing message (attempt {attempt+1}): {e.value}s')
                        await asyncio.sleep(min(5, e.value))
                    except Exception as e:
                        logging.exception('edit_text(q.message) failed')
                        tried.append(f'edit_text: {e}')
                        break

                # Try client-level edit by id
                try:
                    await c.edit_message_text(chat_id=q.message.chat.id, message_id=q.message.id, text=txt, reply_markup=None)
                    return
                except FloodWait as e:
                    logging.warning(f'FloodWait on client.edit_message_text: {e.value}s')
                    await asyncio.sleep(min(5, e.value))
                except Exception as e:
                    logging.exception('client.edit_message_text failed')
                    tried.append(f'client_edit: {e}')

                # If bot is the author of the message, attempt delete+send replacement
                try:
                    if q.message.from_user and bot_id and q.message.from_user.id == bot_id:
                        try:
                            await q.message.delete()
                            await c.send_message(q.message.chat.id, txt)
                            return
                        except Exception as e:
                            logging.exception('delete+send fallback failed')
                            tried.append(f'delete_send: {e}')
                except Exception:
                    logging.exception('delete+send ownership check failed')

                # All edits failed; log diagnostics and fallback to reply or alert
                logging.error('Failed to edit original message for expired game: ' + ' | '.join(tried))
                try:
                    await q.message.reply_text(txt)
                except Exception:
                    return await q.answer(txt, show_alert=True)
                return

            uid, gid = q.from_user.id, game["game_id"]
            # refresh last activity timestamp whenever a callback related to this game is received
            try:
                game['last_activity'] = time.time()
            except Exception:
                pass

            # ACCEPT
            if data.startswith("accept_"):
                if uid != game["p2"]["id"]:
                    return await q.answer("❌ Not for you.", show_alert=True)
                # Mark game active when the challenged user accepts
                try:
                    game['status'] = 'active'
                    game['last_activity'] = time.time()
                except Exception:
                    pass
                await q.message.delete()
                await show_draw_menu(c, q.message, game, gid)
                return

            # START BATTLE
            if data.startswith("start_rpg_"):
                is_p1 = "p1" in data
                # Use lock to avoid race where both press quickly
                with GAMES_LOCK:
                    if (is_p1 and uid == game["p1"]["id"]):
                        game["ready"]["p1"] = True
                    elif (not is_p1 and uid == game["p2"]["id"]):
                        game["ready"]["p2"] = True
                    else:
                        return await q.answer("❌ Wrong button.", show_alert=True)

                    # Update the UI to show who is ready
                    try:
                        await finish_game_ui(c, q.message, game, gid)
                    except Exception:
                        pass

                    # If both are ready and battle not already started, start once
                    if game.get("ready", {}).get("p1") and game.get("ready", {}).get("p2") and not game.get("battle_started"):
                        game["battle_started"] = True
                        # release lock before awaiting long-running simulation
                        # run simulate_battle
                        try:
                            await simulate_battle(c, q.message, game)
                        except Exception:
                            logging.exception('simulate_battle failed')
                    else:
                        await q.answer("✅ Ready! Waiting...")
                return

            # GAME ACTIONS
            if uid != game["turn"]:
                return await q.answer("⏳ Not your turn!", show_alert=True)

            if data.startswith("action_draw_"):
                # --- FILTER LOGIC HERE ---
                pool_key = game.get("filter")

                if pool_key:
                    # Use only specific series
                    base_pool = SERIES_MAP.get(pool_key, [])
                else:
                    # Use ALL characters
                    base_pool = ANIME_CHARACTERS

                # Exclude used characters
                available = [x for x in base_pool if x not in game["used_chars"]]

                if not available:
                    return await q.answer("❌ Pool empty!", show_alert=True)
                char = random.choice(available)
                game["current_draw"] = char
                await show_assignment_menu(c, q.message, game, char, gid)

            elif data.startswith("action_skip_"):
                pkey = "p1" if uid == game["p1"]["id"] else "p2"
                if game[pkey]["skips"] > 0:
                    game[pkey]["skips"] -= 1
                    if game.get("current_draw"):
                        game["used_chars"].append(game["current_draw"])
                        game["current_draw"] = None
                    switch_turn(game)
                    await show_draw_menu(c, q.message, game, gid)
                else:
                    await q.answer("❌ No skips.", show_alert=True)

            elif data.startswith("set_"):
                suffix_len = len(gid) + 1
                role = data[4:-suffix_len]

                if role not in ROLES:
                    return await q.answer("❌ Invalid role.", show_alert=True)
                char = game.get("current_draw")
                if not char:
                    return await q.answer("❌ Error.", show_alert=True)

                pkey = "p1" if uid == game["p1"]["id"] else "p2"
                game[pkey]["team"][role] = char
                game["used_chars"].append(char)
                game["current_draw"] = None

                if len(game["p1"]["team"]) == 8 and len(game["p2"]["team"]) == 8:
                    await finish_game_ui(c, q.message, game, gid)
                else:
                    switch_turn(game)
                    await show_draw_menu(c, q.message, game, gid)

        except Exception as e:
            logging.error(f"Callback error: {e}")
            await q.answer("❌ Error.")

if __name__ == "__main__":
    print("Bot Starting...")
    # If running directly (not via gunicorn), start the Flask web server in a thread
    try:
        web_thread = threading.Thread(target=lambda: web_app.run(host="0.0.0.0", port=PORT), daemon=True)
        web_thread.start()
        logging.info(f"Flask web server started on port {PORT}.")
    except Exception:
        logging.exception("Failed to start Flask web server thread")

    app.run()
