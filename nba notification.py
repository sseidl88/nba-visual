from nba_api.stats.endpoints import scoreboardv2, boxscoretraditionalv3
from datetime import datetime, timedelta
import pandas as pd
from twilio.rest import Client

# Get yesterday's date
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

# Get scoreboard (games played)
scoreboard = scoreboardv2.ScoreboardV2(game_date=yesterday)
games = scoreboard.game_header.get_data_frame()

all_players = []

for game_id in games["GAME_ID"].unique():
    boxscore = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id)
    players = boxscore.player_stats.get_data_frame()
    all_players.append(players)

# Combine all player stats
if not all_players:
    print('No player stats were retrieved for', yesterday)
    df = pd.DataFrame(columns=["PLAYER_NAME", "TEAM_ABBREVIATION", "PTS"])
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

# Get top 3 scorers
top_scorers = (
    df.sort_values("PTS", ascending=False)
      .head(3)[["PLAYER_NAME", "TEAM_ABBREVIATION", "PTS"]]
)

#print(top_scorers)



account_sid = "ACc93248aea47ac2c49f0df11b02b7d006"
auth_token = "8842b22ad94950030fa104cc5347158f"
client = Client(account_sid, auth_token)

message_body = "Top scorers last night:\n"
for _, row in top_scorers.iterrows():
    message_body += f"{row['PLAYER_NAME']} ({row['TEAM_ABBREVIATION']}): {row['PTS']} pts\n"

client.messages.create(
    body=message_body,
    from_="+18884475179",   # Twilio number
    to="+19139801277"
)
