# nba-visual

GitHub Pages stats dashboard covering WNBA, NBA, NCAA Men's, and NCAA Women's basketball.

**Repo:** sseidl88/nba-visual  
**Live site:** GitHub Pages serving from `docs/` on `main` branch

---

## Key rules

- **NEVER use `stats.nba.com`** — blocked at the network level from GitHub Actions IP ranges. No header workaround exists.
- **NEVER use the `nba_api` Python library** — it hits nba.com under the hood. Same block applies.
- **NEVER use the ESPN `/leaders` endpoint** — returns 404 for WNBA/NCAA. NBA-only and unreliable.
- Always `git pull --rebase origin main` before `git push` in CI to avoid race conditions when Actions and local pushes collide.
- Data source is **ESPN public API (`site.api.espn.com`) only** — works from GitHub Actions IPs and browser cross-origin.

---

## Architecture

```
ESPN API → nba notification.py (GitHub Actions daily cron)
         → JSON files committed to docs/data/{league}/
         → GitHub Pages serves docs/ as static site
         → docs/index.html reads JSON via fetch()
```

- No build step — all JS inline in `docs/index.html`, styles in `docs/style.css`
- JSON files in the repo are the database — simple, versioned, free
- Workflow: `.github/workflows/static.yml` — cron `0 9 * * *` + `workflow_dispatch`

---

## Python script (`nba notification.py`)

Parameterized with `--league {wnba,nba,ncaam,ncaaw}`. Outputs JSON to the league-specific data dir.

**Data dirs:**
| Flag | Dir |
|------|-----|
| `--league wnba` | `docs/data/` |
| `--league nba` | `docs/data/nba/` |
| `--league ncaam` | `docs/data/ncaam/` |
| `--league ncaaw` | `docs/data/ncaaw/` |

**ESPN league slugs (used in URLs):**
| Flag | ESPN slug |
|------|-----------|
| `wnba` | `wnba` |
| `nba` | `nba` |
| `ncaam` | `mens-college-basketball` |
| `ncaaw` | `womens-college-basketball` |

**Key notes:**
- `MAX_GAMES = 150` for NCAA, `90` for pro (NCAA has far more games per day)
- Skip team roster loop for NCAA (`IS_NCAA` flag) — 360+ teams would timeout Actions
- `experience.years == 0` in ESPN roster data = rookie (pro) or freshman (NCAA)
- True Shooting %: `PTS / (2 × (FGA + 0.44 × FTA)) × 100`
- PPG is computed from 30 days of box scores — no ESPN season-stats endpoint exists for WNBA/NCAA

---

## ESPN API endpoints

```
https://site.api.espn.com/apis/site/v2/sports/basketball/{slug}/scoreboard?dates=YYYYMMDD
https://site.api.espn.com/apis/site/v2/sports/basketball/{slug}/summary?event={id}
https://site.api.espn.com/apis/site/v2/sports/basketball/{slug}/teams
https://site.api.espn.com/apis/site/v2/sports/basketball/{slug}/teams/{id}/roster
https://site.api.espn.com/apis/site/v2/sports/basketball/{slug}/news
https://site.api.espn.com/apis/v2/sports/basketball/{slug}/standings
```

**Player headshots:** `https://a.espncdn.com/i/headshots/{slug}/players/full/{id}.png`

---

## Frontend (`docs/index.html`)

**Key JS patterns:**
- `activeLeague` state drives all data fetching — one of `wnba | nba | ncaam | ncaaw`
- `dataPath(file)` — routes to the correct `data/{league}/` directory
- `espnSlug()` — maps `activeLeague` to the ESPN API slug for live fetches (news, schedule)
- `photoUrl(id)` — builds ESPN CDN headshot URL using `espnSlug()`
- `applyFilter()` is async — **never call it from inside a render function** (causes infinite recursion)
- All caches (`ppgData`, `standingsCache`, `playerGamesCache`, etc.) are cleared on `switchLeague()`
- URL params `?league=nba&team=MIN` make views shareable via `history.replaceState`

**ESPN data quirks:**
- WNBA: ESPN marks all players `type: "active"` in roster → injury data is always empty
- NCAA standings: `children[]` array of conferences (32 for NCAAM), each with `standings.entries[]`
