"""Refreshes the "steam wishlist" table in Notion from a public Steam wishlist."""
import os, json, time, datetime, requests

STEAM_ID = os.environ.get("STEAM_ID", "76561199240283007")
DB = os.environ["NOTION_DB"]
NH = {"Authorization": "Bearer " + os.environ["NOTION_TOKEN"], "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
API = "https://api.notion.com/v1"

def notion(method, path, body=None):
    for attempt in range(5):
        r = requests.request(method, API + path, headers=NH, json=body, timeout=30)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(1.5 * (attempt + 1)); continue
        r.raise_for_status(); return r.json()
    r.raise_for_status()

def steam_wishlist():
    r = requests.get("https://api.steampowered.com/IWishlistService/GetWishlist/v1/", params={"steamid": STEAM_ID}, timeout=30)
    r.raise_for_status()
    wl = r.json().get("response", {}).get("items", [])
    added = {w["appid"]: w.get("date_added") for w in wl}
    games = []
    for i in range(0, len(wl), 50):
        q = {"ids": [{"appid": w["appid"]} for w in wl[i:i + 50]],
             "context": {"language": "english", "country_code": "US"},
             "data_request": {"include_basic_info": True, "include_release": True}}
        r = requests.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/", params={"input_json": json.dumps(q)}, timeout=30)
        r.raise_for_status()
        for s in r.json().get("response", {}).get("store_items", []):
            b = s.get("best_purchase_option") or {}
            ends = [d.get("discount_end_date") for d in b.get("active_discounts", []) if d.get("discount_end_date")]
            pct = b.get("discount_pct") or 0
            price = int(b["final_price_in_cents"]) / 100 if b.get("final_price_in_cents") else None
            full = int(b["original_price_in_cents"]) / 100 if b.get("original_price_in_cents") else price
            status = "on sale" if pct else "free" if s.get("is_free") else "full price" if price is not None else "not out yet"
            games.append({"appid": s["appid"], "name": s.get("name") or str(s["appid"]), "price": 0 if status == "free" else price,
                          "full": full, "pct": pct, "ends": min(ends) if ends else None, "status": status,
                          "url": "https://store.steampowered.com/" + s.get("store_url_path", "app/%s" % s["appid"]),
                          "added": added.get(s["appid"])})
    return games

def iso(ts, day=False):
    d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    return d.strftime("%Y-%m-%d") if day else d.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def props(g):
    return {
        "Name": {"title": [{"type": "text", "text": {"content": g["name"][:200]}}]},
        "Price": {"number": g["price"]}, "Full price": {"number": g["full"]},
        "Discount": {"number": g["pct"] / 100 if g["pct"] else None},
        "Sale ends": {"date": {"start": iso(g["ends"])} if g["ends"] else None},
        "Status": {"select": {"name": g["status"]}},
        "Store": {"url": g["url"]},
        "Wishlisted": {"date": {"start": iso(g["added"], True)} if g["added"] else None},
        "App ID": {"number": g["appid"]},
    }

def existing():
    rows, cursor = {}, None
    while True:
        body = {"page_size": 100}
        if cursor: body["start_cursor"] = cursor
        r = notion("POST", "/databases/%s/query" % DB, body)
        for p in r["results"]:
            rows[p["properties"]["App ID"]["number"]] = p["id"]
        if not r.get("has_more"): return rows
        cursor = r["next_cursor"]

def main():
    games = sorted(steam_wishlist(), key=lambda g: (-g["pct"], g["name"].lower()))
    if not games:
        print("wishlist came back empty (is it still public?). leaving the table as it is."); return
    rows = existing(); made = updated = 0
    for g in games:
        if g["appid"] in rows:
            notion("PATCH", "/pages/" + rows[g["appid"]], {"properties": props(g)}); updated += 1
        else:
            img = "https://cdn.akamai.steamstatic.com/steam/apps/%s/header.jpg" % g["appid"]
            notion("POST", "/pages", {"parent": {"database_id": DB}, "properties": props(g),
                                      "cover": {"type": "external", "external": {"url": img}}}); made += 1
        time.sleep(0.35)
    gone = [pid for appid, pid in rows.items() if appid not in {g["appid"] for g in games}]
    for pid in gone:
        notion("PATCH", "/pages/" + pid, {"archived": True}); time.sleep(0.35)
    print("added %d, updated %d, removed %d" % (made, updated, len(gone)))

if __name__ == "__main__":
    main()
