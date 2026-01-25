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
CHECK_INTERVAL = 1800
MIN_EV = 0.03
MAX_HOURS_TO_START = 24

TRUSTED_BOOKS = ["Sportsbet", "PointsBet", "TAB", "Neds", "Betfair AU"]

SPORTS = {
    "americanfootball_nfl": "🏈 NFL",
    "basketball_nba": "🏀 NBA",
    "soccer_epl": "⚽ EPL"
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
    posted INTEGER
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

def stake(ev):
    if ev >= 0.08: return 3
    if ev >= 0.06: return 2
    if ev >= 0.04: return 1
    return 0.5

def log_bet(bet_id, sport, game, market, pick, odds, units, ev):
    c.execute("""
    INSERT OR IGNORE INTO bets
    (id, sport, game, market, pick, odds, stake, ev, placed_at, posted)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        bet_id, sport, game, market, pick,
        odds, units, ev,
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()

def settle_bet(bet_id, result):
    c.execute("""
    UPDATE bets SET result=?, settled_at=?
    WHERE id=?
    """, (result, datetime.now(timezone.utc).isoformat(), bet_id))
    conn.commit()

# ================= CORE =================
async def check_sport(channel, sport_key, sport_name):
    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        f"?apiKey={ODDS_API_KEY}&regions={REGION}"
        f"&markets=h2h&oddsFormat={ODDS_FORMAT}"
    )


    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return
        games = r.json()
    except:
        return

    for game in games:
        if hours_until_start(game["commence_time"]) > MAX_HOURS_TO_START:
            continue

        books = [b for b in game.get("bookmakers", []) if b.get("markets")]
        if len(books) < 2:
            continue

        outcomes = books[0]["markets"][0]["outcomes"]

        for outcome in outcomes:
            name = outcome["name"]
            prices = []

            for b in books:
                if b["title"] in TRUSTED_BOOKS:
                    try:
                        price = next(o["price"] for o in b["markets"][0]["outcomes"] if o["name"] == name)
                        prices.append(price)
                    except:
                        pass

            if len(prices) < 2:
                continue

            inv = [1/p for p in prices]
            true_prob = sum(inv) / len(inv)
            true_prob = true_prob / (1 + (sum(inv) - 1))

            best_price = max(prices)
            ev = calc_ev(best_price, true_prob)

            if ev < MIN_EV:
                continue

            bet_id = f"{game['id']}-h2h-{name}"
            c.execute("SELECT posted FROM bets WHERE id=?", (bet_id,))
            row = c.fetchone()
            if row and row[0] == 1:
                continue

            units = stake(ev)

            msg = (
                f"🔥 **+EV BET** 🔥\n\n"
                f"{sport_name}\n"
                f"**{game['away_team']} @ {game['home_team']}**\n"
                f"**Pick:** {name}\n"
                f"**Odds:** {best_price}\n"
                f"**EV:** {round(ev*100,2)}%\n"
                f"**Stake:** {units} units"
            )

            await channel.send(msg)
            log_bet(bet_id, sport_key, game["id"], "h2h", name, best_price, units, ev)

# ================= AUTO SETTLE =================
async def auto_settle():
    await client.wait_until_ready()

    while True:
        c.execute("""
        SELECT id, sport, pick
        FROM bets
        WHERE result IS NULL
        """)
        bets = c.fetchall()

        for bet_id, sport, pick in bets:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/scores?apiKey={ODDS_API_KEY}&daysFrom=2"

            try:
                r = requests.get(url, timeout=10)
                games = r.json()
            except:
                continue

            for game in games:
                if not game.get("completed"):
                    continue

                scores = {s["name"]: s["score"] for s in game.get("scores", [])}
                if not scores:
                    continue

                winner = max(scores, key=scores.get)
                settle_bet(bet_id, "win" if pick == winner else "loss")

        await asyncio.sleep(3600)

# ================= EVENTS =================
@client.event
async def on_ready():
    print("Bot online")
    channel = client.get_channel(CHANNEL_ID)
    client.loop.create_task(auto_settle())

    while True:
        for sport, name in SPORTS.items():
            await check_sport(channel, sport, name)
        await asyncio.sleep(CHECK_INTERVAL)

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if message.channel.id != RESULTS_CHANNEL_ID:
        return

    if message.content.lower() == "?results":
        c.execute("SELECT odds, stake, result FROM bets WHERE result IS NOT NULL")
        rows = c.fetchall()

        profit, staked = 0, 0
        for odds, stake, result in rows:
            staked += stake
            profit += (odds - 1) * stake if result == "win" else -stake

        roi = round((profit / staked) * 100, 2) if staked else 0
        await message.channel.send(f"📊 **ROI:** {profit:+.2f}u | {roi}%")

client.run(TOKEN)
