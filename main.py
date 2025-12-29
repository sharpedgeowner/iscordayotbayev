import discord
import os
import asyncio
import requests

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
MIN_EV = float(os.getenv("MIN_EV", 0.02))        # default +2% EV
KELLY_FRAC = float(os.getenv("KELLY_FRACTION", 0.1))

SPORT = "basketball_nba"
REGIONS = "au,us"
MARKETS = ["h2h"]  # list so we can expand easily

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# store last seen odds for line movement
last_odds = {}

def calc_ev(decimal_odds, true_prob):
    return (true_prob * decimal_odds) - 1

def kelly_units(ev, decimal_odds):
    # Kelly fraction * (bp - q)/b ; simplifed
    b = decimal_odds - 1
    q = 1 - ev
    kelly = ((ev * b) - q) / b if b > 0 else 0
    return max(0, kelly * KELLY_FRAC)

async def check_games(channel):
    url = (
        f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions={REGIONS}"
        f"&markets={','.join(MARKETS)}"
        f"&oddsFormat=decimal"
    )

    res = requests.get(url)
    if res.status_code != 200:
        print("Odds API error", res.status_code)
        return

    games = res.json()

    for game in games:
        game_id = game["id"]
        home = game["home_team"]
        away = game["away_team"]
        bookmakers = game.get("bookmakers", [])

        # skip if no multiple books
        if len(bookmakers) < 2:
            continue

        # identify reference (sharp) as highest available books
        ref_book = bookmakers[0]

        for book in bookmakers:
            book_name = book["title"]

            for market in book["markets"]:
                for outcome in market["outcomes"]:
                    team = outcome["name"]
                    dec_odds = outcome.get("price")

                    # compute true probability using reference odds
                    ref_outcome = next(
                        (o for o in ref_book["markets"][0]["outcomes"] if o["name"] == team),
                        None
                    )
                    if not ref_outcome:
                        continue

                    ref_dec = ref_outcome.get("price")
                    if not ref_dec:
                        continue

                    true_prob = 1 / ref_dec
                    ev = calc_ev(dec_odds, true_prob)

                    # track odds changes
                    prev = last_odds.get((game_id, book_name, team))
                    moved = ""
                    if prev and prev != dec_odds:
                        moved = f"📈 *Line moved: {prev} → {dec_odds}*"

                    # save current odds
                    last_odds[(game_id, book_name, team)] = dec_odds

                    # only alert if EV ≥ threshold
                    if ev >= MIN_EV:
                        units = round(kelly_units(ev, dec_odds), 2)
                        if units > 0:
                            await channel.send(
                                f"🔥 **+EV ALERT** 🔥\n"
                                f"🏀 {away} vs {home}\n"
                                f"📍 Book: {book_name}\n"
                                f"📌 {team} ML @ {dec_odds}\n"
                                f"📊 EV: {round(ev*100,2)}%\n"
                                f"📈 Kelly Units: {units}\n"
                                f"{moved}"
                            )

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(ev_loop())

async def ev_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while True:
        await check_games(channel)
        await asyncio.sleep(900)  # 15 min

client.run(TOKEN)
