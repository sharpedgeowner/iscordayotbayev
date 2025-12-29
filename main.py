import discord
import os
import asyncio
import requests

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

SPORT = "basketball_nba"
REGION = "us"
MARKET = "h2h"  # moneyline

intents = discord.Intents.default()
client = discord.Client(intents=intents)

def american_to_decimal(odds):
    if odds > 0:
        return 1 + odds / 100
    else:
        return 1 + 100 / abs(odds)

def calculate_ev(decimal_odds, true_prob):
    return (true_prob * decimal_odds) - 1

def staking_units(ev):
    if ev >= 0.10:
        return 3
    elif ev >= 0.05:
        return 2
    elif ev >= 0.02:
        return 1
    else:
        return 0

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(ev_loop())

async def ev_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while True:
        url = (
            f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
            f"?apiKey={ODDS_API_KEY}&regions={REGION}&markets={MARKET}"
        )

        response = requests.get(url)

        if response.status_code != 200:
            print("Odds API error")
            await asyncio.sleep(600)
            continue

        games = response.json()

        for game in games:
            home = game["home_team"]
            away = game["away_team"]

            bookmakers = game.get("bookmakers", [])
            if len(bookmakers) < 2:
                continue

            sharp_book = bookmakers[0]   # reference
            soft_book = bookmakers[-1]   # target

            for i in range(2):
                sharp_odds = sharp_book["markets"][0]["outcomes"][i]["price"]
                soft_odds = soft_book["markets"][0]["outcomes"][i]["price"]
                team = sharp_book["markets"][0]["outcomes"][i]["name"]

                sharp_dec = american_to_decimal(sharp_odds)
                true_prob = 1 / sharp_dec
                soft_dec = american_to_decimal(soft_odds)

                ev = calculate_ev(soft_dec, true_prob)
                units = staking_units(ev)

                if units > 0:
                    await channel.send(
                        f"🔥 **+EV BET FOUND** 🔥\n\n"
                        f"🏀 {away} vs {home}\n"
                        f"📌 {team} ML\n"
                        f"💰 Odds: {soft_odds}\n"
                        f"📊 EV: {round(ev * 100, 2)}%\n"
                        f"📈 Stake: {units} Units\n"
                    )

        await asyncio.sleep(900)  # check every 15 minutes

client.run(TOKEN)
