import discord
import os
import asyncio
import requests
import sqlite3
from datetime import datetime, timezone

# ================= ENV =================
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# ================= CONFIG =================
REGION = "au"
ODDS_FORMAT = "decimal"
CHECK_INTERVAL = 900
MIN_EV = 0.03
MAX_HOURS_TO_START = 24

TRUSTED_BOOKS = ["Sportsbet", "PointsBet", "TAB", "Neds", "Betfair AU"]

SPORTS = {
    "americanfootball_nfl": {
        "name": "🏈 NFL",
        "markets": ["h2h", "spreads", "totals"]
    },
    "basketball_nba": {
        "name": "🏀 NBA",
        "markets": ["h2h", "spreads", "totals", "player_points"]
    },
    "soccer_epl": {
        "name": "⚽ EPL",
        "markets": ["h2h", "totals"]
    }
}

# ================= DATABASE =================
conn = sqlite3.connect("bets.db", check_same_thread=False)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS bets (
    id TEXT PRIMARY KEY,
    sport TEXT,
    game TEXT,
    market TEXT,
    pick TEXT,
    odds REAL,
    stake REAL,
    ev REAL,
    result TEXT
)
""")
conn.commit()

# ================= DISCORD =================
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

posted_bets = set()

# ================= HELPERS =================
def hours_until_start(commence):
    start = datetime.fromisoformat(commence.replace("Z", "+00:00"))
    return (start - datetime.now(timezone.utc)).total_seconds() / 3600

def calc_ev(price, true_prob):
    return (price * true_prob) - 1

def staking(ev):
    if ev >= 0.08: return 3
    if ev >= 0.06: return 2
    if ev >= 0.04: return 1
    return 0.5

def format_game(game):
    home = game.get("home_team", "Unknown")
    away = game.get("away_team", "Unknown")
    start = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
    return f"{away} @ {home} — {start.strftime('%d %b %H:%M UTC')}"

def log_bet(bet_id, sport, game, market, pick, odds, stake, ev):
    c.execute("""
    INSERT OR IGNORE INTO bets
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
    """, (bet_id, sport, game, market, pick, odds, stake, ev))
    conn.commit()

def get_roi():
    c.execute("SELECT odds, stake, result FROM bets WHERE result IS NOT NULL")
    rows = c.fetchall()

    profit = 0
    staked = 0

    for odds, stake, result in rows:
        staked += stake
        if result == "win":
            profit += (odds - 1) * stake
        elif result == "loss":
            profit -= stake

    return profit, staked

# ================= CORE =================
async def check_sport(channel, sport_key, cfg):
    for market in cfg["markets"]:
        url = (
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
            f"?apiKey={ODDS_API_KEY}"
            f"&regions={REGION}"
            f"&markets={market}"
            f"&oddsFormat={ODDS_FORMAT}"
        )

        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                continue
            games = r.json()
        except:
            continue

        for game in games:
            if hours_until_start(game["commence_time"]) > MAX_HOURS_TO_START:
                continue

            books = game.get("bookmakers", [])
            if len(books) < 2:
                continue

            game_line = format_game(game)

            for outcome in books[0]["markets"][0]["outcomes"]:
                name = outcome["name"]

                ref_prices = []
                for b in books:
                    if b["title"] in TRUSTED_BOOKS:
                        try:
                            price = next(
                                o["price"]
                                for o in b["markets"][0]["outcomes"]
                                if o["name"] == name
                            )
                            ref_prices.append(price)
                        except:
                            pass

                if len(ref_prices) < 2:
                    continue

                true_prob = sum(1/p for p in ref_prices) / len(ref_prices)

                best_price = 0
                best_book = None
                for b in books:
                    try:
                        price = next(
                            o["price"]
                            for o in b["markets"][0]["outcomes"]
                            if o["name"] == name
                        )
                        if price > best_price:
                            best_price = price
                            best_book = b["title"]
                    except:
                        pass

                ev = calc_ev(best_price, true_prob)
                if ev < MIN_EV:
                    continue

                bet_id = f"{game['id']}-{market}-{name}"
                if bet_id in posted_bets:
                    continue
                posted_bets.add(bet_id)

                units = staking(ev)

                msg = (
                    f"🔥 **+EV BET** 🔥\n\n"
                    f"{cfg['name']}\n"
                    f"**Game:** {game_line}\n"
                    f"**Market:** {market}\n"
                    f"**Pick:** {name}\n"
                    f"**Best Odds:** {best_price} ({best_book})\n"
                    f"**EV:** {round(ev*100,2)}%\n"
                    f"**Stake:** {units} units"
                )

                await channel.send(msg)

                log_bet(
                    bet_id,
                    cfg["name"],
                    game_line,
                    market,
                    name,
                    best_price,
                    units,
                    ev
                )

# ================= LOOP =================
async def loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while True:
        for k, v in SPORTS.items():
            await check_sport(channel, k, v)
        await asyncio.sleep(CHECK_INTERVAL)

# ================= EVENTS =================
@client.event
async def on_ready():
    print("Bot online")
    client.loop.create_task(loop())

@client.event
async def on_message(message):
    if message.content == "!roi":
        profit, staked = get_roi()
        if staked == 0:
            await message.channel.send("No settled bets yet.")
            return

        roi_pct = round((profit / staked) * 100, 2)
        await message.channel.send(
            f"📊 **ROI**\n"
            f"Profit: {round(profit,2)}u\n"
            f"Staked: {round(staked,2)}u\n"
            f"ROI: {roi_pct}%"
        )

client.run(TOKEN)
