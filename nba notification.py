from nba_api.stats.endpoints import scoreboardv2, boxscoretraditionalv3
from datetime import datetime, timedelta
import pandas as pd
from twilio.rest import Client
import json
import os

# Get yesterday's date
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

# Get scoreboard (games played)
scoreboard = scoreboardv2.ScoreboardV2(game_date=yesterday)
games = scoreboard.game_header.get_data_frame()

all_players = []

for game_id in games["GAME_ID"].unique():
    # traditional box score (basic counting stats)
    boxscore = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id)
    players = boxscore.player_stats.get_data_frame()

    # If the traditional boxscore already has a plus/minus-like column, prefer that first
    trad_pm_candidates = ['PLUS_MINUS', 'plusMinus', 'PlusMinus', 'plus_minus', '+/-', 'PLUS-MINUS', 'plusMinusPoints']
    trad_found = next((c for c in trad_pm_candidates if c in players.columns), None)
    if trad_found:
        players['PLUS_MINUS'] = players[trad_found]

    all_players.append(players)

# Combine all player stats
if not all_players:
    print('No player stats were retrieved for', yesterday)
    df = pd.DataFrame(columns=["PLAYER_NAME", "TEAM_ABBREVIATION", "PTS","PLUS_MINUS"])
else:
    df = pd.concat(all_players, ignore_index=True)

# Ensure a points column named 'PTS' exists for compatibility with older code
if 'PTS' not in df.columns:
    if 'points' in df.columns:
        df['PTS'] = df['points']
    else:
        df['PTS'] = 0

# Normalize player name and team abbreviation to expected column names
if 'PLAYER_NAME' not in df.columns:
    if 'firstName' in df.columns and 'familyName' in df.columns:
        df['PLAYER_NAME'] = df['firstName'].fillna('') + ' ' + df['familyName'].fillna('')
    elif 'name' in df.columns:
        df['PLAYER_NAME'] = df['name']

if 'TEAM_ABBREVIATION' not in df.columns:
    if 'teamTricode' in df.columns:
        df['TEAM_ABBREVIATION'] = df['teamTricode']
    elif 'teamAbbreviation' in df.columns:
        df['TEAM_ABBREVIATION'] = df['teamAbbreviation']

# Ensure `PLUS_MINUS` column exists (normalize common variants)
if 'PLUS_MINUS' not in df.columns:
    candidates = ['plusMinus', 'PLUS_MINUS', 'PlusMinus', 'plus_minus', 'PLUS-MINUS', '+/-', 'plus-minus', 'plusMinusPoints']
    for cand in candidates:
        if cand in df.columns:
            df['PLUS_MINUS'] = df[cand]
            break
    else:
        df['PLUS_MINUS'] = pd.NA

# Get top 3 scorers
top_scorers = (
        df.sort_values('PTS', ascending=False)
            .head(10)[['PLAYER_NAME', 'TEAM_ABBREVIATION', 'PTS', 'PLUS_MINUS']]
)

# Print without the DataFrame index
# Ensure output directory exists
os.makedirs('data', exist_ok=True)

# Convert to list of dicts and write JSON
output_records = top_scorers.to_dict(orient='records')
output_path = os.path.join('data', f"top_scorers_{yesterday}.json")
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(output_records, f, ensure_ascii=False, indent=2)

print(f"Wrote top scorers JSON to {output_path}")
