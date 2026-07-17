from datetime import datetime, timedelta
import requests
import json
import os

yesterday = datetime.now() - timedelta(days=1)
date_str = yesterday.strftime("%Y-%m-%d")
espn_date = yesterday.strftime("%Y%m%d")

resp = requests.get(
    "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    params={"dates": espn_date},
    timeout=30,
)
resp.raise_for_status()
events = resp.json().get("events", [])

all_players = []

for event in events:
    summary_resp = requests.get(
        "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary",
        params={"event": event["id"]},
        timeout=30,
    )
    if not summary_resp.ok:
        continue

    for team in summary_resp.json().get("boxscore", {}).get("players", []):
        abbrev = team.get("team", {}).get("abbreviation", "")
        for group in team.get("statistics", []):
            names = group.get("names", group.get("labels", []))
            if "PTS" not in names:
                continue
            pts_idx = names.index("PTS")
            pm_idx = names.index("+/-") if "+/-" in names else None

            for athlete in group.get("athletes", []):
                stats = athlete.get("stats", [])
                name = athlete.get("athlete", {}).get("displayName", "")

                try:
                    pts = int(float(stats[pts_idx])) if stats[pts_idx] not in ("--", "") else 0
                except (IndexError, ValueError):
                    pts = 0

                pm = None
                if pm_idx is not None and len(stats) > pm_idx:
                    try:
                        raw = stats[pm_idx]
                        pm = int(float(raw)) if raw not in ("--", "") else None
                    except ValueError:
                        pm = None

                all_players.append({
                    "PLAYER_NAME": name,
                    "TEAM_ABBREVIATION": abbrev,
                    "PTS": pts,
                    "PLUS_MINUS": pm,
                })

if not all_players:
    print(f"No WNBA games found for {date_str}")

top_scorers = sorted(all_players, key=lambda x: x["PTS"], reverse=True)[:10]

os.makedirs("docs/data", exist_ok=True)
output_path = os.path.join("docs", "data", f"top_scorers_{date_str}.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(top_scorers, f, ensure_ascii=False, indent=2)

print(f"Wrote {len(top_scorers)} WNBA top scorers for {date_str} to {output_path}")
