from datetime import datetime, timedelta
import requests
import json
import os


def espn_get(url, **params):
    r = requests.get(url, params=params or None, timeout=30)
    r.raise_for_status()
    return r.json()


# ── yesterday's top scorers ──────────────────────────────────────────────────

yesterday = datetime.now() - timedelta(days=1)
date_str  = yesterday.strftime("%Y-%m-%d")
espn_date = yesterday.strftime("%Y%m%d")

events = espn_get(
    "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    dates=espn_date,
).get("events", [])

all_players = []
for event in events:
    try:
        summary = espn_get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary",
            event=event["id"],
        )
    except Exception:
        continue

    for team in summary.get("boxscore", {}).get("players", []):
        abbrev = team.get("team", {}).get("abbreviation", "")
        for group in team.get("statistics", []):
            names = group.get("names", group.get("labels", []))
            if "PTS" not in names:
                continue
            pts_idx = names.index("PTS")
            pm_idx  = names.index("+/-") if "+/-" in names else None

            for athlete in group.get("athletes", []):
                stats = athlete.get("stats", [])
                name  = athlete.get("athlete", {}).get("displayName", "")
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


# ── season / rookie PPG leaders ──────────────────────────────────────────────

def parse_ppg_leaders(data):
    """Pull scoring leaders out of an ESPN /leaders response."""
    for cat in data.get("leaders", []):
        if "point" in cat.get("name", "").lower():
            result = []
            for entry in cat.get("leaders", []):
                athlete = entry.get("athlete", {})
                team    = entry.get("team", {})
                result.append({
                    "PLAYER_NAME":     athlete.get("displayName", ""),
                    "TEAM_ABBREVIATION": team.get("abbreviation", ""),
                    "PPG":             entry.get("displayValue", ""),
                })
            return result[:10]
    return []


LEADERS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/leaders"

season_ppg = parse_ppg_leaders(espn_get(LEADERS_URL, limit=10))

# ESPN uses groups=50 for the rookie cohort in basketball stat leaders
try:
    rookie_ppg = parse_ppg_leaders(espn_get(LEADERS_URL, limit=10, groups=50))
except Exception as e:
    print(f"Rookie PPG fetch failed: {e}")
    rookie_ppg = []


# ── write output ─────────────────────────────────────────────────────────────

os.makedirs("docs/data", exist_ok=True)

outputs = {
    f"top_scorers_{date_str}.json": top_scorers,
    "season_ppg.json":              season_ppg,
    "rookie_ppg.json":              rookie_ppg,
}

for filename, data in outputs.items():
    path = os.path.join("docs", "data", filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(data)} records → {path}")
