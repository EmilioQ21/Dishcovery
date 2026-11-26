"""Dishcovery command line client.

    python -m dishcovery --help
    python -m dishcovery shell          # interactive mode (connections stay open between commands)
"""
import argparse
import getpass
import json
import shlex
import sys
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dishcovery import config
from dishcovery.services.errors import DishcoveryError

console = Console()


# ------------------------------------------------------------------ helpers
def table(title, columns, rows):
    t = Table(title=title, header_style="bold cyan", show_lines=False)
    for c in columns:
        t.add_column(c)
    for r in rows:
        t.add_row(*["" if v is None else (v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else str(v)) for v in r])
    console.print(t)


def show_json(obj, title=None):
    text = json.dumps(obj, indent=2, default=str, ensure_ascii=False)
    console.print(Panel(text, title=title) if title else text)


def csv_list(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def stars(n):
    return "*" * int(round(n or 0))


def current_user():
    from dishcovery.services.users import user_from_token
    if not config.SESSION_FILE.exists():
        raise DishcoveryError("not logged in: run `login --email ...` first")
    return user_from_token(config.SESSION_FILE.read_text().strip())


def status_line(status):
    console.print("  written to: " + "  ".join(("[green]%s OK[/]" if ok else "[red]%s QUEUED[/]") % db
                                                for db, ok in status.items()))


# ------------------------------------------------------------------ users (FR-01..FR-05, FR-12..FR-14)
def cmd_register(a):
    from dishcovery.services import users
    pw = a.password or getpass.getpass("Password: ")
    u = users.register(a.email, pw, a.name, a.city)
    console.print("[green]Registered[/] %s (%s). Now run: login --email %s" % (u["_id"], u["email"], u["email"]))


def cmd_login(a):
    from dishcovery.services import users
    token, uid = users.login(a.email, a.password or getpass.getpass("Password: "))
    config.SESSION_FILE.write_text(token)
    console.print("[green]Logged in[/] as %s. Session valid for %d h." % (uid, config.SESSION_HOURS))


def cmd_logout(a):
    from dishcovery.services import users
    if config.SESSION_FILE.exists():
        users.logout(config.SESSION_FILE.read_text().strip())
        config.SESSION_FILE.unlink()
    console.print("Logged out.")


def cmd_whoami(a):
    from dishcovery.services import users
    show_json(users.get_user(current_user()), "Profile")


def cmd_profile(a):
    from dishcovery.services import users
    show_json(users.update_profile(current_user(), name=a.name, city=a.city, bio=a.bio, photo_url=a.photo), "Updated profile")


def cmd_prefs(a):
    from dishcovery.services import users
    pr = [int(x) for x in a.price.split("-")] if a.price else None
    prefs = users.set_preferences(current_user(), csv_list(a.cuisines) if a.cuisines is not None else None,
                                  csv_list(a.dietary) if a.dietary is not None else None, pr)
    show_json(prefs, "Preferences")


def cmd_delete_account(a):
    from dishcovery.services import users
    if not a.yes:
        raise DishcoveryError("this deletes your account in all 4 databases; repeat with --yes")
    uid = current_user()
    users.delete_account(uid)
    config.SESSION_FILE.unlink(missing_ok=True)
    console.print("[yellow]Account %s deleted[/] (MongoDB, Dgraph, Cassandra partitions, ChromaDB reviews)." % uid)


def cmd_fav(a):
    from dishcovery.services import users
    uid = current_user()
    if a.action == "list":
        fav = users.get_user(uid)["favorites"]
    elif a.action == "add":
        fav = users.add_favorite(uid, a.kind, a.ref_id)
    else:
        fav = users.remove_favorite(uid, a.kind, a.ref_id)
    show_json(fav, "Favorites")


def cmd_list(a):
    from dishcovery.services import users
    uid = current_user()
    if a.action == "create":
        show_json(users.create_list(uid, a.args[0]), "List created")
    elif a.action == "add":
        show_json(users.add_to_list(uid, a.args[0], a.args[1], a.args[2]), "List")
    elif a.action == "remove":
        show_json(users.remove_from_list(uid, a.args[0], a.args[1]), "List")
    elif a.action == "delete":
        users.delete_list(uid, a.args[0])
        console.print("List deleted.")
    else:
        for lst in users.get_lists(uid):
            table("%s  %s" % (lst["_id"], lst["name"]), ["type", "id"], [(i["type"], i["ref_id"]) for i in lst["items"]])


# ------------------------------------------------------------------ catalog (FR-06..FR-11)
def cmd_restaurant(a):
    from dishcovery.queries import mongo_queries as mq
    from dishcovery.services import catalog
    if a.action == "create":
        attrs = {k: True for k in csv_list(a.attributes)}
        r = catalog.create_restaurant(a.name, csv_list(a.cuisine), a.price, a.lon, a.lat, a.city,
                                      a.street or "", a.neighborhood or "", a.description or "", attrs)
        console.print("[green]Created[/] %s %s (MongoDB + Dgraph + ChromaDB)" % (r["_id"], r["name"]))
        return
    r = catalog.get_restaurant(a.id)
    hours = ", ".join("%s %s" % (d, "closed" if h.get("closed") else "%s-%s" % (h["open"], h["close"]))
                      for d, h in r.get("hours", {}).items())
    console.print(Panel("[bold]%s[/] (%s)  %s  price %s  rating %.2f (%d reviews)\n%s\n%s, %s, %s\nHours: %s\nAttributes: %s" % (
        r["name"], r["_id"], ", ".join(r["cuisine"]), "$" * r["price_level"], r.get("rating_avg", 0),
        r.get("rating_count", 0), r.get("description", ""), r["address"].get("street", ""),
        r["address"].get("neighborhood", ""), r["address"]["city"], hours,
        ", ".join(k for k, v in r.get("attributes", {}).items() if v)), title="FR-08 restaurant detail (one document)"))
    table("Menu (embedded menu_summary + dishes collection)", ["dish", "name", "price", "rating"],
          [(d["_id"], d["name"], "$%s" % d["price"], "%.1f (%d)" % (d.get("rating_avg", 0), d.get("rating_count", 0)))
           for d in mq.restaurant_dishes(r["_id"])])


def cmd_search(a):
    from dishcovery.services import catalog
    try:
        uid = current_user()
    except DishcoveryError:
        uid = None
    res = catalog.search(a.text, a.cuisine, a.max_price, uid, a.limit)
    table("FR-09 search results", ["id", "name", "cuisine", "price", "rating", "city"],
          [(r["_id"], r["name"], ", ".join(r["cuisine"]), "$" * r["price_level"], "%.2f" % r.get("rating_avg", 0),
            r.get("address", {}).get("city")) for r in res["results"]])
    for facet in ("by_cuisine", "by_price_level", "by_city"):
        if facet in res:
            console.print("  %s: %s" % (facet, ", ".join("%s=%d" % (f["_id"], f["n"]) for f in res[facet])))


def cmd_near(a):
    from dishcovery.services import catalog
    rows = catalog.near(a.lon, a.lat, a.meters, a.max_price)
    table("FR-10 restaurants within %d m ($geoNear)" % a.meters, ["id", "name", "cuisine", "price", "rating", "distance"],
          [(r["_id"], r["name"], r["cuisine"][0], "$" * r["price_level"], "%.2f" % r.get("rating_avg", 0),
            "%d m" % r["distance_m"]) for r in rows])


def cmd_filter(a):
    from dishcovery.services import catalog
    flags = {k: True for k in ("terrace", "vegetarian_options", "pet_friendly", "delivery", "wifi") if getattr(a, k)}
    rows = catalog.filter_attributes(**flags)
    table("FR-11 restaurants with %s" % ", ".join(flags), ["id", "name", "cuisine"],
          [(r["_id"], r["name"], ", ".join(r["cuisine"])) for r in rows])


def cmd_dish(a):
    from dishcovery.services import catalog, chatbot
    if a.action == "add":
        d = catalog.add_dish(a.restaurant, a.name, a.price, a.description or "", csv_list(a.tags), a.vegetarian)
        console.print("[green]Added[/] %s %s to %s (dishes + menu_summary, Dgraph, ChromaDB)" % (d["_id"], d["name"], a.restaurant))
    elif a.action == "similar":
        hits = chatbot.similar(a.id, a.n)
        table("FR-34 dishes similar to %s" % a.id, ["dish", "restaurant", "distance", "text"],
              [(h["id"], h["metadata"]["restaurant_name"], h["distance"], h["document"][:70]) for h in hits])
    else:
        d, r = catalog.view_dish(a.id)
        show_json({k: d[k] for k in ("_id", "name", "price", "description", "tags", "vegetarian", "rating_avg", "rating_count")},
                  "%s at %s (view counted for FR-24)" % (d["name"], r["name"]))


# ------------------------------------------------------------------ reviews (FR-15..FR-19)
def cmd_review(a):
    from dishcovery.services import reviews
    if a.action == "write":
        r, status = reviews.write_review(current_user(), a.restaurant, a.rating, a.text, a.dish)
        console.print("[green]Review %s saved[/]" % r["_id"])
        status_line(status)
    elif a.action == "edit":
        r, status = reviews.edit_review(current_user(), a.id, a.rating, a.text)
        console.print("[green]Review %s updated[/] (rating %d)" % (r["_id"], r["rating"]))
        status_line(status)
    elif a.action == "delete":
        status_line(reviews.delete_review(current_user(), a.id))
    elif a.action == "mine":
        table("My reviews", ["id", "restaurant", "dish", "rating", "date", "text"],
              [(r["_id"], r["restaurant_id"], r.get("dish_id"), stars(r["rating"]), r["created_at"], r["text"][:60])
               for r in reviews.my_reviews(current_user())])
    else:
        rows = reviews.restaurant_reviews(a.id, a.limit)
        table("FR-17 reviews of %s, newest first (Cassandra reviews_by_restaurant)" % a.id,
              ["date", "user", "dish", "rating", "text"],
              [(r.created_at, r.user_name, r.dish_name, stars(r.rating), r.text[:70]) for r in rows])


def cmd_ratings(a):
    from dishcovery.services import reviews
    avg, n = reviews.ratings(a.restaurant, a.dish)
    console.print("FR-18 Pipeline A: average %.2f from %d reviews" % (avg, n))


def cmd_top_dishes(a):
    from dishcovery.services import reviews
    for group in reviews.top_dishes(a.cuisine, a.min_votes, a.top):
        table("FR-19 top dishes: %s" % group["_id"], ["dish", "name", "restaurant", "avg", "votes"],
              [(t["dish_id"], t["dish"], t["restaurant"], t["avg"], t["votes"]) for t in group["top"]])


# ------------------------------------------------------------------ activity (FR-20..FR-25)
def cmd_checkin(a):
    from dishcovery.services import activity
    rest, ts = activity.checkin(current_user(), a.restaurant)
    console.print("[green]Checked in[/] at %s (%s) -> visits_by_user, visits_by_user_month, activity_by_user" % (rest["name"], ts.isoformat()))


def cmd_passport(a):
    from dishcovery.services import activity
    rows = activity.passport(current_user(), a.limit)
    table("FR-21 food passport (%d visits)" % len(rows), ["date", "restaurant", "cuisine", "city"],
          [(r.visited_at, r.restaurant_name, r.cuisine, r.city) for r in rows])


def cmd_activity(a):
    from dishcovery.services import activity
    table("FR-22 recent activity", ["when", "event", "target", "details"],
          [(r.event_ts, r.event_type, "%s %s" % (r.target_type, r.target_id), dict(r.details or {}))
           for r in activity.recent_activity(current_user(), a.limit)])


def cmd_searches(a):
    from dishcovery.services import activity
    table("FR-23 search history", ["when", "query", "filters"],
          [(r.searched_at, r.query_text, dict(r.filters or {})) for r in activity.search_history(current_user(), a.limit)])


def cmd_trending(a):
    from dishcovery.services import activity
    ranking, per_day = activity.trending(a.city, a.days, a.top)
    table("FR-24 trending dishes in %s, last %d days" % (a.city, a.days), ["#", "dish", "name", "views"],
          [(i + 1, d, n, v) for i, (d, n, v) in enumerate(ranking)])
    console.print("  views per daily partition: " + ", ".join("%s=%d" % kv for kv in per_day.items()))


def cmd_stats(a):
    from dishcovery.services import activity
    s = activity.personal_stats(current_user(), a.months)
    table("FR-25 visits per month (Cassandra)", ["month", "visits"], list(s["visits_per_month"].items()))
    table("Most visited cuisines (Cassandra)", ["cuisine", "visits"], s["most_visited_cuisines"])
    table("Reviews by cuisine (MongoDB $lookup)", ["cuisine", "reviews", "avg rating"],
          [(r["_id"], r["reviews"], r["avg_rating"]) for r in s["reviews_by_cuisine"]])
    table("Cuisines reviewed (Dgraph count/val)", ["cuisine", "restaurants"],
          [(c["cuisine_name"], c["restaurants_reviewed"]) for c in s["graph_cuisines"]])
    table("Rating distribution (Dgraph @groupby)", ["rating", "reviews"],
          [(g["rating"], g["count"]) for g in s["rating_distribution"]])


# ------------------------------------------------------------------ social (FR-26..FR-31)
def cmd_follow(a):
    from dishcovery.services import social
    (social.unfollow if a.unfollow else social.follow)(current_user(), a.user)
    console.print("%s %s" % ("Unfollowed" if a.unfollow else "Now following", a.user))


def cmd_followers(a):
    from dishcovery.services import social
    f = social.followers(a.user or current_user()) or {}
    console.print("FR-27 %s: following %d, followers %d" % (f.get("name"), f.get("following_count", 0), f.get("followers_count", 0)))
    table("Following", ["id", "name"], [(x["user_id"], x["name"]) for x in f.get("following", [])])
    table("Followers (~follows)", ["id", "name"], [(x["user_id"], x["name"]) for x in f.get("followers", [])])


def cmd_feed(a):
    from dishcovery.services import social
    table("FR-28 feed: Dgraph ids -> MongoDB content", ["date", "user", "restaurant", "dish", "rating", "text"],
          [(r["created_at"], r["user"], r["restaurant"], r.get("dish"), stars(r["rating"]), r["text"][:60])
           for r in social.feed(current_user(), a.n)])


def cmd_recommend(a):
    from dishcovery.services import social
    table("FR-29 dishes liked by people with your taste (not tried yet)", ["dish", "name", "restaurant", "votes", "avg", "score"],
          [(r["dish_id"], r["name"], (r.get("served_at") or {}).get("name"), r.get("votes"),
            "%.2f" % r.get("avg_rating", 0), "%.1f" % r.get("score", 0)) for r in social.recommend(current_user(), a.n)])


def cmd_suggest(a):
    from dishcovery.services import social
    table("FR-30 people you may know (friends of friends)", ["id", "name", "city", "mutual"],
          [(r["user_id"], r["name"], r.get("city"), r["mutual_connections"]) for r in social.suggest_people(current_user(), a.n)])


def cmd_picks(a):
    from dishcovery.services import social
    table("FR-31 dishes at %s your network rated 4-5" % a.restaurant, ["dish", "name", "avg (math)", "reviews", "liked by"],
          [(p["dish_id"], p["name"], "%.2f" % p.get("avg_rating", 0), p.get("total_reviews"),
            ", ".join("%s (%d)" % (x["author"]["name"], x["rating"]) for x in p.get("liked_by", []) if x.get("author")))
           for p in social.network_picks(current_user(), a.restaurant)])


# ------------------------------------------------------------------ chatbot (FR-32..FR-35)
def cmd_ask(a):
    from dishcovery.services import chatbot
    try:
        uid = current_user()
    except DishcoveryError:
        uid = None
    res = chatbot.ask(a.question, uid, personalize=not a.no_personalize, near_me=a.near, use_llm=not a.no_llm)
    console.print("[dim]filters: %s | relevance threshold: cosine distance <= %.2f[/]" % (res["filters"], res["threshold"]))
    if a.show_prompt and res.get("prompt"):
        console.print(Panel(res["prompt"], title="Prompt sent to the LLM"))
    console.print(Panel(res["answer"], title="Dishcovery assistant" + (" (%s)" % res.get("model") if res.get("llm_used") else "")))
    if res["sources"]:
        table("Sources", ["tag", "collection", "id", "distance", "passage"],
              [("S%d" % (i + 1), s["collection"], s["id"], s["distance"], s["document"][:80]) for i, s in enumerate(res["sources"])])


def cmd_discover(a):
    from dishcovery.services import chatbot
    hits = chatbot.recommend_text(a.text, a.max_price, a.near, a.meters, a.vegetarian, a.n)
    table("FR-33 '%s'" % a.text, ["dish", "restaurant", "price", "veg", "distance", "text"],
          [(h["id"], h["metadata"]["restaurant_name"], "$" * h["metadata"]["price_level"], h["metadata"]["vegetarian"],
            h["distance"], h["document"][:60]) for h in hits])


def cmd_for_me(a):
    from dishcovery.services import chatbot
    hits, where = chatbot.personalized(current_user(), a.text, a.n)
    console.print("FR-35 preferences -> Chroma where = %s" % json.dumps(where))
    table("Suggestions", ["dish", "restaurant", "price", "veg", "distance"],
          [(h["id"], h["metadata"]["restaurant_name"], "$" * h["metadata"]["price_level"], h["metadata"]["vegetarian"], h["distance"]) for h in hits])


# ------------------------------------------------------------------ admin
def cmd_status(a):
    from dishcovery.connection import cassandra, chroma, dgraph, mongo
    for name, mod in (("MongoDB", mongo), ("Cassandra", cassandra), ("Dgraph", dgraph), ("ChromaDB", chroma)):
        try:
            mod.ping()
            console.print("  [green]OK[/]   %s" % name)
        except Exception as exc:  # noqa: BLE001
            console.print("  [red]FAIL[/] %s: %s" % (name, exc))


def cmd_explain(a):
    from dishcovery.queries import cassandra_queries as cq
    from dishcovery.queries import dgraph_queries as dq
    from dishcovery.queries import mongo_queries as mq
    table("MongoDB explain(): winning plans", ["query", "plan stages", "keys examined", "docs examined", "returned"],
          [(k, " <- ".join(v["stages"]), v.get("keysExamined"), v.get("docsExamined"), v.get("nReturned"))
           for k, v in mq.explain_main_queries().items()])
    rows = []
    for name, key, params in [("Q1 activity_by_user", "q1_activity", ("user_0001", cq.ym(datetime.now()), 20)),
                              ("Q3 reviews_by_restaurant", "q3_reviews", ("rest_0001", "2026-10", 10)),
                              ("Q4 searches_by_user", "q4_searches", ("user_0001", 10))]:
        rs = cq.execute(key, params, trace=True)
        trace = rs.get_query_trace(max_wait_sec=5)
        events = [e.description for e in trace.events]
        single = any("single-partition" in e.lower() or "partition" in e.lower() for e in events)
        rows.append((name, "%d us" % int(trace.duration.total_seconds() * 1e6) if trace.duration else "?", len(events),
                     "yes" if single else "?", next((e for e in events if "partition" in e.lower()), "")[:60]))
    table("Cassandra TRACING (one partition per query)", ["query", "duration", "trace events", "single partition", "evidence"], rows)
    table("Dgraph server latency", ["query", "ms"], [(k, "%.2f" % v) for k, v in dq.latency_report().items()])


def cmd_sync(a):
    from dishcovery.services import sync
    if a.action == "retry":
        done, failed = sync.retry_pending()
        console.print("Replayed %d queued writes, %d still failing." % (done, failed))
    else:
        table("Queued derived writes", ["op", "attempts", "error", "created"],
              [(j["op"], j["attempts"], j.get("error", "")[:60], j["created_at"]) for j in sync.pending()])


# ------------------------------------------------------------------ parser
def build_parser():
    p = argparse.ArgumentParser(prog="dishcovery", description="Dishcovery client (MongoDB + Cassandra + Dgraph + ChromaDB)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def cmd(name, fn, help_text):
        sp = sub.add_parser(name, help=help_text)
        sp.set_defaults(func=fn)
        return sp

    s = cmd("register", cmd_register, "FR-01 create an account")
    s.add_argument("--email", required=True); s.add_argument("--name", required=True)
    s.add_argument("--city", default="Guadalajara"); s.add_argument("--password")
    s = cmd("login", cmd_login, "FR-02 log in"); s.add_argument("--email", required=True); s.add_argument("--password")
    cmd("logout", cmd_logout, "FR-02 log out")
    cmd("whoami", cmd_whoami, "show my profile")
    s = cmd("profile", cmd_profile, "FR-03 edit profile")
    for f in ("name", "city", "bio", "photo"):
        s.add_argument("--" + f)
    s = cmd("prefs", cmd_prefs, "FR-04 set preferences")
    s.add_argument("--cuisines", help="comma separated"); s.add_argument("--dietary", help="vegetarian,vegan,...")
    s.add_argument("--price", help="range, e.g. 1-2")
    s = cmd("delete-account", cmd_delete_account, "FR-05 delete my account"); s.add_argument("--yes", action="store_true")
    s = cmd("fav", cmd_fav, "FR-12/13 favorites")
    s.add_argument("action", choices=["add", "remove", "list"]); s.add_argument("kind", nargs="?", choices=["restaurant", "dish"])
    s.add_argument("ref_id", nargs="?")
    s = cmd("list", cmd_list, "FR-14 custom lists: create NAME | add LIST TYPE ID | remove LIST ID | delete LIST | show")
    s.add_argument("action", choices=["create", "add", "remove", "delete", "show"]); s.add_argument("args", nargs="*")

    s = cmd("restaurant", cmd_restaurant, "FR-06/08 create or show a restaurant")
    s.add_argument("action", choices=["show", "create"]); s.add_argument("id", nargs="?")
    for f in ("name", "cuisine", "city", "street", "neighborhood", "description", "attributes"):
        s.add_argument("--" + f)
    s.add_argument("--price", type=int, default=2); s.add_argument("--lon", type=float); s.add_argument("--lat", type=float)
    s = cmd("search", cmd_search, "FR-09 search by text, cuisine or price")
    s.add_argument("text", nargs="?"); s.add_argument("--cuisine"); s.add_argument("--max-price", type=int)
    s.add_argument("--limit", type=int, default=10)
    s = cmd("near", cmd_near, "FR-10 restaurants near a point (default: ITESO)")
    s.add_argument("--lon", type=float); s.add_argument("--lat", type=float)
    s.add_argument("--meters", type=int, default=2000); s.add_argument("--max-price", type=int)
    s = cmd("filter", cmd_filter, "FR-11 filter by attributes")
    for f in ("terrace", "vegetarian_options", "pet_friendly", "delivery", "wifi"):
        s.add_argument("--" + f.replace("_", "-"), dest=f, action="store_true")
    s = cmd("dish", cmd_dish, "FR-07 add, show (FR-24 view) or find similar (FR-34)")
    s.add_argument("action", choices=["show", "add", "similar"]); s.add_argument("id", nargs="?")
    s.add_argument("--restaurant"); s.add_argument("--name"); s.add_argument("--price", type=float)
    s.add_argument("--description"); s.add_argument("--tags"); s.add_argument("--vegetarian", action="store_true")
    s.add_argument("-n", type=int, default=5)

    s = cmd("review", cmd_review, "FR-15/16/17 write, edit, delete, list, mine")
    s.add_argument("action", choices=["write", "edit", "delete", "list", "mine"]); s.add_argument("id", nargs="?")
    s.add_argument("--restaurant"); s.add_argument("--dish"); s.add_argument("--rating", type=int)
    s.add_argument("--text"); s.add_argument("--limit", type=int, default=10)
    s = cmd("ratings", cmd_ratings, "FR-18 average rating"); s.add_argument("--restaurant"); s.add_argument("--dish")
    s = cmd("top-dishes", cmd_top_dishes, "FR-19 best dishes by cuisine")
    s.add_argument("--cuisine"); s.add_argument("--min-votes", type=int, default=3); s.add_argument("--top", type=int, default=5)

    s = cmd("checkin", cmd_checkin, "FR-20 check in at a restaurant"); s.add_argument("restaurant")
    s = cmd("passport", cmd_passport, "FR-21 my food passport"); s.add_argument("--limit", type=int, default=30)
    s = cmd("activity", cmd_activity, "FR-22 my recent activity"); s.add_argument("--limit", type=int, default=20)
    s = cmd("searches", cmd_searches, "FR-23 my search history"); s.add_argument("--limit", type=int, default=10)
    s = cmd("trending", cmd_trending, "FR-24 trending dishes by city")
    s.add_argument("--city", default="Guadalajara"); s.add_argument("--days", type=int, default=7); s.add_argument("--top", type=int, default=10)
    s = cmd("stats", cmd_stats, "FR-25 my personal stats"); s.add_argument("--months", type=int, default=6)

    s = cmd("follow", cmd_follow, "FR-26 follow (or --unfollow) a user")
    s.add_argument("user"); s.add_argument("--unfollow", action="store_true")
    s = cmd("followers", cmd_followers, "FR-27 followers / following"); s.add_argument("user", nargs="?")
    s = cmd("feed", cmd_feed, "FR-28 reviews from people I follow"); s.add_argument("-n", type=int, default=15)
    s = cmd("recommend", cmd_recommend, "FR-29 dish recommendations"); s.add_argument("-n", type=int, default=10)
    s = cmd("suggest", cmd_suggest, "FR-30 people to follow"); s.add_argument("-n", type=int, default=10)
    s = cmd("picks", cmd_picks, "FR-31 dishes my network liked at a restaurant"); s.add_argument("restaurant")

    s = cmd("ask", cmd_ask, "FR-32/35 chatbot (RAG)")
    s.add_argument("question"); s.add_argument("--near", action="store_true", help="only restaurants within 3 km of ITESO")
    s.add_argument("--no-personalize", action="store_true"); s.add_argument("--no-llm", action="store_true")
    s.add_argument("--show-prompt", action="store_true")
    s = cmd("discover", cmd_discover, "FR-33 natural language dish search")
    s.add_argument("text"); s.add_argument("--max-price", type=int); s.add_argument("--near", action="store_true")
    s.add_argument("--meters", type=int, default=2000); s.add_argument("--vegetarian", action="store_true")
    s.add_argument("-n", type=int, default=5)
    s = cmd("for-me", cmd_for_me, "FR-35 suggestions filtered by my preferences")
    s.add_argument("text", nargs="?", default="something good for lunch"); s.add_argument("-n", type=int, default=5)

    cmd("status", cmd_status, "check the connection to the 4 databases")
    cmd("explain", cmd_explain, "optimization evidence: Mongo explain, Cassandra tracing, Dgraph latency")
    s = cmd("sync", cmd_sync, "derived writes queued after a failure"); s.add_argument("action", choices=["status", "retry"])
    cmd("shell", cmd_shell, "interactive mode")
    return p


def run(argv):
    import dishcovery.services  # noqa: F401  (registers sync handlers)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    try:
        args.func(args)
        return 0
    except DishcoveryError as exc:
        console.print("[red]Error:[/] %s" % exc)
        return 1


def cmd_shell(_):
    console.print("[bold]Dishcovery shell[/] - type a command (e.g. `near`, `ask \"spicy tacos\"`), `cls`, `help` or `exit`.")
    parser = build_parser()
    while True:
        try:
            line = input("dishcovery> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("exit", "quit"):
            break
        if line in ("help", "?"):
            parser.print_help()
            continue
        if line in ("cls", "clear"):
            console.clear()
            continue
        if line:
            try:
                run(shlex.split(line))
            except Exception as exc:  # noqa: BLE001 - keep the shell alive during a demo
                console.print("[red]%s: %s[/]" % (type(exc).__name__, exc))


def main():
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
