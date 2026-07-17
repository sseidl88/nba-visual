from nba_api.stats.endpoints import scoreboardv2, boxscoretraditionalv2
from nba_api.library.http import NBAStatsHTTP
from datetime import datetime, timedelta
import pandas as pd
import json
import os

# stats.nba.com blocks requests that don't look like a browser
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

yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

# WNBA league_id is '10'
scoreboard = scoreboardv2.ScoreboardV2(game_date=yesterday, league_id='10', timeout=60)
games = scoreboard.game_header.get_data_frame()

all_players = []

for game_id in games["GAME_ID"].unique():
    boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id, timeout=60)
    players = boxscore.player_stats.get_data_frame()
    all_players.append(players)

if not all_players:
    print('No WNBA games found for', yesterday)
    df = pd.DataFrame(columns=["PLAYER_NAME", "TEAM_ABBREVIATION", "PTS", "PLUS_MINUS"])
else:
    df = pd.concat(all_players, ignore_index=True)

# BoxScoreTraditionalV2 already returns PLAYER_NAME, TEAM_ABBREVIATION, PTS, PLUS_MINUS
top_scorers = (
    df.sort_values('PTS', ascending=False)
      .head(10)[['PLAYER_NAME', 'TEAM_ABBREVIATION', 'PTS', 'PLUS_MINUS']]
)

os.makedirs('docs/data', exist_ok=True)

output_path = os.path.join('docs', 'data', f"top_scorers_{yesterday}.json")
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(top_scorers.to_dict(orient='records'), f, ensure_ascii=False, indent=2)

print(f"Wrote WNBA top scorers JSON to {output_path}")
