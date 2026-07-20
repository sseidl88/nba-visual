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

            def col(stat):
                return names.index(stat) if stat in names else None

            pts_idx = col("PTS")
            pm_idx  = col("+/-")
            ast_idx = col("AST")
            reb_idx = col("REB")
            blk_idx = col("BLK")
            fg_idx  = col("FG")

            for ath_data in group.get("athletes", []):
                stats = ath_data.get("stats", [])
                ath   = ath_data.get("athlete", {})
                name  = ath.get("displayName", "")
                aid   = str(ath.get("id", ""))
                if not name:
                    continue

                def stat_int(i):
                    if i is None or i >= len(stats):
                        return 0
                    try:
                        return int(float(stats[i])) if stats[i] not in ("--", "") else 0
                    except (ValueError, TypeError):
                        return 0

                pts = stat_int(pts_idx)
                ast = stat_int(ast_idx)
                reb = stat_int(reb_idx)
                blk = stat_int(blk_idx)

                pm = None
                if pm_idx is not None and pm_idx < len(stats):
                    try:
                        raw = stats[pm_idx]
                        pm = int(float(raw)) if raw not in ("--", "") else None
                    except (ValueError, TypeError):
                        pm = None

                fgm, fga = 0, 0
                if fg_idx is not None and fg_idx < len(stats):
                    fg_str = stats[fg_idx]
                    if fg_str and fg_str != "--" and "-" in str(fg_str):
                        try:
                            parts = str(fg_str).split("-")
                            fgm, fga = int(parts[0]), int(parts[1])
                        except (ValueError, IndexError):
                            pass

                records.append({
                    "_id": aid, "PLAYER_NAME": name,
                    "TEAM_ABBREVIATION": abbrev,
                    "PTS": pts, "PLUS_MINUS": pm,
                    "AST": ast, "REB": reb, "BLK": blk,
                    "FGM": fgm, "FGA": fga,
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

totals    = {}   # athlete_id → {name, team, totals, recent 7d, older 7d}
MAX_GAMES = 50   # cap total box score fetches to stay within CI time limits
game_calls = 0

for offset in range(1, 15):
    if game_calls >= MAX_GAMES:
        break
    is_recent = offset <= 7   # days 1-7 = recent half; days 8-14 = older half
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
                    # overall
                    "pts": 0, "ast": 0, "reb": 0, "blk": 0, "fgm": 0, "fga": 0, "games": 0,
                    # recent 7 days
                    "r_pts": 0, "r_ast": 0, "r_reb": 0, "r_blk": 0, "r_fgm": 0, "r_fga": 0, "r_games": 0,
                    # older 7 days
                    "o_pts": 0, "o_ast": 0, "o_reb": 0, "o_blk": 0, "o_fgm": 0, "o_fga": 0, "o_games": 0,
                }
            for stat, key in [("PTS","pts"),("AST","ast"),("REB","reb"),("BLK","blk"),("FGM","fgm"),("FGA","fga")]:
                totals[aid][key] += p[stat]
            totals[aid]["games"] += 1
            pfx = "r_" if is_recent else "o_"
            for stat, key in [("PTS","pts"),("AST","ast"),("REB","reb"),("BLK","blk"),("FGM","fgm"),("FGA","fga")]:
                totals[aid][f"{pfx}{key}"] += p[stat]
            totals[aid][f"{pfx}games"] += 1

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
    {
        "PLAYER_NAME":     v["PLAYER_NAME"],
        "TEAM_ABBREVIATION": v["TEAM_ABBREVIATION"],
        "PPG":  round(v["pts"] / v["games"], 1),
        "APG":  round(v["ast"] / v["games"], 1),
        "RPG":  round(v["reb"] / v["games"], 1),
        "BPG":  round(v["blk"] / v["games"], 1),
        "FG_PCT": round(v["fgm"] / v["fga"] * 100, 1) if v["fga"] > 0 else 0,
    }
    for kid, v in sorted(totals.items(), key=lambda kv: kv[1]["pts"] / max(kv[1]["games"], 1), reverse=True)
    if kid in rookie_ids and v["games"] > 0
][:10]


# ── trending players ─────────────────────────────────────────────────────────

def per_game_stats(v, pfx=""):
    g   = v[f"{pfx}games"]
    fga = v[f"{pfx}fga"]
    if g == 0:
        return None
    return {
        "PPG":    round(v[f"{pfx}pts"] / g, 1),
        "APG":    round(v[f"{pfx}ast"] / g, 1),
        "RPG":    round(v[f"{pfx}reb"] / g, 1),
        "BPG":    round(v[f"{pfx}blk"] / g, 1),
        "FG_PCT": round(v[f"{pfx}fgm"] / fga * 100, 1) if fga > 0 else 0.0,
    }

trend_candidates = []
for v in totals.values():
    # Require at least 2 games in each half to avoid single-game noise
    if v["r_games"] < 2 or v["o_games"] < 2:
        continue
    recent = per_game_stats(v, "r_")
    avg    = per_game_stats(v)
    older  = per_game_stats(v, "o_")
    if not recent or not avg or not older:
        continue
    delta = {k: round(recent[k] - avg[k], 1) for k in recent}
    score = recent["PPG"] - older["PPG"]   # positive = trending up
    trend_candidates.append({
        "score":           score,
        "PLAYER_NAME":     v["PLAYER_NAME"],
        "TEAM_ABBREVIATION": v["TEAM_ABBREVIATION"],
        "recent_games":    v["r_games"],
        "recent":          recent,
        "avg":             avg,
        "delta":           delta,
    })

trend_candidates.sort(key=lambda x: x["score"], reverse=True)

def strip_score(entry):
    return {k: v for k, v in entry.items() if k != "score"}

trending_up   = strip_score(trend_candidates[0])  if trend_candidates else {}
trending_down = strip_score(trend_candidates[-1]) if trend_candidates else {}


# ── write output ─────────────────────────────────────────────────────────────

os.makedirs("docs/data", exist_ok=True)

outputs = {
    f"top_scorers_{date_str}.json": top_scorers,
    "season_ppg.json":              season_ppg,
    "rookie_ppg.json":              rookie_ppg,
    "trending_up.json":             trending_up,
    "trending_down.json":           trending_down,
}

for filename, data in outputs.items():
    path = os.path.join("docs", "data", filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(data)} records → {path}")
