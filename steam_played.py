"""Refreshes the "steam hours" table in Notion: every game with playtime, total hours and last two weeks."""
import os, time, datetime, requests

STEAM_ID = os.environ.get("STEAM_ID", "76561199240283007")
KEY = os.environ.get("STEAM_KEY", "")
DB = os.environ["NOTION_PLAYED_DB"]
NH = {"Authorization": "Bearer " + os.environ["NOTION_TOKEN"], "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
API = "https://api.notion.com/v1"

def notion(method, path, body=None):
    for attempt in range(5):
        r = requests.request(method, API + path, headers=NH, json=body, timeout=30)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(1.5 * (attempt + 1)); continue
        r.raise_for_status(); return r.json()
    r.raise_for_status()

def props(g):
    last = g.get("rtime_last_played")
    return {
        "Name": {"title": [{"type": "text", "text": {"content": (g.get("name") or str(g["appid"]))[:200]}}]},
        "Hours": {"number": round(g.get("playtime_forever", 0) / 60, 1)},
        "Last 2 weeks": {"number": round(g.get("playtime_2weeks", 0) / 60, 1)},
        "Last played": {"date": {"start": datetime.datetime.fromtimestamp(last, datetime.timezone.utc).strftime("%Y-%m-%d")} if last else None},
        "Store": {"url": "https://store.steampowered.com/app/%s" % g["appid"]},
        "App ID": {"number": g["appid"]},
    }

def main():
    if not KEY:
        print("no STEAM_KEY secret set. skipping hours."); return
    r = requests.get("https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/",
                     params={"key": KEY, "steamid": STEAM_ID, "include_appinfo": 1, "include_played_free_games": 1}, timeout=30)
    if r.status_code in (401, 403):
        raise SystemExit("steam rejected the key (status %s). check the STEAM_KEY secret." % r.status_code)
    r.raise_for_status()
    games = [g for g in r.json().get("response", {}).get("games", []) if g.get("playtime_forever", 0) > 0]
    if not games:
        print("steam returned no played games (are game details and playtime still public?). leaving the table as it is."); return
    games.sort(key=lambda g: -g["playtime_forever"])
    rows, cursor = {}, None
    while True:
        body = {"page_size": 100}
        if cursor: body["start_cursor"] = cursor
        q = notion("POST", "/databases/%s/query" % DB, body)
        for p in q["results"]:
            rows[p["properties"]["App ID"]["number"]] = (p["id"], p["properties"]["Hours"]["number"], p["properties"]["Last 2 weeks"]["number"])
        if not q.get("has_more"): break
        cursor = q["next_cursor"]
    made = updated = 0
    for g in games:
        p = props(g)
        if g["appid"] in rows:
            pid, hours, recent = rows[g["appid"]]
            if hours == p["Hours"]["number"] and recent == p["Last 2 weeks"]["number"]:
                continue
            notion("PATCH", "/pages/" + pid, {"properties": p}); updated += 1
        else:
            img = "https://cdn.akamai.steamstatic.com/steam/apps/%s/header.jpg" % g["appid"]
            notion("POST", "/pages", {"parent": {"database_id": DB}, "properties": p, "cover": {"type": "external", "external": {"url": img}}}); made += 1
        time.sleep(0.35)
    print("played games: %d, added %d, updated %d" % (len(games), made, updated))

if __name__ == "__main__":
    main()
