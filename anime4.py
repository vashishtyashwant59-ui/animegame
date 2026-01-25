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
ADMIN_IDS = [6265981509]

LEADERBOARD_FILE = "leaderboard.json"
CHATS_FILE = "active_chats.json"
USERS_FILE = "active_users.json"
CHARACTERS_FILE = "character.json"

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
COL_CHARACTERS = None
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
GAME_CLEANUP_INTERVAL = 180  # Clean up inactive games every 5 minute
GAME_INACTIVITY_TIMEOUT = 600  # Remove games with no user interaction for 10 minutes
FINISHED_GAME_TIMEOUT = 1800  # Remove finished games after 30 minutes

CHAR_STATS = {}
CHAR_IMAGES = {}
CHAR_RARITY = {}
ANIME_CHARACTERS = []
SERIES_MAP = {}
SERIES_DISPLAY = {}

# Pokemon Draft Globals
POKEMON_DATA = {}
POKEMON_LIST = []

# Default image used when a character has no image
DEFAULT_CHAR_IMG = "https://files.catbox.moe/wahm05.jpg"

DEFAULT_POWER = 50
ROLES = ["Captain", "Vice Captain", "Tank", "Healer", "Assassin", "Support 1", "Support 2", "Traitor"]

# Multiplier applied to Healer when facing an Assassin
HEALER_BONUS = 2.3

# --- POKEMON DRAFT CONFIGURATION ---
POKEMON_ROLES = ["HP", "Atk", "Def", "SpA", "SpD", "Spe", "Type"]
STAT_MAP = {
    "HP": "hp",
    "Atk": "attack",
    "Def": "defense",
    "SpA": "special-attack",
    "SpD": "special-defense",
    "Spe": "speed"
}
POKEMON_FILE = "pokemon.json"
POKEMON_LEVEL = 50
MOVE_POWER = 50
ASSIGN_TIMER_DURATION = 15
MAX_ACTIVE_DRAFTS_PER_CHAT = 50

# --- TYPE EFFECTIVENESS CHART FOR POKEMON ---
TYPE_CHART = {
    'Normal': {'Rock': 0.5, 'Ghost': 0, 'Steel': 0.5},
    'Fire': {'Fire': 0.5, 'Water': 0.5, 'Grass': 2, 'Ice': 2, 'Bug': 2, 'Rock': 0.5, 'Dragon': 0.5, 'Steel': 2},
    'Water': {'Fire': 2, 'Water': 0.5, 'Grass': 0.5, 'Ground': 2, 'Rock': 2, 'Dragon': 0.5},
    'Electric': {'Water': 2, 'Electric': 0.5, 'Grass': 0.5, 'Ground': 0, 'Flying': 2, 'Dragon': 0.5},
    'Grass': {'Fire': 0.5, 'Water': 2, 'Grass': 0.5, 'Poison': 0.5, 'Ground': 2, 'Flying': 0.5, 'Bug': 0.5, 'Rock': 2, 'Dragon': 0.5, 'Steel': 0.5},
    'Ice': {'Fire': 0.5, 'Water': 0.5, 'Grass': 2, 'Ice': 0.5, 'Ground': 2, 'Flying': 2, 'Dragon': 2, 'Steel': 0.5},
    'Fighting': {'Normal': 2, 'Ice': 2, 'Poison': 0.5, 'Flying': 0.5, 'Psychic': 0.5, 'Bug': 0.5, 'Rock': 2, 'Ghost': 0, 'Dark': 2, 'Steel': 2, 'Fairy': 0.5},
    'Poison': {'Grass': 2, 'Poison': 0.5, 'Ground': 0.5, 'Rock': 0.5, 'Ghost': 0.5, 'Steel': 0, 'Fairy': 2},
    'Ground': {'Fire': 2, 'Electric': 2, 'Grass': 0.5, 'Poison': 2, 'Flying': 0, 'Bug': 0.5, 'Rock': 2, 'Steel': 2},
    'Flying': {'Electric': 0.5, 'Grass': 2, 'Fighting': 2, 'Bug': 2, 'Rock': 0.5, 'Steel': 0.5},
    'Psychic': {'Fighting': 2, 'Poison': 2, 'Psychic': 0.5, 'Dark': 0, 'Steel': 0.5},
    'Bug': {'Fire': 0.5, 'Grass': 2, 'Fighting': 0.5, 'Poison': 0.5, 'Flying': 0.5, 'Psychic': 2, 'Ghost': 0.5, 'Dark': 2, 'Steel': 0.5, 'Fairy': 0.5},
    'Rock': {'Fire': 2, 'Ice': 2, 'Fighting': 0.5, 'Ground': 0.5, 'Flying': 2, 'Bug': 2, 'Steel': 0.5},
    'Ghost': {'Normal': 0, 'Psychic': 2, 'Ghost': 2, 'Dark': 0.5},
    'Dragon': {'Dragon': 2, 'Steel': 0.5, 'Fairy': 0},
    'Dark': {'Psychic': 2, 'Ghost': 2, 'Dark': 0.5, 'Fighting': 0.5, 'Fairy': 0.5},
    'Steel': {'Ice': 2, 'Rock': 2, 'Fairy': 2, 'Fire': 0.5, 'Water': 0.5, 'Electric': 0.5, 'Steel': 0.5},
    'Fairy': {'Fighting': 2, 'Dragon': 2, 'Dark': 2, 'Fire': 0.5, 'Poison': 0.5, 'Steel': 0.5}
}

# Forfeit settings (seconds)
FORFEIT_TIMEOUT = 5 * 60  # 5 minutes
FORFEIT_CHECK_INTERVAL = 50  # check every 30s

# --- INITIALIZATION ---
def init_mongo():
    global MONGO_CLIENT, MONGO_DB, COL_ACTIVE_CHATS, COL_ACTIVE_USERS, COL_LEADERBOARD, COL_CHARACTERS, USE_MONGO
    try:
        MONGO_CLIENT = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        MONGO_CLIENT.admin.command('ping')
        MONGO_DB = MONGO_CLIENT[MONGO_DB_NAME]
        COL_ACTIVE_CHATS = MONGO_DB['active_chats']
        COL_ACTIVE_USERS = MONGO_DB['active_users']
        COL_LEADERBOARD = MONGO_DB['leaderboard']
        COL_CHARACTERS = MONGO_DB['characters']

        # Create indexes, handling conflicts gracefully
        try:
            COL_ACTIVE_CHATS.create_index('chat_id', unique=True)
            COL_ACTIVE_USERS.create_index('user_id', unique=True)
            COL_LEADERBOARD.create_index('user_id', unique=True)
        except:
            pass
        
        try:
            COL_CHARACTERS.create_index('name', unique=True)
        except:
            # Index may already exist as non-unique, drop and recreate
            try:
                COL_CHARACTERS.drop_index('name_1')
                COL_CHARACTERS.create_index('name', unique=True)
            except:
                pass
        
        try:
            COL_CHARACTERS.create_index('series')
        except:
            pass

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
        data = []
        
        # Try loading from MongoDB first
        if USE_MONGO and COL_CHARACTERS is not None:
            try:
                data = list(COL_CHARACTERS.find({}))
                logging.info(f"📚 Loaded {len(data)} characters from MongoDB.")
            except Exception as e:
                logging.warning(f"Failed to load from MongoDB: {e}. Falling back to JSON.")
                data = []
        
        # Fallback to JSON file if MongoDB is not available
        if not data and os.path.exists(CHARACTERS_FILE):
            with open(CHARACTERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            logging.info(f"📄 Loaded {len(data)} characters from {CHARACTERS_FILE}.")
        
        if not data:
            logging.error(f"❌ No characters found in MongoDB or {CHARACTERS_FILE}!")
            return

        for char in data:
            name = char.get("name")
            stats = char.get("stats")
            series = char.get("series", "Unknown")
            img = char.get("img")

            if name and stats:
                # Create a unique identifier combining name and series
                unique_char_id = f"{name} | {series}"
                
                CHAR_STATS[unique_char_id] = stats
                # store image if provided
                if img:
                    CHAR_IMAGES[unique_char_id] = img

                # Create normalized key for filtering (e.g. "One Piece" -> "onepiece")
                norm_series = re.sub(r'[^a-z0-9]', '', series.lower())
                SERIES_MAP.setdefault(norm_series, []).append(unique_char_id)
                SERIES_DISPLAY[norm_series] = series

        ANIME_CHARACTERS = list(CHAR_STATS.keys())
        logging.info(f"✅ Loaded {len(ANIME_CHARACTERS)} characters.")
    except Exception as e:
        logging.error(f"❌ Failed to load data: {e}")


def load_pokemon_data():
    global POKEMON_DATA, POKEMON_LIST
    try:
        if os.path.exists(POKEMON_FILE):
            with open(POKEMON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for p in data:
                if all(k in p for k in ["name", "stats", "types", "region", "is_legendary"]):
                    POKEMON_DATA[p["name"]] = {
                        "stats": p["stats"],
                        "types": p["types"],
                        "region": p["region"],
                        "is_legendary": p["is_legendary"]
                    }
                    POKEMON_LIST.append(p["name"])
            logging.info(f"✅ Loaded {len(POKEMON_LIST)} Pokémon from {POKEMON_FILE}.")
        else:
            logging.error(f"❌ {POKEMON_FILE} not found! Pokemon Draft will not have any Pokémon to draft.")
    except Exception as e:
        logging.error(f"❌ Failed to load Pokémon data: {e}")


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
                # Send a simple chat notification about expiration by editing the original message
                note = "⏳ Game expired due to inactivity."
                disp = game.get('display_message')
                if hasattr(app, 'loop') and app.loop is not None and disp:
                     app.loop.call_soon_threadsafe(lambda: asyncio.create_task(
                         app.edit_message_text(chat_id, disp['msg_id'], f"~~~\n{note}", reply_markup=None)
                     ))
                elif hasattr(app, 'loop') and app.loop is not None:
                     app.loop.call_soon_threadsafe(lambda: asyncio.create_task(
                        app.send_message(chat_id, note)
                    ))
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


def cleanup_old_games():
    """Cleanup inactive and finished games from memory to prevent memory bloat"""
    while True:
        try:
            time.sleep(GAME_CLEANUP_INTERVAL)
            now = time.time()
            removed_count = 0
            removed_details = {}
            
            with GAMES_LOCK:
                for chat_id, games in list(GAMES.items()):
                    for gid, game in list(games.items()):
                        try:
                            last_activity = game.get('last_activity', 0)
                            inactivity_duration = (now - last_activity) if last_activity else float('inf')
                            game_status = game.get('status', 'unknown')
                            
                            should_remove = False
                            reason = ""
                            
                            # Remove if game is inactive (no user interaction) for too long
                            if inactivity_duration > GAME_INACTIVITY_TIMEOUT:
                                should_remove = True
                                reason = "inactivity"
                            # Remove finished games after they've been around for a while
                            elif game_status == 'finished' and inactivity_duration > FINISHED_GAME_TIMEOUT:
                                should_remove = True
                                reason = "finished_timeout"
                            
                            if should_remove:
                                # Cancel any pending async tasks
                                try:
                                    task = game.get('timer_task')
                                    if task and not task.done():
                                        task.cancel()
                                except:
                                    pass
                                
                                p1_name = game.get('p1', {}).get('name', 'Unknown')
                                p2_name = game.get('p2', {}).get('name', 'Unknown')
                                removed_details[f"{p1_name}_vs_{p2_name}"] = reason
                                
                                GAMES[chat_id].pop(gid, None)
                                removed_count += 1
                        except Exception:
                            logging.exception(f'Error cleaning up game {gid}')
                    
                    # Remove empty chat entries
                    if not games:
                        GAMES.pop(chat_id, None)
            
            if removed_count > 0:
                logging.info(f'Cleaned up {removed_count} inactive/finished games: {removed_details}')
        except Exception:
            logging.exception('Game cleanup error')


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

# Start game cleanup thread
try:
    cleanup_t = threading.Thread(target=cleanup_old_games, daemon=True)
    cleanup_t.start()
    logging.info("Game cleanup thread started.")
except Exception:
    logging.exception('Failed to start game cleanup thread')

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

    r1 = u1.get("rating", 1200)
    r2 = u2.get("rating", 1200)

    def rank_index(rating):
        if rating < 1000: return 0
        if rating < 1300: return 1
        if rating < 1600: return 2
        if rating < 2000: return 3
        if rating < 2500: return 4
        return 5

    delta1, delta2 = 0, 0

    if result == 0.5:
        # Per user request, draws result in 0 point change
        delta1, delta2 = 0, 0
    else:
        if result == 1: # p1 wins
            winner_idx, loser_idx = rank_index(r1), rank_index(r2)
            diff = winner_idx - loser_idx

            if diff >= 2:    # Winner is 2+ ranks higher
                delta_w, delta_l = 16, -10
            elif diff == 1:  # Winner is 1 rank higher
                delta_w, delta_l = 20, -15
            elif diff == 0:  # Same rank
                delta_w, delta_l = 28, -20
            else:            # Winner is lower rank (upset)
                delta_w, delta_l = 35, -12

            delta1, delta2 = int(delta_w), int(delta_l)
        else: # p2 wins
            winner_idx, loser_idx = rank_index(r2), rank_index(r1)
            diff = winner_idx - loser_idx

            if diff >= 2:
                delta_w, delta_l = 16, -10
            elif diff == 1:
                delta_w, delta_l = 20, -15
            elif diff == 0:
                delta_w, delta_l = 28, -20
            else: # Winner is lower rank (upset)
                delta_w, delta_l = 35, -12

            delta2, delta1 = int(delta_w), int(delta_l)

    if NEW_YEAR_EVENT:
        if delta1 < 0: delta1 = 0
        if delta2 < 0: delta2 = 0

    u1["name"], u2["name"] = p1_name, p2_name
    u1["matches"] += 1
    u2["matches"] += 1
    if result == 1: u1["wins"] += 1
    elif result == 0: u2["wins"] += 1
    u1["rating"] = max(0, r1 + delta1)
    u2["rating"] = max(0, r2 + delta2)

    if USE_MONGO:
        u1["user_id"], u2["user_id"] = p1_id, p2_id
        COL_LEADERBOARD.update_one({"user_id": p1_id}, {"$set": u1}, upsert=True)
        COL_LEADERBOARD.update_one({"user_id": p2_id}, {"$set": u2}, upsert=True)
    else:
        data = {}
        if os.path.exists(LEADERBOARD_FILE):
            with open(LEADERBOARD_FILE, "r") as f: data = json.load(f)
        data[str(p1_id)], data[str(p2_id)] = u1, u2
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

# --- DECK HELPERS (no rarity) ---
def generate_deck(pool, size=8):
    """Simple deck generator: choose up to `size` unique characters from pool.
    If the pool has fewer unique characters than `size`, allow duplicates as fallback.
    """
    pool = list(pool) if pool else []
    pool = [p for p in pool if p is not None]
    if not pool:
        return []

    unique = list(dict.fromkeys(pool))
    if len(unique) >= size:
        deck = random.sample(unique, size)
    else:
        deck = []
        while len(deck) < size:
            deck.append(random.choice(pool))

    random.shuffle(deck)
    return deck[:size]


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

def get_team_display(game, show_pending=False):
    p1, p2 = game['p1'], game['p2']
    p1_name = html.escape(p1['name'])
    p2_name = html.escape(p2['name'])

    def fmt_role(r, team_dict):
        unique_char_id = team_dict.get(r)
        if not unique_char_id and show_pending:
            # Check if this role is the one currently being picked
            r_index = game.get('current_role_index', 0)
            if r_index < len(game.get('roles_order', [])) and game['roles_order'][r_index] == r:
                 char_display = "❓ Picking..."
            else:
                 char_display = ". . ."
        elif not unique_char_id:
            char_display = ". . ."
        else:
            # Extract the name part from the unique ID (format: "name | series")
            char_display = unique_char_id.split(' | ')[0]
        return f"• {r}: <code>{html.escape(char_display)}</code>"

    txt = f"🔵 <b>{p1_name}'s Team</b>:\n"
    for role in ROLES: txt += fmt_role(role, p1['team']) + "\n"
    txt += f"\n🔴 <b>{p2_name}'s Team</b>:\n"
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
            # If message cannot be edited (deleted, expired, etc), do NOT send a new message
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

    if game.get('mode') == 'draft_v2':
        r_index = game.get('current_role_index', 0)
        if r_index >= len(game.get('roles_order', [])):
            await finish_game_ui(client, message, game, game_id)
            return

        role_key = game['roles_order'][r_index]
        pkey = 'p1' if turn_id == game['p1']['id'] else 'p2'
        deck = game[f'deck_{pkey}']
        assigned_chars = set(game[f'assigned_{pkey}'])
        available_deck = [c for c in deck if c not in assigned_chars]

        # --- Public message in group chat ---
        # Extract names from unique IDs for display (format: "name | series")
        p1_deck_str = "\n".join(f"• {html.escape(c.split(' | ')[0])}" for c in game['deck_p1'])
        p2_deck_str = "\n".join(f"• {html.escape(c.split(' | ')[0])}" for c in game['deck_p2'])

        public_text = (
            f"<b>Deck Duel Drafting Phase</b>\n\n"
            f"🔵 <b>{html.escape(game['p1']['name'])}'s Deck:</b>\n{p1_deck_str}\n\n"
            f"🔴 <b>{html.escape(game['p2']['name'])}'s Deck:</b>\n{p2_deck_str}\n\n"
            f"Waiting for <b>{p_name}</b> to secretly pick their <b>{role_key}</b>..."
        )
        await ensure_display_message(client, message.chat.id, game, public_text, reply_markup=None, preview=False)

        # --- Private message (DM) with pick buttons ---
        keyboard = []
        row = []
        for i, card in enumerate(available_deck):
            # Use the index of the card in the available_deck list for the callback
            # Extract name from unique ID for display
            card_name_display = card.split(' | ')[0]
            # --- BUG FIX: Standardized callback format ---
            row.append(InlineKeyboardButton(f"{card_name_display}", callback_data=f"assign_{game_id}_{r_index}_{i}"))
            # --- END BUG FIX ---
            if len(row) == 2:
                keyboard.append(row); row = []
        if row: keyboard.append(row)

        try:
            await client.send_message(
                turn_id,
                f"🕵️ <b>Secret Pick</b>\n\nChoose your <b>{role_key}</b> from your available cards:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await client.send_message(message.chat.id, f"⚠️ {p_name}, I can't DM you. Please start a chat with me privately and try again.")
        return
    else:
        # Regular draft mode
        text = (
            f"🏁 <b>Drafting Phase</b>\n\n"
            f"{get_team_display(game)}\n"
            f"🎮 <b>Turn:</b> {p_name}"
        )
        # --- BUG FIX: Standardized callback format ---
        kb = [[InlineKeyboardButton(f"🎲 Draw Character", callback_data=f"draw_{game_id}")]]
        # --- END BUG FIX ---
        await ensure_display_message(client, message.chat.id, game, text, reply_markup=kb, preview=False)

async def show_assignment_menu(client, message, game, unique_char_id, game_id):
    cp_key = "p1" if game["turn"] == game["p1"]["id"] else "p2"
    team = game[cp_key]["team"]
    skips = game[cp_key]["skips"]
    p_name = html.escape(game[cp_key]["name"])

    keyboard = []
    row = []
    for role in ROLES:
        if role not in team:
            # --- BUG FIX: Standardized callback format ---
            # Using dashes instead of spaces in roles for safe parsing
            safe_role = role.replace(' ', '-')
            row.append(InlineKeyboardButton(f"🟢 {role}", callback_data=f"set_{game_id}_{safe_role}"))
            # --- END BUG FIX ---
            if len(row) == 2:
                keyboard.append(row)
                row = []
    if row: keyboard.append(row)
    if skips > 0:
        # --- BUG FIX: Standardized callback format ---
        keyboard.append([InlineKeyboardButton(f"🗑 Skip ({skips})", callback_data=f"skip_{game_id}")])
        # --- END BUG FIX ---

    DEFAULT_IMG = "https://files.catbox.moe/t3d359.jpg"
    img_url = CHAR_IMAGES.get(unique_char_id, DEFAULT_IMG)
    header_link = f'<a href="{img_url}">&#160;</a>'
    
    # Extract the name part from the unique ID (format: "name | series")
    char_name_for_display = unique_char_id.split(' | ')[0]

    text = (
        f"{header_link}"
        f"{get_team_display(game)}\n"
        f"✨ <b>{p_name}'s turn</b>\n"
        f"Pulled: <b>{html.escape(char_name_for_display)}</b>\n"
        f"Assign a position:"
    )
    await ensure_display_message(client, message.chat.id, game, text, reply_markup=keyboard, preview=True)

async def finish_game_ui(client, message, game, game_id):
    game["status"] = "finished"
    p1n = html.escape(game['p1']['name'])
    p2n = html.escape(game['p2']['name'])

    p1_status = "✅ READY" if game.get('ready', {}).get('p1') else "⏳ WAITING"
    p2_status = "✅ READY" if game.get('ready', {}).get('p2') else "⏳ WAITING"

    team_display_text = get_team_display(game)

    text = (
        f"🏁 <b>TEAMS READY!</b> 🏁\n\n"
        f"{team_display_text}\n\n"
        f"⚔️ <b>BOTH PLAYERS MUST CLICK TO START BATTLE</b>"
    )
    # --- BUG FIX: Standardized callback format ---
    kb = [
        [InlineKeyboardButton(f"🔵 {p1n} {p1_status}", callback_data=f"startrpg_{game_id}_p1")],
        [InlineKeyboardButton(f"🔴 {p2n} {p2_status}", callback_data=f"startrpg_{game_id}_p2")]
    ]
    # --- END BUG FIX ---
    await ensure_display_message(client, message.chat.id, game, text, reply_markup=kb, preview=False)

# --- BATTLE LOGIC ---

async def simulate_battle(client, message, game):
    p1, p2 = game["p1"], game["p2"]
    score1, score2 = 0, 0
    log = "🏟 <b>BATTLE ARENA SIMULATION</b>\n\n"

    def get_stat(unique_char_id, r_key):
        if not unique_char_id: return 0
        s = CHAR_STATS.get(unique_char_id, {})
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
        c1_id = p1["team"].get(r1)
        c2_id = p2["team"].get(r2)
        log += f"<b>{title}</b>\n"
        if c1_id and c2_id:
            s1 = get_stat(c1_id, r1)
            s2 = get_stat(c2_id, r2)

            # Healer bonus: when a Healer faces an Assassin, boost the Healer's stat
            if r1 == "Assassin" and r2 == "Healer":
                # P2 is the Healer in this matchup
                s2 = int(s2 * HEALER_BONUS)
            if r1 == "Healer" and r2 == "Assassin":
                # P1 is the Healer in this matchup
                s1 = int(s1 * HEALER_BONUS)

            # Extract display names from unique IDs
            c1_display = c1_id.split(' | ')[0]
            c2_display = c2_id.split(' | ')[0]

            if s1 > s2:
                score1 += pts
                log += f"🔵 {html.escape(c1_display)} def. 🔴 {html.escape(c2_display)} (+{pts} Pts)\n\n"
            elif s2 > s1:
                score2 += pts
                log += f"🔴 {html.escape(c2_display)} def. 🔵 {html.escape(c1_display)} (+ {pts} Pts)\n\n"
            else:
                log += f"⚖️ Draw ({html.escape(c1_display)} vs {html.escape(c2_display)})\n\n"
        else:
            log += "⚖️ Draw (Missing)\n\n"

    # Traitors
    t1_id = p1["team"].get("Traitor")
    log += "🎭 <b>8. P1 Traitor Check:</b> "
    if t1_id:
        if random.randint(1, 100) < get_stat(t1_id, "Traitor"):
            score1 -= 30
            t1_display = t1_id.split(' | ')[0]
            log += f"🎭 <b>BETRAYAL!</b> 🔵 {html.escape(t1_display)} betrayed! (-30 Pts)\n\n"
        else:
            t1_display = t1_id.split(' | ')[0]
            log += f"🔵 {html.escape(t1_display)} stayed loyal!\n\n"
    else: log += "None.\n\n"

    t2_id = p2["team"].get("Traitor")
    log += "🎭 <b>9. P2 Traitor Check:</b> "
    if t2_id:
        if random.randint(1, 100) < get_stat(t2_id, "Traitor"):
            score2 -= 30
            t2_display = t2_id.split(' | ')[0]
            log += f"🎭 <b>BETRAYAL!</b> 🔴 {html.escape(t2_display)} betrayed! (-30 Pts)\n\n"
        else:
            t2_display = t2_id.split(' | ')[0]
            log += f"🔴 {html.escape(t2_display)} stayed loyal!\n\n"
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
        try:
            # Cancel any pending tasks
            task = game.get('timer_task')
            if task and not task.done():
                task.cancel()
            # Mark as finished instead of removing immediately - cleanup thread will handle it
            game['status'] = 'finished'
            game['last_activity'] = time.time()
        except Exception as e:
            logging.error(f"Error cleaning up game: {e}")

# --- POKEMON DRAFT HELPER FUNCTIONS ---

def get_best_move_info(attacker_types, defender_types):
    """Determines the best move type for an attacker and calculates the damage multiplier."""
    best_multiplier = -1
    best_type = attacker_types[0]

    for move_type in attacker_types:
        current_multiplier = 1.0
        for def_type in defender_types:
            effectiveness = TYPE_CHART.get(move_type, {}).get(def_type, 1.0)
            current_multiplier *= effectiveness
        
        if current_multiplier > best_multiplier:
            best_multiplier = current_multiplier
            best_type = move_type
    
    return best_type, best_multiplier

def calculate_damage(attack_stat, defense_stat, move_type, attacker_types, type_multiplier):
    """Calculates damage based on a simplified official Pokémon formula."""
    stab = 1.5 if move_type in attacker_types else 1.0
    damage = (((((2 * POKEMON_LEVEL / 5) + 2) * MOVE_POWER * (attack_stat / defense_stat)) / 50) + 2) * stab * type_multiplier
    return max(1, int(damage))

def simulate_matchup(attacker, defender):
    """Simulates a 1v1 matchup and returns the winner based on turns to KO and speed."""
    move_type_A, type_mult_A = get_best_move_info(attacker['types'], defender['types'])
    damage_A = calculate_damage(attacker['atk'], defender['def'], move_type_A, attacker['types'], type_mult_A)
    turns_to_ko_defender = math.ceil(defender['hp'] / damage_A)

    move_type_D, type_mult_D = get_best_move_info(defender['types'], attacker['types'])
    damage_D = calculate_damage(defender['atk'], attacker['def'], move_type_D, defender['types'], type_mult_D)
    turns_to_ko_attacker = math.ceil(attacker['hp'] / damage_D)

    if turns_to_ko_defender < turns_to_ko_attacker:
        winner = 'attacker'
    elif turns_to_ko_attacker < turns_to_ko_defender:
        winner = 'defender'
    else:
        winner = 'attacker' if attacker['spe'] > defender['spe'] else 'defender' if defender['spe'] > attacker['spe'] else 'draw'

    return {
        "winner": winner,
        "attacker_turns": turns_to_ko_defender, "attacker_damage": damage_A,
        "defender_turns": turns_to_ko_attacker, "defender_damage": damage_D,
    }

async def pokemon_ensure_display_message(client, chat_id, game, text, reply_markup=None):
    """Helper to send or edit display messages for Pokemon draft."""
    disp = game.get('display_message')
    kb = InlineKeyboardMarkup(reply_markup) if isinstance(reply_markup, list) else reply_markup
    try:
        if disp:
            await client.edit_message_text(chat_id=disp['chat_id'], message_id=disp['msg_id'], text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
        else:
            sent = await client.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
            game['display_message'] = {'chat_id': sent.chat.id, 'msg_id': sent.id}
    except:
        pass

def pokemon_get_team_display(game):
    """Generate team display for Pokemon draft."""
    p1, p2 = game['p1'], game['p2']
    p1_name, p2_name = html.escape(p1['name']), html.escape(p2['name'])

    def format_stat_line(role, team_dict):
        entry = team_dict.get(role)
        if role == "Type":
            if entry:
                types_str = " / ".join(entry['types'])
                return f"• Type: <code>{types_str} ({html.escape(entry['pokemon'])})</code>"
            return "• Type: <code>...</code>"
        else:
            if entry:
                return f"• {role}: <code>{entry['value']} ({html.escape(entry['pokemon'])})</code>"
            return f"• {role}: <code>...</code>"

    txt = f"🔵 <b>{p1_name}'s Build</b>:\n" + "\n".join(format_stat_line(r, p1['team']) for r in POKEMON_ROLES)
    txt += f"\n\n🔴 <b>{p2_name}'s Build</b>:\n" + "\n".join(format_stat_line(r, p2['team']) for r in POKEMON_ROLES)
    return txt

def pokemon_switch_turn(game):
    """Switch turn between players in Pokemon draft."""
    p1, p2 = game['p1'], game['p2']
    role_count = len(POKEMON_ROLES)
    if len(p1["team"]) == role_count and len(p2["team"]) == role_count: return

    next_player_id = p2["id"] if game["turn"] == p1["id"] else p1["id"]
    if next_player_id == p1['id'] and len(p1['team']) == role_count:
        game["turn"] = p2['id']
    elif next_player_id == p2['id'] and len(p2['team']) == role_count:
        game["turn"] = p1['id']
    else:
        game["turn"] = next_player_id

async def pokemon_show_draw_menu(client, message, game, game_id):
    """Display draw menu for Pokemon draft."""
    p_name = html.escape(game["p1" if game["turn"] == game["p1"]["id"] else "p2"]['name'])
    text = f"🏁 <b>Drafting Phase</b>\n\n{pokemon_get_team_display(game)}\n\n🎮 <b>Turn:</b> {p_name}"
    kb = [[InlineKeyboardButton("🎲 Draw Pokémon", callback_data=f"pdraw_{game_id}")]]
    await pokemon_ensure_display_message(client, message.chat.id, game, text, reply_markup=kb)

async def pokemon_auto_assign_task(client, message, game_id):
    """Auto-assign Pokemon if player doesn't choose."""
    await asyncio.sleep(ASSIGN_TIMER_DURATION)
    with GAMES_LOCK:
        game = next((g for games in GAMES.values() for g_id, g in games.items() if g_id == game_id), None)
        if not game or not game.get("current_draw"): return

        pokemon_name = game["current_draw"]
        pkey = "p1" if game["turn"] == game["p1"]["id"] else "p2"
        team = game[pkey]["team"]
        available_roles = [role for role in POKEMON_ROLES if role not in team]
        
        if not available_roles: return

        role_to_assign = random.choice(available_roles)
        pokemon_info = POKEMON_DATA.get(pokemon_name)

        if role_to_assign == "Type":
            game[pkey]["team"][role_to_assign] = {"pokemon": pokemon_name, "types": pokemon_info["types"]}
        elif role_to_assign in STAT_MAP:
            stat_key = STAT_MAP[role_to_assign]
            game[pkey]["team"][role_to_assign] = {"pokemon": pokemon_name, "value": pokemon_info["stats"][stat_key]}

        game["used_players"].append(pokemon_name)
        game["current_draw"] = None
        game['timer_task'] = None

        await client.send_message(
            message.chat.id,
            f"⏰ <b>Time's up!</b> {html.escape(pokemon_name)} was automatically assigned to <b>{role_to_assign}</b> for {html.escape(game[pkey]['name'])}."
        )

        role_count = len(POKEMON_ROLES)
        if len(game["p1"]["team"]) == role_count and len(game["p2"]["team"]) == role_count:
            await pokemon_finish_game_ui(client, message, game, game_id)
        else:
            pokemon_switch_turn(game)
            await pokemon_show_draw_menu(client, message, game, game_id)

async def pokemon_show_assignment_menu(client, message, game, pokemon, game_id):
    """Display assignment menu for Pokemon draft."""
    cp_key = "p1" if game["turn"] == game["p1"]["id"] else "p2"
    team, skips, p_name = game[cp_key]["team"], game[cp_key]["skips"], html.escape(game[cp_key]["name"])

    keyboard, row = [], []
    for role in POKEMON_ROLES:
        if role not in team:
            row.append(InlineKeyboardButton(f"🟢 {role}", callback_data=f"pset_{game_id}_{role}"))
            if len(row) >= 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    if skips > 0: keyboard.append([InlineKeyboardButton(f"🗑 Skip ({skips})", callback_data=f"pskip_{game_id}")])

    text = f"{pokemon_get_team_display(game)}\n\n✨ <b>{p_name}'s turn</b>\nPulled: <b>{html.escape(pokemon)}</b>\nAssign a stat slot (<b>{ASSIGN_TIMER_DURATION}s</b>):"
    await pokemon_ensure_display_message(client, message.chat.id, game, text, reply_markup=keyboard)

    if game.get('timer_task'): game['timer_task'].cancel()
    task = asyncio.create_task(pokemon_auto_assign_task(client, message, game_id))
    game['timer_task'] = task

async def pokemon_finish_game_ui(client, message, game, game_id):
    """Show teams are ready for battle."""
    game["status"] = "awaiting_start"
    text = f"🏁 <b>TEAMS READY!</b> 🏁\n\n{pokemon_get_team_display(game)}\n\n⚔️ Click below to start the battle!"
    kb = [[InlineKeyboardButton("💥 Start Battle", callback_data=f"pstartbattle_{game_id}")]]
    await pokemon_ensure_display_message(client, message.chat.id, game, text, reply_markup=kb)

async def pokemon_simulate_battle(client, message, game):
    """Simulate Pokemon battle and determine winner."""
    p1, p2 = game["p1"], game["p2"]
    score1, score2 = 0, 0
    log = "🏟 <b>BATTLE SIMULATION</b>\n\n"

    # Phase 1: HP vs HP
    log += "❤️‍🩹 <b>Phase 1: HP Comparison</b>\n"
    p1_hp_draft = p1['team'].get('HP', {}).get('value', 0)
    p2_hp_draft = p2['team'].get('HP', {}).get('value', 0)
    if p1_hp_draft > p2_hp_draft:
        score1 += 1
        log += f"🔵 {p1['name']}'s HP ({p1_hp_draft}) > ({p2_hp_draft}) 🔴 {p2['name']}'s HP. <b>(+1 Point)</b>\n\n"
    elif p2_hp_draft > p1_hp_draft:
        score2 += 1
        log += f"🔴 {p2['name']}'s HP ({p2_hp_draft}) > ({p1_hp_draft}) 🔵 {p1['name']}'s HP. <b>(+1 Point)</b>\n\n"
    else:
        log += f"⚖️ HP stats are tied at {p1_hp_draft}. No points awarded.\n\n"
    
    p1_combatant_name = p1['team'].get('Type', {}).get('pokemon')
    p2_combatant_name = p2['team'].get('Type', {}).get('pokemon')

    if not p1_combatant_name or not p2_combatant_name:
        log += "⚠️ Battle cannot proceed without Pokémon assigned to the 'Type' slot."
    else:
        p1_combatant_data = POKEMON_DATA[p1_combatant_name]
        p2_combatant_data = POKEMON_DATA[p2_combatant_name]

        # Phase 2: Physical Battle
        log += f"⚔️ <b>Phase 2: Physical Battle</b>\n"
        p1_physical_stats = {
            'hp': p1_hp_draft, 'atk': p1['team'].get('Atk', {}).get('value', 0),
            'def': p1['team'].get('Def', {}).get('value', 0), 'spe': p1['team'].get('Spe', {}).get('value', 0),
            'types': p1_combatant_data['types']}
        p2_physical_stats = {
            'hp': p2_hp_draft, 'atk': p2['team'].get('Atk', {}).get('value', 0),
            'def': p2['team'].get('Def', {}).get('value', 0), 'spe': p2['team'].get('Spe', {}).get('value', 0),
            'types': p2_combatant_data['types']}
        
        physical_result = simulate_matchup(p1_physical_stats, p2_physical_stats)
        if physical_result['winner'] == 'attacker':
            score1 += 1
            log += f"🔵 {p1['name']} wins! It would take {physical_result['attacker_turns']} hits to KO the opponent. <b>(+1 Point)</b>\n\n"
        elif physical_result['winner'] == 'defender':
            score2 += 1
            log += f"🔴 {p2['name']} wins! It would take {physical_result['defender_turns']} hits to KO the opponent. <b>(+1 Point)</b>\n\n"
        else:
            log += "⚖️ The physical battle is a perfect draw! No points awarded.\n\n"

        # Phase 3: Special Battle
        log += f"🔮 <b>Phase 3: Special Battle</b>\n"
        p1_special_stats = {
            'hp': p1_hp_draft, 'atk': p1['team'].get('SpA', {}).get('value', 0),
            'def': p1['team'].get('SpD', {}).get('value', 0), 'spe': p1['team'].get('Spe', {}).get('value', 0),
            'types': p1_combatant_data['types']}
        p2_special_stats = {
            'hp': p2_hp_draft, 'atk': p2['team'].get('SpA', {}).get('value', 0),
            'def': p2['team'].get('SpD', {}).get('value', 0), 'spe': p2['team'].get('Spe', {}).get('value', 0),
            'types': p2_combatant_data['types']}

        special_result = simulate_matchup(p1_special_stats, p2_special_stats)
        if special_result['winner'] == 'attacker':
            score1 += 1
            log += f"🔵 {p1['name']} wins! It would take {special_result['attacker_turns']} hits to KO the opponent. <b>(+1 Point)</b>\n\n"
        elif special_result['winner'] == 'defender':
            score2 += 1
            log += f"🔴 {p2['name']} wins! It would take {special_result['defender_turns']} hits to KO the opponent. <b>(+1 Point)</b>\n\n"
        else:
            log += "⚖️ The special battle is a perfect draw! No points awarded.\n\n"

    # Final Result
    result = 0.5 if score1 == score2 else 1 if score1 > score2 else 0
    delta1, delta2 = update_leaderboard_elo(p1['id'], p1['name'], p2['id'], p2['name'], result)
    winner_name = "It's a Draw!" if result == 0.5 else p1['name'] if result == 1 else p2['name']
    
    final_log = f"{pokemon_get_team_display(game)}\n\n{log}➖➖➖➖➖➖➖➖➖➖\n🔵 <b>Score: {score1}</b> (Rating Change: {delta1:+})\n🔴 <b>Score: {score2}</b> (Rating Change: {delta2:+})\n\n🏆 <b>WINNER: {html.escape(winner_name)}</b>"
    await pokemon_ensure_display_message(client, message.chat.id, game, final_log)
    with GAMES_LOCK:
        try:
            # Cancel any pending tasks
            task = game.get('timer_task')
            if task and not task.done():
                task.cancel()
            # Mark as finished instead of removing immediately - cleanup thread will handle it
            game['status'] = 'finished'
            game['last_activity'] = time.time()
        except Exception as e:
            logging.error(f"Error cleaning up pokemon game: {e}")

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

@app.on_message(filters.command("status") & filters.user(ADMIN_IDS))
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
        f"👥 Active Users: **{u_count}**\n"
        f"💬 Active Chats: **{c_count}**"
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

@app.on_message(filters.command("add") & filters.user(ADMIN_IDS))
async def add_char_cmd(c, m):
    """
    Admin command to add a new character to the database.
    Usage:
    /add character_name
    anime_name
    img_url
    captain_stat
    vice_captain_stat
    tank_stat
    healer_stat
    assassin_stat
    support1_stat
    support2_stat
    traitor_stat
    """
    try:
        lines = m.text.split('\n')
        if len(lines) < 11:
            return await m.reply(
                "❌ Invalid format. Use:\n"
                "/add character_name\n"
                "anime_name\n"
                "img_url\n"
                "captain_stat\n"
                "vice_captain_stat\n"
                "tank_stat\n"
                "healer_stat\n"
                "assassin_stat\n"
                "support1_stat\n"
                "support2_stat\n"
                "traitor_stat"
            )
        
        # Extract and validate inputs
        char_name = lines[0].split(maxsplit=1)[1].strip() if len(lines[0].split()) > 1 else ""
        anime_name = lines[1].strip()
        img_url = lines[2].strip()
        
        # Parse stats
        try:
            captain = int(lines[3].strip())
            vice_captain = int(lines[4].strip())
            tank = int(lines[5].strip())
            healer = int(lines[6].strip())
            assassin = int(lines[7].strip())
            support = int(lines[8].strip())
            support2 = int(lines[9].strip())
            traitor = int(lines[10].strip())
        except ValueError:
            return await m.reply("❌ Stats must be integers!")
        
        if not char_name or not anime_name or not img_url:
            return await m.reply("❌ Character name, anime name, and image URL cannot be empty!")
        
        # Create character document
        char_doc = {
            "name": char_name,
            "series": anime_name,
            "img": img_url,
            "stats": {
                "captain": captain,
                "vice_captain": vice_captain,
                "tank": tank,
                "healer": healer,
                "assassin": assassin,
                "support": support,
                "traitor": traitor
            }
        }
        
        # Add to MongoDB if available, otherwise add to JSON
        if USE_MONGO and COL_CHARACTERS is not None:
            try:
                # Update if exists, insert if new
                result = COL_CHARACTERS.update_one(
                    {"name": char_name},
                    {"$set": char_doc},
                    upsert=True
                )
                logging.info(f"Added character '{char_name}' to MongoDB.")
            except Exception as e:
                logging.error(f"Failed to add character to MongoDB: {e}")
                return await m.reply(f"❌ Database error: {e}")
        else:
            # Fallback: add to JSON file
            try:
                data = []
                if os.path.exists(CHARACTERS_FILE):
                    with open(CHARACTERS_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                
                # Remove if exists, then add
                data = [c for c in data if c.get('name') != char_name]
                data.append(char_doc)
                
                with open(CHARACTERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                logging.info(f"Added character '{char_name}' to JSON file.")
            except Exception as e:
                logging.error(f"Failed to add character to JSON: {e}")
                return await m.reply(f"❌ File error: {e}")
        
        # Update in-memory data
        CHAR_STATS[char_name] = char_doc["stats"]
        CHAR_IMAGES[char_name] = img_url
        if char_name not in ANIME_CHARACTERS:
            ANIME_CHARACTERS.append(char_name)
        
        norm_series = re.sub(r'[^a-z0-9]', '', anime_name.lower())
        if char_name not in SERIES_MAP.get(norm_series, []):
            SERIES_MAP.setdefault(norm_series, []).append(char_name)
        SERIES_DISPLAY[norm_series] = anime_name
        
        # Format response
        stats_txt = (
            f"Captain: {captain}\n"
            f"Vice Captain: {vice_captain}\n"
            f"Tank: {tank}\n"
            f"Healer: {healer}\n"
            f"Assassin: {assassin}\n"
            f"Support: {support}\n"
            f"Support 2: {support2}\n"
            f"Traitor: {traitor}"
        )
        
        await m.reply(
            f"✅ <b>Character Added!</b>\n\n"
            f"<b>Name:</b> {html.escape(char_name)}\n"
            f"<b>Anime:</b> {html.escape(anime_name)}\n"
            f"<b>Stats:</b>\n{stats_txt}",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logging.exception(f"Error in add_char_cmd: {e}")
        await m.reply(f"❌ Error: {e}")

@app.on_message(filters.command("updateimg") & filters.user(ADMIN_IDS))
async def updateimg_cmd(c, m):
    """
    Admin command to update a character's image URL.
    Usage:
    /updateimg "new_url" "character_name" "series_name"
    """
    try:
        # Parse command - expecting quoted arguments
        text = m.text
        # Remove the /updateimg command part
        args_text = text.split(maxsplit=1)[1].strip() if ' ' in text else ""
        
        if not args_text:
            return await m.reply(
                "❌ Invalid format. Use:\n"
                '/updateimg "new_url" "character_name" "series_name"'
            )
        
        # Extract quoted arguments
        import shlex
        try:
            parts = shlex.split(args_text)
            if len(parts) < 3:
                return await m.reply(
                    "❌ Invalid format. Use:\n"
                    '/updateimg "new_url" "character_name" "series_name"'
                )
            img_url = parts[0].strip()
            char_name = parts[1].strip()
            series_name = parts[2].strip()
        except ValueError:
            return await m.reply(
                "❌ Invalid format. Use:\n"
                '/updateimg "new_url" "character_name" "series_name"'
            )
        
        if not img_url or not char_name or not series_name:
            return await m.reply("❌ Image URL, character name, and series name cannot be empty!")
        
        # Create unique identifier
        unique_char_id = f"{char_name} | {series_name}"
        
        # Check if character exists
        if unique_char_id not in CHAR_STATS:
            return await m.reply(f"❌ Character '{char_name}' from '{series_name}' not found!")
        
        # Update in MongoDB if available, otherwise update JSON
        if USE_MONGO and COL_CHARACTERS is not None:
            try:
                result = COL_CHARACTERS.update_one(
                    {"name": char_name, "series": series_name},
                    {"$set": {"img": img_url}},
                    upsert=False
                )
                if result.matched_count == 0:
                    return await m.reply(f"❌ Character not found in database!")
                logging.info(f"Updated image for '{char_name}' from '{series_name}' in MongoDB.")
            except Exception as e:
                logging.error(f"Failed to update character in MongoDB: {e}")
                return await m.reply(f"❌ Database error: {e}")
        else:
            # Fallback: update JSON file
            try:
                data = []
                if os.path.exists(CHARACTERS_FILE):
                    with open(CHARACTERS_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                
                # Find and update character
                found = False
                for char in data:
                    if char.get('name') == char_name and char.get('series') == series_name:
                        char['img'] = img_url
                        found = True
                        break
                
                if not found:
                    return await m.reply(f"❌ Character not found in database!")
                
                with open(CHARACTERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                logging.info(f"Updated image for '{char_name}' from '{series_name}' in JSON file.")
            except Exception as e:
                logging.error(f"Failed to update character in JSON: {e}")
                return await m.reply(f"❌ File error: {e}")
        
        # Update in-memory data
        CHAR_IMAGES[unique_char_id] = img_url
        
        await m.reply(
            f"✅ <b>Image Updated!</b>\n\n"
            f"<b>Character:</b> {html.escape(char_name)}\n"
            f"<b>Series:</b> {html.escape(series_name)}\n"
            f"<b>New URL:</b> <code>{html.escape(img_url)}</code>",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logging.exception(f"Error in updateimg_cmd: {e}")
        await m.reply(f"❌ Error: {e}")

def save_admin_ids():
    """Save ADMIN_IDS to a persistent file."""
    try:
        with open("admin_ids.json", "w", encoding="utf-8") as f:
            json.dump(list(ADMIN_IDS), f, indent=2)
        logging.info(f"Saved {len(ADMIN_IDS)} admin IDs to file.")
    except Exception as e:
        logging.error(f"Failed to save admin IDs: {e}")

def load_admin_ids():
    """Load ADMIN_IDS from persistent file."""
    global ADMIN_IDS
    try:
        if os.path.exists("admin_ids.json"):
            with open("admin_ids.json", "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    ADMIN_IDS = loaded
                    logging.info(f"Loaded {len(ADMIN_IDS)} admin IDs from file.")
    except Exception as e:
        logging.error(f"Failed to load admin IDs: {e}")

# Load admin IDs on startup
load_admin_ids()

@app.on_message(filters.command("add_sudo") & filters.user([6265981509]))
async def add_sudo_cmd(c, m):
    """
    Command to promote a user to admin.
    Can be used by user 6265981509 only.
    Usage (reply to a message):
    /add_sudo
    
    Or with username/UID:
    /add_sudo @username
    /add_sudo 123456789
    """
    try:
        target_uid = None
        
        # Check if replying to a message
        if m.reply_to_message:
            target_uid = m.reply_to_message.from_user.id
        else:
            # Parse from command arguments
            parts = m.text.split()
            if len(parts) < 2:
                return await m.reply(
                    "❌ Invalid usage.\n\n"
                    "<b>Reply to a message:</b>\n/add_sudo\n\n"
                    "<b>Or provide UID:</b>\n/add_sudo 123456789\n\n"
                    "<b>Or provide username:</b>\n/add_sudo @username",
                    parse_mode=ParseMode.HTML
                )
            
            identifier = parts[1]
            
            # If it's a username, we'd need to resolve it (simplified for now)
            if identifier.startswith("@"):
                # For simplicity, we can't resolve usernames without making API calls
                return await m.reply("❌ Please reply to the user's message or provide their UID directly.")
            
            # Try to parse as UID
            try:
                target_uid = int(identifier)
            except ValueError:
                return await m.reply("❌ Invalid UID. Please provide a valid numeric UID or reply to a message.")
        
        if not target_uid:
            return await m.reply("❌ Could not determine target user.")
        
        # Prevent demoting self
        if target_uid == m.from_user.id:
            return await m.reply("❌ You cannot promote yourself (you're already the only promoter).")
        
        # Check if already admin
        if target_uid in ADMIN_IDS:
            return await m.reply(f"❌ User {target_uid} is already an admin!")
        
        # Add to admin list
        ADMIN_IDS.append(target_uid)
        save_admin_ids()
        
        logging.info(f"User {target_uid} promoted to admin by {m.from_user.id}")
        
        await m.reply(
            f"✅ <b>Admin Promoted!</b>\n\n"
            f"<b>User ID:</b> <code>{target_uid}</code>\n"
            f"<b>Total Admins:</b> {len(ADMIN_IDS)}",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logging.exception(f"Error in add_sudo_cmd: {e}")
        await m.reply(f"❌ Error: {e}")

@app.on_message(filters.command("remove_sudo") & filters.user([6265981509]))
async def remove_sudo_cmd(c, m):
    """
    Command to demote a user from admin.
    Can be used by user 6265981509 only.
    Usage (reply to a message):
    /remove_sudo
    
    Or with username/UID:
    /remove_sudo @username
    /remove_sudo 123456789
    """
    try:
        target_uid = None
        
        # Check if replying to a message
        if m.reply_to_message:
            target_uid = m.reply_to_message.from_user.id
        else:
            # Parse from command arguments
            parts = m.text.split()
            if len(parts) < 2:
                return await m.reply(
                    "❌ Invalid usage.\n\n"
                    "<b>Reply to a message:</b>\n/remove_sudo\n\n"
                    "<b>Or provide UID:</b>\n/remove_sudo 123456789\n\n"
                    "<b>Or provide username:</b>\n/remove_sudo @username",
                    parse_mode=ParseMode.HTML
                )
            
            identifier = parts[1]
            
            # If it's a username, we'd need to resolve it (simplified for now)
            if identifier.startswith("@"):
                # For simplicity, we can't resolve usernames without making API calls
                return await m.reply("❌ Please reply to the user's message or provide their UID directly.")
            
            # Try to parse as UID
            try:
                target_uid = int(identifier)
            except ValueError:
                return await m.reply("❌ Invalid UID. Please provide a valid numeric UID or reply to a message.")
        
        if not target_uid:
            return await m.reply("❌ Could not determine target user.")
        
        # Prevent demoting the promoter
        if target_uid == 6265981509:
            return await m.reply("❌ Cannot demote the main admin!")
        
        # Check if user is actually an admin
        if target_uid not in ADMIN_IDS:
            return await m.reply(f"❌ User {target_uid} is not an admin!")
        
        # Remove from admin list
        ADMIN_IDS.remove(target_uid)
        save_admin_ids()
        
        logging.info(f"User {target_uid} demoted from admin by {m.from_user.id}")
        
        await m.reply(
            f"✅ <b>Admin Demoted!</b>\n\n"
            f"<b>User ID:</b> <code>{target_uid}</code>\n"
            f"<b>Total Admins:</b> {len(ADMIN_IDS)}",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logging.exception(f"Error in remove_sudo_cmd: {e}")
        await m.reply(f"❌ Error: {e}")

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
    # --- BUG FIX ---
    if not p2 or p2.is_bot or p1.id == p2.id: return await m.reply("⚠️ Invalid opponent. You must reply to a regular user.")
    # --- END BUG FIX ---

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

    game_id = f"{abs(m.chat.id)}_{int(time.time())}_{random.randint(1000,999999)}"

    # Include the filter in game data
    game = {
        "game_id": game_id,
        "status": "waiting",
        "mode": "draft",
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
    challenge_message = await m.reply(
        f"⚔️ <b>DRAFT CHALLENGE</b>\n"
        f"🎭 <b>Series:</b> {series_name}\n\n"
        f"{html.escape(p1.first_name)} Vs {html.escape(p2.first_name)}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.HTML
    )
    game['display_message'] = {'chat_id': challenge_message.chat.id, 'msg_id': challenge_message.id}


@app.on_message(filters.command(["pokemondraft", "pdraft"]))
async def pokemon_draft_cmd(c, m):
    if not m.reply_to_message: return await m.reply("⚠️ Reply to a friend to challenge them!")
    p1, p2 = m.from_user, m.reply_to_message.from_user
    if not p2 or p2.is_bot or p1.id == p2.id: return await m.reply("⚠️ You must challenge a valid user.")
    
    with GAMES_LOCK:
        if len(GAMES.get(m.chat.id, {})) >= MAX_ACTIVE_DRAFTS_PER_CHAT:
            return await m.reply("⚠️ Too many active drafts in this chat. Please finish some first.")

    args = m.text.split()[1:]
    filters_map = {"regions": [], "legendary_status": None}
    legendary_map = {"0l": False, "6l": True}
    for arg in args:
        arg_lower = arg.lower()
        if arg_lower in legendary_map:
            filters_map["legendary_status"] = legendary_map[arg_lower]
        else:
            filters_map["regions"].append(arg.capitalize())

    # Validate: legendary filter (6l) is not allowed with region
    if filters_map["legendary_status"] is True and filters_map["regions"]:
        return await m.reply("❌ Cannot filter by legendary (6l) with regions!\nUse:\n• `/pdraft 6l` (all legendary)\n• `/pdraft region 0l` (region non-legendary)\n• `/pdraft region` (all from region)")

    # Validate filters before creating game
    region_filters = filters_map.get("regions")
    legendary_filter = filters_map.get("legendary_status")
    
    filtered_list = POKEMON_LIST[:]
    if region_filters:
        filtered_list = [p for p in filtered_list if POKEMON_DATA.get(p, {}).get("region") in region_filters]
        if not filtered_list:
            invalid_regions = [r for r in region_filters if not any(POKEMON_DATA.get(p, {}).get("region") == r for p in POKEMON_LIST)]
            return await m.reply(f"❌ Invalid region(s): {', '.join(invalid_regions)}\nValid regions: Kanto, Johto, Hoenn, Sinnoh, Unova, Kalos, Alola, Galar, Paldea")
    
    if legendary_filter is not None:
        filtered_list = [p for p in filtered_list if POKEMON_DATA.get(p, {}).get("is_legendary") == legendary_filter]
    
    if not filtered_list:
        filter_desc = "legendary" if legendary_filter else "non-legendary" if legendary_filter is False else ""
        region_desc = f"{', '.join(region_filters)} region" if region_filters else "all regions"
        return await m.reply(f"❌ No Pokémon found matching filters:\n🔹 Region: {region_desc}\n🔹 Type: {filter_desc if filter_desc else 'any'}\n\nTry different filters!")

    game_id = f"{m.chat.id}_{int(time.time())}_{random.randint(1000, 9999)}"
    game = {
        "game_id": game_id, "status": "waiting", "mode": "pdraft", "turn": p1.id, "last_activity": time.time(),
        "p1": {"id": p1.id, "name": p1.first_name, "team": {}, "skips": 2},
        "p2": {"id": p2.id, "name": p2.first_name, "team": {}, "skips": 2},
        "used_players": [],
        "filters": filters_map,
    }

    with GAMES_LOCK:
        GAMES.setdefault(m.chat.id, {})[game_id] = game
    
    msg = await m.reply(
        f"⚔️ <b>Pokémon Stat Draft Challenge!</b>\n\n<b>{html.escape(p1.first_name)}</b> has challenged <b>{html.escape(p2.first_name)}</b>!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Accept Challenge", callback_data=f"paccept_{game_id}")]]),
        parse_mode=ParseMode.HTML
    )
    game['display_message'] = {'chat_id': msg.chat.id, 'msg_id': msg.id}


@app.on_message(filters.command("draft_v2"))
async def draft_v2_cmd(c, m):
    if not m.reply_to_message: return await m.reply("⚠️ Reply to a friend!")
    p1, p2 = m.from_user, m.reply_to_message.from_user
    # --- BUG FIX ---
    if not p2 or p2.is_bot or p1.id == p2.id: return await m.reply("⚠️ Invalid opponent. You must reply to a regular user.")
    # --- END BUG FIX ---

    # 1. Parse Series Filter
    series_filter = None
    args = m.text.split(maxsplit=1)
    if len(args) > 1:
        raw_input = re.sub(r'[^a-z0-9]', '', args[1].lower())
        if raw_input in SERIES_MAP:
            series_filter = raw_input
        else:
            examples = ", ".join(list(SERIES_DISPLAY.values())[:5])
            return await m.reply(f"❌ Series not found.\nTry: {examples}...")

    if USE_MONGO:
        save_id_set(CHATS_FILE, {m.chat.id})
        save_id_set(USERS_FILE, {p1.id, p2.id})

    game_id = f"{m.chat.id}_{random.randint(1000,9999)}"
    game = {
        "game_id": game_id,
        "status": "waiting",
        "mode": "draft_v2",
        "turn": p1.id,
        "last_activity": time.time(),
        "filter": series_filter,
        "p1": {"id": p1.id, "name": p1.first_name, "team": {}},
        "p2": {"id": p2.id, "name": p2.first_name, "team": {}},
        "ready": {"p1": False, "p2": False},
        "battle_started": False
    }

    with GAMES_LOCK:
        if m.chat.id not in GAMES: GAMES[m.chat.id] = {}
        GAMES[m.chat.id][game_id] = game

    series_name = SERIES_DISPLAY.get(series_filter, "All Anime") if series_filter else "All Anime"

    kb = [[InlineKeyboardButton("✅ Accept Deck Duel", callback_data=f"accept_{game_id}")]]
    challenge_message = await m.reply(
        f"⚔️ <b>DECK DUEL CHALLENGE</b>\n"
        f"🎭 <b>Series:</b> {series_name}\n\n"
        f"{html.escape(p1.first_name)} Vs {html.escape(p2.first_name)}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.HTML
    )
    game['display_message'] = {'chat_id': challenge_message.chat.id, 'msg_id': challenge_message.id}
    # --- MODIFICATION: Attempt to pin the message ---
    try:
        await c.pin_chat_message(challenge_message.chat.id, challenge_message.id, disable_notification=True)
    except Exception as e:
        logging.warning(f"Could not pin message in chat {challenge_message.chat.id}: {e}")
    # --- END MODIFICATION ---

@app.on_callback_query()
async def callbacks(c, q: CallbackQuery):
    async with CALLBACK_SEMAPHORE:
        try:
            data = q.data

            # --- Game Independent Callbacks ---
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

                kb = InlineKeyboardMarkup([[InlineKeyboardButton("Points" if sort_by == 'wins' else "Most Wins", callback_data="lb_toggle_rating" if sort_by == 'wins' else "lb_toggle_wins")]])
                try:
                    await q.message.edit_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML)
                except: pass
                await q.answer()
                return

            # --- Game Related Callbacks ---

            # --- NEW ROBUST PARSING LOGIC ---
            # Split only on the first underscore to separate action from game_id
            if '_' not in data:
                logging.warning(f"Invalid callback data received: {data}")
                return
            
            action_part, gid_with_payload = data.split('_', 1)
            action = action_part
            
            # For callbacks with payload (like pset_gameid_role), extract the game_id
            # Game ID format: chatid_timestamp_random (has exactly 2 underscores)
            gid_parts = gid_with_payload.split('_')
            
            # Minimum: action_chatid_timestamp_random = 4 parts when split by _
            if len(gid_parts) < 3:
                logging.warning(f"Invalid callback data received: {data}")
                return
            
            # Reconstruct game_id from the first 3 parts after action
            gid_to_find = f"{gid_parts[0]}_{gid_parts[1]}_{gid_parts[2]}"
            game, gid = None, None

            # The original loop is fine, since game_id is globally unique.
            # We iterate through all games to find the one with the matching ID.
            try:
                for _chat_id, chat_games in GAMES.items():
                    if gid_to_find in chat_games:
                        game = chat_games[gid_to_find]
                        gid = gid_to_find
                        break
            except Exception as e:
                logging.error(f"Error searching for game: {e}")
                game = None

            if not game:
                try:
                    await q.edit_message_text("⏳ Game has expired or was canceled.", reply_markup=None)
                except:
                    try:
                        await q.answer("Game expired.", show_alert=True)
                    except:
                        logging.warning(f"Could not answer callback for expired game")
                return
            # --- END NEW PARSING LOGIC ---

            uid = q.from_user.id
            try:
                game['last_activity'] = time.time()
            except Exception as e:
                logging.error(f"Error updating game activity: {e}")
                return

            # --- POKEMON DRAFT CALLBACKS ---
            if action == "paccept":
                try:
                    if uid != game["p2"]["id"]: 
                        return await q.answer("❌ This challenge is not for you.", show_alert=True)
                    game['status'] = 'active'
                    await pokemon_show_draw_menu(c, q.message, game, gid)
                    await q.answer("Challenge accepted!")
                except Exception as e:
                    logging.error(f"Error in paccept: {e}")
                    await q.answer("❌ An error occurred.", show_alert=True)
                return
            
            if action == "pstartbattle":
                try:
                    if uid not in [game["p1"]["id"], game["p2"]["id"]]: 
                        return await q.answer("You are not in this game.", show_alert=True)
                    if game.get("battle_started"): 
                        return await q.answer("The battle has already started!", show_alert=True)
                    game["battle_started"] = True
                    await pokemon_simulate_battle(c, q.message, game)
                except Exception as e:
                    logging.error(f"Error in pstartbattle: {e}")
                    await q.answer("❌ Battle error.", show_alert=True)
                return
                return

            if action == "pdraw":
                if uid != game["turn"]: return await q.answer("⏳ It's not your turn!", show_alert=True)
                if game.get("current_draw"): return await q.answer("You have already drawn a Pokémon.", show_alert=True)
                
                game_filters = game.get("filters", {})
                region_filters = game_filters.get("regions")
                legendary_filter = game_filters.get("legendary_status")
                
                filtered_list = POKEMON_LIST[:]
                if region_filters:
                    filtered_list = [p for p in filtered_list if POKEMON_DATA.get(p, {}).get("region") in region_filters]
                if legendary_filter is not None:
                    filtered_list = [p for p in filtered_list if POKEMON_DATA.get(p, {}).get("is_legendary") == legendary_filter]

                available = [p for p in filtered_list if p not in game["used_players"]]
                if not available: return await q.answer("❌ No Pokémon matching the filters are left!", show_alert=True)
                
                pokemon = random.choice(available)
                game["current_draw"] = pokemon
                await pokemon_show_assignment_menu(c, q.message, game, pokemon, gid)
                await q.answer(f"You drew {pokemon}!")
                return

            if action == "pskip":
                if uid != game["turn"]: return await q.answer("⏳ It's not your turn!", show_alert=True)
                pkey = "p1" if uid == game["p1"]["id"] else "p2"
                if game[pkey]["skips"] > 0:
                    game[pkey]["skips"] -= 1
                    if game.get("current_draw"): game["used_players"].append(game["current_draw"])
                    game["current_draw"] = None
                    pokemon_switch_turn(game)
                    await pokemon_show_draw_menu(c, q.message, game, gid)
                    await q.answer("Pokémon skipped.")
                else: await q.answer("❌ You have no skips left.", show_alert=True)
                return

            if action == "pset":
                if uid != game["turn"]: return await q.answer("⏳ It's not your turn!", show_alert=True)
                # Extract the role from the remaining parts (parts after the game_id)
                role = gid_parts[3] if len(gid_parts) > 3 else None
                if not role: return await q.answer("❌ Invalid role.", show_alert=True)
                
                pokemon_name = game.get("current_draw")
                if not pokemon_name: return await q.answer("❌ Error: No Pokémon was drawn.", show_alert=True)
                
                pokemon_info = POKEMON_DATA.get(pokemon_name)
                if not pokemon_info: return await q.answer("❌ Error: Could not find data for this Pokémon.", show_alert=True)

                pkey = "p1" if uid == game["p1"]["id"] else "p2"
                
                if role == "Type":
                    game[pkey]["team"][role] = {"pokemon": pokemon_name, "types": pokemon_info["types"]}
                elif role in STAT_MAP:
                    stat_key = STAT_MAP[role]
                    game[pkey]["team"][role] = {"pokemon": pokemon_name, "value": pokemon_info["stats"][stat_key]}
                else:
                    return await q.answer("❌ Invalid role selected.", show_alert=True)

                game["used_players"].append(pokemon_name)
                game["current_draw"] = None
                
                role_count = len(POKEMON_ROLES)
                if len(game["p1"]["team"]) == role_count and len(game["p2"]["team"]) == role_count:
                    await pokemon_finish_game_ui(c, q.message, game, gid)
                else:
                    pokemon_switch_turn(game)
                    await pokemon_show_draw_menu(c, q.message, game, gid)

                await q.answer(f"{pokemon_name} assigned to {role}.")
                return

            # --- ANIME DRAFT CALLBACKS ---
            # --- END POKEMON DRAFT CALLBACKS ---

            # --- Callback Handlers (Now using the new robust `action`) ---
            if action == "accept":
                if uid != game["p2"]["id"]: return await q.answer("❌ This is not for you.", show_alert=True)

                game['status'] = 'active'
                if game.get('mode') == 'draft_v2':
                    pool_key = game.get('filter')
                    base_pool = SERIES_MAP.get(pool_key, ANIME_CHARACTERS)
                    game['deck_p1'] = generate_deck(base_pool, size=9)
                    game['deck_p2'] = generate_deck(base_pool, size=9)
                    game['roles_order'] = ROLES
                    game['current_role_index'] = 0
                    game['assigned_p1'], game['assigned_p2'] = [], []
                    game['pending_picks'] = {}

                await show_draw_menu(c, q.message, game, gid)
                return

            if action == "assign":
                if uid != game['turn']: return await q.answer("⏳ Not your turn!", show_alert=True)
                
                # Payload is now parsed from the end of `gid_parts`
                r_index = int(gid_parts[3]) if len(gid_parts) > 3 else -1
                card_idx = int(gid_parts[4]) if len(gid_parts) > 4 else -1
                if r_index < 0 or card_idx < 0: return await q.answer("❌ Invalid payload.", show_alert=True)

                pkey = 'p1' if uid == game['p1']['id'] else 'p2'
                other_pkey = 'p2' if pkey == 'p1' else 'p1'

                deck = game[f'deck_{pkey}']
                assigned_chars = set(game[f'assigned_{pkey}'])
                available_deck = [c for c in deck if c not in assigned_chars]

                card = available_deck[card_idx]

                game['pending_picks'][pkey] = card
                await q.message.edit_text(f"✅ You secretly picked <b>{html.escape(card)}</b>.", parse_mode=ParseMode.HTML)

                if other_pkey in game.get('pending_picks', {}):
                    role_key = game['roles_order'][r_index]
                    p1_pick = game['pending_picks']['p1']
                    p2_pick = game['pending_picks']['p2']

                    game['p1']['team'][role_key] = p1_pick
                    game['p2']['team'][role_key] = p2_pick
                    game['assigned_p1'].append(p1_pick)
                    game['assigned_p2'].append(p2_pick)
                    game['pending_picks'] = {}

                    reveal_text = (
                        f"🎭 <b>Round {r_index + 1} Reveal: {role_key}</b>\n"
                        f"🔵 {html.escape(game['p1']['name'])} chose: <b>{html.escape(p1_pick)}</b>\n"
                        f"🔴 {html.escape(game['p2']['name'])} chose: <b>{html.escape(p2_pick)}</b>"
                    )
                    try:
                        await c.send_message(game['p1']['id'], reveal_text, parse_mode=ParseMode.HTML)
                    except Exception as e:
                        logging.warning(f"Could not DM reveal to p1 {game['p1']['id']}: {e}")
                    try:
                        await c.send_message(game['p2']['id'], reveal_text, parse_mode=ParseMode.HTML)
                    except Exception as e:
                        logging.warning(f"Could not DM reveal to p2 {game['p2']['id']}: {e}")

                    await c.send_message(q.message.chat.id, reveal_text, parse_mode=ParseMode.HTML)

                    game['current_role_index'] += 1
                    if game['current_role_index'] >= len(game['roles_order']):
                        await finish_game_ui(c, q.message, game, gid)
                    else:
                        game['turn'] = game['p1']['id']
                        await show_draw_menu(c, q.message, game, gid)
                else:
                    game['turn'] = game[other_pkey]['id']
                    await show_draw_menu(c, q.message, game, gid)
                return

            if action == "startrpg":
                try:
                    player_key = gid_parts[3] if len(gid_parts) > 3 else None  # "p1" or "p2"
                    if not player_key:
                        return await q.answer("❌ Invalid action.", show_alert=True)
                    
                    is_p1 = (player_key == "p1")
                    with GAMES_LOCK:
                        if (is_p1 and uid == game["p1"]["id"]): 
                            game["ready"]["p1"] = True
                        elif (not is_p1 and uid == game["p2"]["id"]): 
                            game["ready"]["p2"] = True
                        else: 
                            return await q.answer("❌ Wrong button.", show_alert=True)

                        if game.get("ready", {}).get("p1") and game.get("ready", {}).get("p2") and not game.get("battle_started"):
                            game["battle_started"] = True
                            await simulate_battle(c, q.message, game)
                        else:
                            await finish_game_ui(c, q.message, game, gid)
                            await q.answer("✅ Ready! Waiting...")
                except Exception as e:
                    logging.error(f"Error in startrpg: {e}")
                    await q.answer("❌ An error occurred.", show_alert=True)
                return

            if uid != game["turn"]: 
                return await q.answer("⏳ Not your turn!", show_alert=True)

            if action == "draw":
                try:
                    pool = SERIES_MAP.get(game.get("filter"), ANIME_CHARACTERS)
                    available = [x for x in pool if x not in game["used_chars"]]
                    if not available: 
                        return await q.answer("❌ Pool empty!", show_alert=True)

                    char = random.choice(available)
                    game["current_draw"] = char
                    await show_assignment_menu(c, q.message, game, char, gid)
                except Exception as e:
                    logging.error(f"Error in draw: {e}")
                    await q.answer("❌ Draw error.", show_alert=True)

            elif action == "skip":
                try:
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
                except Exception as e:
                    logging.error(f"Error in skip: {e}")
                    await q.answer("❌ Skip error.", show_alert=True)

            elif action == "set":
                try:
                    role = gid_parts[3].replace('-', ' ') if len(gid_parts) > 3 else None  # Restore spaces from safe format
                    if not role: 
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
                    logging.error(f"Error in set: {e}")
                    await q.answer("❌ Assignment error.", show_alert=True)

        except Exception as e:
            logging.exception(f"Callback error: {e}") # Log with exception info
            try:
                await q.answer("❌ An error occurred.", show_alert=True)
            except: pass


if __name__ == "__main__":
    print("Bot Starting...")
    try:
        init_mongo()
        load_data()
        load_pokemon_data()
        web_thread = threading.Thread(target=lambda: web_app.run(host="0.0.0.0", port=PORT), daemon=True)
        web_thread.start()
        logging.info(f"Flask web server started on port {PORT}.")
    except Exception:
        logging.exception("Failed to start Flask web server thread")
    app.run()
