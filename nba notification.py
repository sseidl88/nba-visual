from nba_api.stats.endpoints import scoreboardv3, boxscoretraditionalv3
from nba_api.library.http import NBAStatsHTTP
from datetime import datetime, timedelta
import pandas as pd
import json
import os

# Required headers — stats.nba.com blocks requests that don't look like a browser
NBAStatsHTTP.headers = {
    'Host': 'stats.nba.com',
    'Connection': 'keep-alive',
    'Accept': 'application/json, text/plain, */*',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.nba.com/',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Get yesterday's date
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

# Get scoreboard (games played)
scoreboard = scoreboardv3.ScoreboardV3(game_date=yesterday, timeout=60)
games = scoreboard.score_board.get_data_frame()

all_players = []

for game_id in games["gameId"].unique():
    boxscore = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=60)
    players = boxscore.player_stats.get_data_frame()

    pm_candidates = ['plusMinus', 'PLUS_MINUS', 'PlusMinus', 'plus_minus', '+/-', 'PLUS-MINUS', 'plusMinusPoints']
    pm_col = next((c for c in pm_candidates if c in players.columns), None)
    if pm_col:
        players['PLUS_MINUS'] = players[pm_col]

    all_players.append(players)

# Combine all player stats
if not all_players:
    print('No games found for', yesterday)
    df = pd.DataFrame(columns=["PLAYER_NAME", "TEAM_ABBREVIATION", "PTS", "PLUS_MINUS"])
else:
    df = pd.concat(all_players, ignore_index=True)

# Normalize column names to what the HTML expects
if 'PTS' not in df.columns:
    df['PTS'] = df.get('points', 0)

if 'PLAYER_NAME' not in df.columns:
    if 'firstName' in df.columns and 'familyName' in df.columns:
        df['PLAYER_NAME'] = df['firstName'].fillna('') + ' ' + df['familyName'].fillna('')
    else:
        df['PLAYER_NAME'] = df.get('name', '')

if 'TEAM_ABBREVIATION' not in df.columns:
    df['TEAM_ABBREVIATION'] = df.get('teamTricode', df.get('teamAbbreviation', ''))

if 'PLUS_MINUS' not in df.columns:
    df['PLUS_MINUS'] = pd.NA

top_scorers = (
    df.sort_values('PTS', ascending=False)
      .head(10)[['PLAYER_NAME', 'TEAM_ABBREVIATION', 'PTS', 'PLUS_MINUS']]
)

os.makedirs('docs/data', exist_ok=True)

output_path = os.path.join('docs', 'data', f"top_scorers_{yesterday}.json")
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(top_scorers.to_dict(orient='records'), f, ensure_ascii=False, indent=2)

print(f"Wrote top scorers JSON to {output_path}")
