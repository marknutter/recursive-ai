"""Ingest Foobat + Oqodo chat data into RLM persistent memory.

Parses both data sources, formats conversations as readable threads
with user attribution, and batch-ingests into ~/.rlm/memory/.

Usage:
    uv run python scripts/ingest_chat_data.py [--foobat] [--oqodo] [--all] [--dry-run]
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Add project root to path so we can import rlm
sys.path.insert(0, str(Path(__file__).parent.parent))
from rlm import memory
from rlm import db

DATA_DIR = Path(__file__).parent.parent / "data"
FOOBAT_POSTS = DATA_DIR / "FOOBAT POSTS.csv"
FOOBAT_USERS = DATA_DIR / "FOOBAT USERS.csv"
OQODO_JSON = DATA_DIR / "oqodo-export copy.json"


# --- HTML cleanup ---

def strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<a[^>]*href=[\"']([^\"']*)[\"'][^>]*>([^<]*)</a>",
                  r"\2 (\1)", text, flags=re.IGNORECASE)
    text = re.sub(r"<img[^>]*src=[\"']([^\"']*)[\"'][^>]*>",
                  r"[image: \1]", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --- Foobat parsing ---

def parse_foobat_users() -> dict[str, dict]:
    """Parse FOOBAT USERS.csv into {id: {first, last, nickname, username}}."""
    users = {}
    with open(FOOBAT_USERS, "r", errors="replace") as f:
        reader = csv.reader(f, delimiter=";")
        for row in reader:
            if len(row) < 5:
                continue
            uid = row[0].strip().strip('"')
            first = row[1].strip().strip('"') if row[1] else ""
            last = row[2].strip().strip('"') if row[2] else ""
            nickname = row[3].strip().strip('"') if row[3] else ""
            username = row[5].strip().strip('"') if len(row) > 5 and row[5] else ""
            users[uid] = {
                "first": first,
                "last": last,
                "nickname": nickname,
                "username": username,
                "display": nickname if nickname else f"{first} {last}".strip(),
            }
    return users


def parse_foobat_posts(users: dict) -> list[dict]:
    """Parse FOOBAT POSTS.csv into list of post dicts."""
    posts = []
    with open(FOOBAT_POSTS, "r", errors="replace") as f:
        reader = csv.reader(f, delimiter=";")
        for row in reader:
            if len(row) < 6:
                continue
            try:
                post_id = row[0].strip()
                title = row[1].strip()
                content = strip_html(row[2].strip())
                date_str = row[3].strip()
                user_id = row[5].strip()

                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                user = users.get(user_id, {})
                display_name = user.get("display", f"user_{user_id}")

                if not content or content.lower() in ("test", "null"):
                    continue

                posts.append({
                    "id": post_id,
                    "title": title,
                    "content": content,
                    "datetime": dt,
                    "user_id": user_id,
                    "user_name": display_name,
                })
            except (ValueError, IndexError):
                continue

    posts.sort(key=lambda p: p["datetime"])
    return posts


def group_foobat_by_week(posts: list[dict]) -> list[dict]:
    """Group Foobat posts into weekly conversation batches."""
    weeks = defaultdict(list)
    for post in posts:
        # ISO week key: "2003-W28"
        week_key = post["datetime"].strftime("%Y-W%W")
        weeks[week_key] = weeks.get(week_key, [])
        weeks[week_key].append(post)

    groups = []
    for week_key in sorted(weeks):
        week_posts = weeks[week_key]
        if not week_posts:
            continue

        participants = sorted(set(p["user_name"] for p in week_posts))
        start_date = week_posts[0]["datetime"]
        end_date = week_posts[-1]["datetime"]

        # Format as conversation
        lines = []
        for p in week_posts:
            ts = p["datetime"].strftime("%Y-%m-%d %H:%M")
            title_part = f" [{p['title']}]" if p["title"] else ""
            lines.append(f"[{ts}] {p['user_name']}{title_part}: {p['content']}")

        content = "\n".join(lines)
        date_range = start_date.strftime("%b %d") + " - " + end_date.strftime("%b %d, %Y")

        groups.append({
            "content": content,
            "participants": participants,
            "start_date": start_date,
            "end_date": end_date,
            "date_range": date_range,
            "post_count": len(week_posts),
            "week_key": week_key,
        })

    return groups


# --- Oqodo parsing ---

def parse_oqodo() -> tuple[dict, dict, dict, dict]:
    """Parse oqodo-export.json into users, threads, posts, cliqs."""
    with open(OQODO_JSON, "r") as f:
        data = json.load(f)

    users = {}
    for uid, u in data.get("users", {}).items():
        email = u.get("email", "")
        # Extract name from email prefix as fallback
        name = email.split("@")[0] if email else f"user_{uid}"
        users[uid] = {
            "email": email,
            "display": name,
        }

    threads = data.get("threads", {})
    posts = data.get("posts", {})
    cliqs = data.get("cliqs", {})

    return users, threads, posts, cliqs


def build_oqodo_conversations(
    users: dict, threads: dict, posts: dict, cliqs: dict
) -> list[dict]:
    """Build conversation groups from Oqodo threads."""
    # Build thread_id -> post_id mapping from threads.rels.posts
    # (Most posts lack threads_parent_id; the thread->post refs are authoritative)
    thread_post_ids = defaultdict(set)
    for tid, tdata in threads.items():
        refs = tdata.get("rels", {}).get("posts", {})
        for pid in refs:
            thread_post_ids[tid].add(pid)

    # Also pick up posts that have threads_parent_id (early data has this)
    for pid, post in posts.items():
        tid = post.get("threads_parent_id", "")
        if tid and tid in threads:
            thread_post_ids[tid].add(pid)

    # Resolve post refs into actual post data
    thread_posts = defaultdict(list)
    for tid, pids in thread_post_ids.items():
        for pid in pids:
            post = posts.get(pid)
            if not post:
                continue

            content = strip_html(post.get("content", ""))
            if not content:
                continue

            updated_at = post.get("updated_at", 0)
            # Firebase timestamps in milliseconds
            if isinstance(updated_at, (int, float)) and updated_at > 1e12:
                updated_at = updated_at / 1000
            try:
                dt = datetime.fromtimestamp(updated_at) if updated_at > 0 else None
            except (OSError, ValueError):
                dt = None

            user_id = str(post.get("user_id", ""))
            user = users.get(user_id, {})
            display_name = user.get("display", f"user_{user_id}")

            thread_posts[tid].append({
                "content": content,
                "datetime": dt,
                "user_name": display_name,
            })

    # Build conversation entries
    conversations = []
    for tid, tdata in threads.items():
        tposts = thread_posts.get(tid, [])
        if not tposts:
            continue

        # Sort by datetime
        tposts.sort(key=lambda p: p["datetime"] or datetime.min)

        title = tdata.get("title", "Untitled")
        participants = sorted(set(p["user_name"] for p in tposts))
        dates = [p["datetime"] for p in tposts if p["datetime"]]
        start_date = min(dates) if dates else None
        end_date = max(dates) if dates else None

        # Find which cliq this thread belongs to
        cliq_name = ""
        cliq_parent = tdata.get("cliqs_parent_id", "")
        if cliq_parent and cliq_parent in cliqs:
            cliq_name = cliqs[cliq_parent].get("name", "")

        # Format as conversation
        lines = []
        for p in tposts:
            ts = p["datetime"].strftime("%Y-%m-%d %H:%M") if p["datetime"] else "unknown"
            lines.append(f"[{ts}] {p['user_name']}: {p['content']}")

        content = f"Thread: {title}\n"
        if cliq_name:
            content += f"Group: {cliq_name}\n"
        content += "\n" + "\n".join(lines)

        date_range = ""
        if start_date and end_date:
            date_range = start_date.strftime("%b %d, %Y") + " - " + end_date.strftime("%b %d, %Y")

        conversations.append({
            "content": content,
            "title": title,
            "participants": participants,
            "start_date": start_date,
            "end_date": end_date,
            "date_range": date_range,
            "post_count": len(tposts),
            "cliq_name": cliq_name,
            "thread_id": tid,
        })

    conversations.sort(key=lambda c: c["start_date"] or datetime.min)
    return conversations


# --- Ingestion ---

def ingest_foobat(dry_run: bool = False):
    """Parse and ingest Foobat data."""
    print("Parsing Foobat users...")
    users = parse_foobat_users()
    print(f"  {len(users)} users loaded")

    print("Parsing Foobat posts...")
    posts = parse_foobat_posts(users)
    print(f"  {len(posts)} posts parsed")

    print("Grouping by week...")
    groups = group_foobat_by_week(posts)
    print(f"  {len(groups)} weekly groups")

    # Filter out tiny groups (< 3 posts)
    groups = [g for g in groups if g["post_count"] >= 3]
    print(f"  {len(groups)} groups after filtering (>= 3 posts)")

    if dry_run:
        print("\n[DRY RUN] Would ingest:")
        for g in groups[:5]:
            print(f"  {g['week_key']}: {g['post_count']} posts, "
                  f"{len(g['participants'])} participants, "
                  f"{len(g['content']):,} chars")
        if len(groups) > 5:
            print(f"  ... and {len(groups) - 5} more")
        return

    print("\nIngesting into memory...")
    memory.init_memory_store()
    ingested = 0
    for g in groups:
        year = g["start_date"].strftime("%Y")
        participant_names = ", ".join(g["participants"][:5])
        if len(g["participants"]) > 5:
            participant_names += f" +{len(g['participants']) - 5} more"

        summary = f"Foobat {g['date_range']}: {g['post_count']} posts by {participant_names}"
        if len(summary) > 80:
            summary = summary[:77] + "..."

        tags = [
            "foobat", "chat", "forum",
            g["start_date"].strftime("%Y"),
        ]
        # Add participant names as tags (first names only, lowercase)
        for name in g["participants"][:6]:
            tag = name.lower().split()[0] if " " in name else name.lower()
            if len(tag) > 2 and tag not in tags:
                tags.append(tag)

        result = memory.add_memory(
            content=g["content"],
            tags=tags,
            source="foobat-csv",
            source_name=f"foobat-{g['week_key']}",
            summary=summary,
        )
        ingested += 1
        if ingested % 25 == 0:
            print(f"  {ingested}/{len(groups)} ingested...")

    print(f"  Done: {ingested} Foobat entries ingested")


def ingest_oqodo(dry_run: bool = False):
    """Parse and ingest Oqodo data."""
    print("Parsing Oqodo export...")
    users, threads, posts, cliqs = parse_oqodo()
    users = enrich_oqodo_users(users)
    print(f"  {len(users)} users, {len(threads)} threads, {len(posts)} posts")

    print("Building conversations...")
    conversations = build_oqodo_conversations(users, threads, posts, cliqs)
    print(f"  {len(conversations)} conversations built")

    # Filter out tiny threads (< 2 posts)
    conversations = [c for c in conversations if c["post_count"] >= 2]
    print(f"  {len(conversations)} after filtering (>= 2 posts)")

    if dry_run:
        from collections import Counter
        year_dist = Counter()
        for c in conversations:
            y = c["start_date"].strftime("%Y") if c["start_date"] else "unknown"
            year_dist[y] += 1
        print(f"\n[DRY RUN] Conversations by year:")
        for y in sorted(year_dist):
            print(f"  {y}: {year_dist[y]}")
        print(f"\nSample entries:")
        for c in conversations[:5]:
            print(f"  \"{c['title']}\": {c['post_count']} posts, "
                  f"{len(c['participants'])} participants, "
                  f"{len(c['content']):,} chars")
        if len(conversations) > 5:
            print(f"  ... and {len(conversations) - 5} more")
        return

    print("\nIngesting into memory...")
    memory.init_memory_store()
    ingested = 0
    skipped = 0
    for c in conversations:
        source_name = f"oqodo-thread-{c['thread_id'][:12]}"

        # Skip if already ingested (incremental)
        if db.source_name_exists(source_name):
            skipped += 1
            continue

        participant_names = ", ".join(c["participants"][:5])
        if len(c["participants"]) > 5:
            participant_names += f" +{len(c['participants']) - 5} more"

        title_short = c["title"][:30] if len(c["title"]) > 30 else c["title"]
        summary = f"Oqodo \"{title_short}\": {c['post_count']} posts by {participant_names}"
        if len(summary) > 80:
            summary = summary[:77] + "..."

        tags = ["oqodo", "chat"]
        if c["cliq_name"]:
            tags.append(c["cliq_name"].lower().replace(" ", "-"))
        if c["start_date"]:
            tags.append(c["start_date"].strftime("%Y"))
        # Add participant names as tags
        for name in c["participants"][:6]:
            tag = name.lower()
            if len(tag) > 2 and tag not in tags:
                tags.append(tag)

        result = memory.add_memory(
            content=c["content"],
            tags=tags,
            source="oqodo-firebase",
            source_name=source_name,
            summary=summary,
        )
        ingested += 1
        if ingested % 50 == 0:
            print(f"  {ingested}/{len(conversations)} ingested...")

    print(f"  Done: {ingested} new entries ingested, {skipped} skipped (already exist)")


# --- Map Oqodo emails to Foobat names ---

# Known email -> Foobat identity mappings (from comparing both user lists)
OQODO_EMAIL_TO_NAME = {
    "marknutter@gmail.com": "Stegg",
    "spewcus@gmail.com": "Greg-a-Byte",
    "mike@neuegrafik.net": "NeueGrafik",
    "kangas_bass@hotmail.com": "captain butter",
    "craigbergeron@gmail.com": "Craigers",
    "kobenews@cox.net": "Chief Genius Officer",
    "frjmeyer@gmail.com": "Deacon",
    "brian.ratnayake@gmail.com": "B-Rat",
    "java81@gmail.com": "Goober",
    "goober8008@gmail.com": "Goober",
}


def enrich_oqodo_users(users: dict) -> dict:
    """Add Foobat nicknames to Oqodo users where possible."""
    for uid, u in users.items():
        email = u.get("email", "")
        if email in OQODO_EMAIL_TO_NAME:
            u["display"] = OQODO_EMAIL_TO_NAME[email]
    return users


def main():
    parser = argparse.ArgumentParser(
        description="Ingest chat data into RLM persistent memory"
    )
    parser.add_argument("--foobat", action="store_true", help="Ingest Foobat data")
    parser.add_argument("--oqodo", action="store_true", help="Ingest Oqodo data")
    parser.add_argument("--all", action="store_true", help="Ingest all sources")
    parser.add_argument("--dry-run", action="store_true", help="Parse but don't store")
    args = parser.parse_args()

    if not (args.foobat or args.oqodo or args.all):
        parser.print_help()
        print("\nSpecify --foobat, --oqodo, or --all")
        sys.exit(1)

    if args.foobat or args.all:
        print("=" * 50)
        print("FOOBAT INGESTION")
        print("=" * 50)
        ingest_foobat(dry_run=args.dry_run)
        print()

    if args.oqodo or args.all:
        print("=" * 50)
        print("OQODO INGESTION")
        print("=" * 50)
        ingest_oqodo(dry_run=args.dry_run)
        print()

    if not args.dry_run:
        index = memory.load_index()
        print(f"Total memories in store: {len(index)}")


if __name__ == "__main__":
    main()
