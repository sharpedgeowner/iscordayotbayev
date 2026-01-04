import discord
import os
import asyncio
import requests
import sqlite3
from datetime import datetime, timezone, timedelta

# ================= ENV =================
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# ================= CONFIG =================
REGION = "au"
ODDS_FORMAT = "decimal"
CHECK_INTERVAL = 1800  # safer for rate limits
MIN_EV = 0.03
MAX_HOURS_TO_START = 24

TRUSTED_BOOKS = ["Sportsbet", "PointsBet", "TAB", "Neds", "Betfair AU"]

SPORTS = {
    "americanfootball_nfl": {"name": "🏈 NFL", "markets": ["h2h"]},
    "basketball_nba": {"name": "🏀 NBA", "markets": ["h2h"]},
    "soccer_epl": {"name": "⚽ EPL", "markets": ["h2h"]}
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
    result TEXT,
    placed_at TEXT,
    settled_at TEXT,
    posted INTEGER DEFAULT 0
)
""")
conn.commit()

# ================= DISCORD =================
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

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

def discord_time(iso):
    ts = int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    return f"<t:{ts}:F>"

def log_bet(bet_id, sport, game, market, pick, odds, stake, ev):
    c.execute("""
    INSERT OR IGNORE INTO bets
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, 0)
    """, (
        bet_id, sport, game, market, pick, odds, stake, ev,
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()

def settle_bet(bet_id, result):
    c.execute("""
    UPDATE bets SET result=?, settled_at=?
    WHERE id=?
    """, (result, datetime.now(timezone.utc).isoformat(), bet_id))
    conn.commit()

def roi_since(start):
    c.execute("""
        SELECT odds, stake, result
        FROM bets
        WHERE result IS NOT NULL AND settled_at >= ?
    """, (start,))
    rows = c.fetchall()

    profit, staked = 0, 0
    for odds, stake, result in rows:
        staked += stake
        profit += (odds - 1) * stake if result == "win" else -stake

    roi = (profit / staked * 100) if staked else 0
    return round(profit, 2), round(roi, 2)

# ================= CORE =================
async def check_sport(channel, sport_key, cfg):
    for market in cfg["markets"]:
        url = (
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
            f"?apiKey={ODDS_API_KEY}&regions={REGION}"
            f"&markets={market}&oddsFormat={ODDS_FORMAT}"
        )

        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                continue
            games = r.json()
            if not isinstance(games, list):
                continue
        except Exception as e:
            print("Odds API error:", e)
            continue

        for game in games:
            if not isinstance(game, dict):
                continue

            if hours_until_start(game["commence_time"]) > MAX_HOURS_TO_START:
                continue

            books = game.get("bookmakers", [])
            if len(books) < 2:
                continue

            for outcome in books[0]["markets"][0]["outcomes"]:
                name = outcome["name"]
                prices = []

                for b in books:
                    if b["title"] in TRUSTED_BOOKS:
                        try:
                            price = next(o["price"] for o in b["markets"][0]["outcomes"] if o["name"] == name)
                            prices.append((price, b["title"]))
                        except:
                            pass

                if len(prices) < 2:
                    continue

                true_prob = sum(1/p[0] for p in prices) / len(prices)
                best_price, best_book = max(prices, key=lambda x: x[0])
                ev = calc_ev(best_price, true_prob)

                if ev < MIN_EV:
                    continue

                bet_id = f"{game['id']}-{market}-{name}"
                c.execute("SELECT posted FROM bets WHERE id=?", (bet_id,))
                if c.fetchone():
                    continue

                units = staking(ev)

                msg = (
                    f"🔥 **+EV BET** 🔥\n\n"
                    f"{cfg['name']}\n"
                    f"**Game:** {game['away_team']} @ {game['home_team']}\n"
                    f"**Start:** {discord_time(game['commence_time'])}\n"
                    f"**Pick:** {name}\n"
                    f"**Odds:** {best_price} ({best_book})\n"
                    f"**EV:** {round(ev*100,2)}%\n"
                    f"**Stake:** {units} units"
                )

                await channel.send(msg)

                log_bet(bet_id, sport_key, game["id"], market, name, best_price, units, ev)
                c.execute("UPDATE bets SET posted=1 WHERE id=?", (bet_id,))
                conn.commit()

# ================= AUTO SETTLE (H2H ONLY) =================
async def auto_settle():
    await client.wait_until_ready()

    while True:
        c.execute("""
            SELECT id, sport, pick
            FROM bets
            WHERE result IS NULL AND market='h2h'
        """)
        unsettled = c.fetchall()

        for bet_id, sport, pick in unsettled:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/scores?apiKey={ODDS_API_KEY}&daysFrom=2"

            try:
                r = requests.get(url, timeout=10)
                if r.status_code != 200:
                    continue
                games = r.json()
                if not isinstance(games, list):
                    continue
            except:
                continue

            for game in games:
                if not game.get("completed"):
                    continue

                scores = game.get("scores")
                if not scores:
                    continue

                winner = game["home_team"] if scores[0]["score"] > scores[1]["score"] else game["away_team"]
                settle_bet(bet_id, "win" if pick == winner else "loss")

        await asyncio.sleep(3600)

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
    client.loop.create_task(auto_settle())

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if message.channel.id != RESULTS_CHANNEL_ID:
        return

    if message.content.lower() == "?results":
        now = datetime.now(timezone.utc)
        periods = {
            "Today": now.replace(hour=0, minute=0, second=0),
            "Week": now - timedelta(days=now.weekday()),
            "Month": now.replace(day=1),
            "Year": now.replace(month=1, day=1),
            "All-Time": datetime(1970, 1, 1, tzinfo=timezone.utc)
        }

        msg = "📊 **RESULTS**\n\n"
        for label, start in periods.items():
            units, roi = roi_since(start.isoformat())
            msg += f"**{label}:** {units:+}u | {roi}%\n"

        await message.channel.send(msg)

client.run(TOKEN)
