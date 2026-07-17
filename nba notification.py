from datetime import datetime, timedelta
import requests
import json
import os

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
SUMMARY    = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"
TEAMS_URL  = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams"


def safe_get(url, **params):
    r = requests.get(url, params=params or None, timeout=30)
    return r


def parse_box_score(summary_json):
    """Return per-player records from a game summary response."""
    records = []
    for team in summary_json.get("boxscore", {}).get("players", []):
        abbrev = team.get("team", {}).get("abbreviation", "")
        for group in team.get("statistics", []):
            names = group.get("names", group.get("labels", []))
            if "PTS" not in names:
                continue
            pts_idx = names.index("PTS")
            pm_idx  = names.index("+/-") if "+/-" in names else None
            for ath_data in group.get("athletes", []):
                stats = ath_data.get("stats", [])
                ath   = ath_data.get("athlete", {})
                name  = ath.get("displayName", "")
                aid   = str(ath.get("id", ""))
                if not name:
                    continue
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
                records.append({
                    "_id": aid, "PLAYER_NAME": name,
                    "TEAM_ABBREVIATION": abbrev, "PTS": pts, "PLUS_MINUS": pm,
                })
            break  # only first group containing PTS
    return records


now       = datetime.now()
yesterday = now - timedelta(days=1)
date_str  = yesterday.strftime("%Y-%m-%d")


# ── yesterday's top scorers ──────────────────────────────────────────────────

yest_resp   = safe_get(SCOREBOARD, dates=yesterday.strftime("%Y%m%d"))
yest_events = yest_resp.json().get("events", []) if yest_resp.ok else []

all_yesterday = []
for event in yest_events:
    r = safe_get(SUMMARY, event=event["id"])
    if r.ok:
        all_yesterday.extend(parse_box_score(r.json()))

if not all_yesterday:
    print(f"No WNBA games found for {date_str}")

top_scorers = [
    {k: v for k, v in p.items() if k != "_id"}
    for p in sorted(all_yesterday, key=lambda x: x["PTS"], reverse=True)[:10]
]


# ── aggregate last 14 days for PPG ──────────────────────────────────────────

totals    = {}   # athlete_id → {name, team, pts, games}
MAX_GAMES = 40   # cap total box score fetches to stay within CI time limits
game_calls = 0

for offset in range(1, 15):
    if game_calls >= MAX_GAMES:
        break
    d = (now - timedelta(days=offset)).strftime("%Y%m%d")
    r = safe_get(SCOREBOARD, dates=d)
    if not r.ok:
        continue
    for event in r.json().get("events", []):
        if game_calls >= MAX_GAMES:
            break
        gr = safe_get(SUMMARY, event=event["id"])
        if not gr.ok:
            continue
        game_calls += 1
        for p in parse_box_score(gr.json()):
            aid = p["_id"] or p["PLAYER_NAME"]
            if aid not in totals:
                totals[aid] = {
                    "PLAYER_NAME": p["PLAYER_NAME"],
                    "TEAM_ABBREVIATION": p["TEAM_ABBREVIATION"],
                    "pts": 0, "games": 0,
                }
            totals[aid]["pts"]   += p["PTS"]
            totals[aid]["games"] += 1

ppg_rows = sorted(
    [
        {"_id": kid,
         "PLAYER_NAME": v["PLAYER_NAME"],
         "TEAM_ABBREVIATION": v["TEAM_ABBREVIATION"],
         "PPG": round(v["pts"] / v["games"], 1)}
        for kid, v in totals.items() if v["games"] > 0
    ],
    key=lambda x: x["PPG"],
    reverse=True,
)

season_ppg = [{"PLAYER_NAME": p["PLAYER_NAME"], "TEAM_ABBREVIATION": p["TEAM_ABBREVIATION"], "PPG": p["PPG"]} for p in ppg_rows[:10]]


# ── identify rookies from team rosters ───────────────────────────────────────

rookie_ids = set()
try:
    tr = safe_get(TEAMS_URL)
    if tr.ok:
        leagues = tr.json().get("sports", [{}])[0].get("leagues", [{}])[0]
        for team_entry in leagues.get("teams", []):
            tid = team_entry.get("team", {}).get("id")
            if not tid:
                continue
            rr = safe_get(f"{TEAMS_URL}/{tid}/roster")
            if not rr.ok:
                continue
            athletes_raw = rr.json().get("athletes", [])
            # Roster may group players by position: [{items: [...]}, ...]
            if athletes_raw and "items" in (athletes_raw[0] if athletes_raw else {}):
                athletes_flat = [a for grp in athletes_raw for a in grp.get("items", [])]
            else:
                athletes_flat = athletes_raw
            for a in athletes_flat:
                if a.get("experience", {}).get("years", -1) == 0:
                    rookie_ids.add(str(a.get("id", "")))
    print(f"Found {len(rookie_ids)} rookies across all rosters")
except Exception as e:
    print(f"Rookie detection error: {e}")

rookie_ppg = [
    {"PLAYER_NAME": p["PLAYER_NAME"], "TEAM_ABBREVIATION": p["TEAM_ABBREVIATION"], "PPG": p["PPG"]}
    for p in ppg_rows
    if p["_id"] in rookie_ids
][:10]


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
