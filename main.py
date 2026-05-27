import os
import re
import time
import requests

from thefuzz import fuzz, process

# =========================================================
# CONFIG
# =========================================================

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
MAIN_DB_ID = os.environ.get("NOTION_DATABASE_ID")

ARTIST_DB_ID = "21e451056c5e814d9c19d39545e1ce9c"
GENRE_DB_ID = "222451056c5e81239bc7e95a553cef45"
FORMAT_DB_ID = "36d451056c5e8018bddfc238554cde03"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

FUZZY_THRESHOLD = 92

# =========================================================
# HELPERS
# =========================================================

def safe_json(response):

    try:
        return response.json()
    except:
        return {}

# =========================================================
# FETCH ALL PAGES
# =========================================================

def fetch_all_pages(database_id):

    pages = []

    has_more = True
    next_cursor = None

    while has_more:

        payload = {}

        if next_cursor:
            payload["start_cursor"] = next_cursor

        response = requests.post(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers=HEADERS,
            json=payload
        )

        data = safe_json(response)

        pages.extend(data.get("results", []))

        print(f"Fetched {len(pages)} pages so far...")

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    return pages

# =========================================================
# CACHE
# =========================================================

def build_cache(database_id):

    pages = fetch_all_pages(database_id)

    cache = {}

    for page in pages:

        props = page.get("properties", {})

        title = props.get("Name", {}).get("title", [])

        if not title:
            continue

        name = title[0]["plain_text"].strip()

        cache[name.lower()] = {
            "id": page["id"],
            "name": name
        }

    return cache

# =========================================================
# LOAD CACHES
# =========================================================

print("Loading caches...")

artist_cache = build_cache(ARTIST_DB_ID)
genre_cache = build_cache(GENRE_DB_ID)
format_cache = build_cache(FORMAT_DB_ID)

print("Caches loaded.")

# =========================================================
# FUZZY FIND
# =========================================================

def fuzzy_find(name, cache, threshold=FUZZY_THRESHOLD):

    if not name:
        return None

    cleaned = name.strip().lower()

    if cleaned in cache:
        return cache[cleaned]["id"]

    keys = list(cache.keys())

    result = process.extractOne(
        cleaned,
        keys,
        scorer=fuzz.token_sort_ratio
    )

    if not result:
        return None

    match, score = result

    print(f"Fuzzy Match: {name} -> {match} ({score})")

    if score >= threshold:
        return cache[match]["id"]

    return None

# =========================================================
# EXISTING RELATIONS ONLY
# =========================================================

def build_existing_relations(
    values,
    cache,
    threshold
):

    relation = []

    keys = list(cache.keys())

    for val in values:

        val = val.strip()

        if not val:
            continue

        cleaned = val.lower()

        # EXACT MATCH
        if cleaned in cache:

            relation.append({
                "id": cache[cleaned]["id"]
            })

            continue

        # FUZZY MATCH
        result = process.extractOne(
            cleaned,
            keys,
            scorer=fuzz.token_sort_ratio
        )

        if not result:
            continue

        match, score = result

        print(f"{val} -> {match} ({score})")

        if score >= threshold:

            relation.append({
                "id": cache[match]["id"]
            })

    return relation

# =========================================================
# CREATE PAGE
# =========================================================

def create_page(database_id, name):

    payload = {
        "parent": {
            "database_id": database_id
        },
        "properties": {
            "Name": {
                "title": [
                    {
                        "text": {
                            "content": name
                        }
                    }
                ]
            }
        }
    }

    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS,
        json=payload
    )

    data = safe_json(response)

    return data.get("id")

# =========================================================
# GET OR CREATE
# =========================================================

def get_or_create(name, cache, db_id):

    existing = fuzzy_find(
        name,
        cache
    )

    if existing:
        return existing

    print(f"Creating: {name}")

    pid = create_page(
        db_id,
        name
    )

    if pid:

        cache[name.lower()] = {
            "id": pid,
            "name": name
        }

    return pid

# =========================================================
# FETCH YOUTUBE METADATA
# =========================================================

def fetch_youtube_metadata(url):

    try:

        video_id = None

        # ============================================
        # EXTRACT VIDEO ID
        # ============================================

        patterns = [
            r"v=([a-zA-Z0-9_-]+)",
            r"youtu\.be/([a-zA-Z0-9_-]+)"
        ]

        for pattern in patterns:

            match = re.search(pattern, url)

            if match:
                video_id = match.group(1)
                break

        if not video_id:

            print("Invalid YouTube URL")

            return None

        # ============================================
        # OEMBED API
        # ============================================

        oembed = requests.get(
            "https://www.youtube.com/oembed",
            params={
                "url": url,
                "format": "json"
            },
            timeout=20
        )

        if oembed.status_code != 200:

            print("oEmbed fetch failed")

            return None

        data = oembed.json()

        title = data.get("title", "")
        author = data.get("author_name", "")
        thumbnail = data.get("thumbnail_url", "")

        # ============================================
        # CLEAN TITLE
        # ============================================

        track = title
        artist = author

        separators = [
            " - ",
            " | ",
            " — "
        ]

        for sep in separators:

            if sep in title:

                left, right = title.split(sep, 1)

                if len(left) < 40:

                    artist = left.strip()
                    track = right.strip()

                    break

        return {
            "title": track,
            "track": track,
            "artist": artist,
            "thumbnail": thumbnail,
            "id": video_id
        }

    except Exception as e:

        print(f"YT ERROR: {e}")

        return None

# =========================================================
# GENRE CLEANER
# =========================================================

def clean_genres(info):

    genres = []

    title = (
        info.get("track")
        or info.get("title", "")
    ).lower()

    mappings = {
        "hip hop": "Hip Hop",
        "rap": "Hip Hop",
        "rock": "Rock",
        "metal": "Metal",
        "pop": "Pop",
        "jazz": "Jazz",
        "classical": "Classical",
        "lofi": "Lo-Fi",
        "electronic": "Electronic",
        "edm": "Electronic",
        "indie": "Indie",
        "folk": "Folk",
        "r&b": "R&B",
        "romantic": "Romance",
        "love": "Romance"
    }

    for key, val in mappings.items():

        if key in title:
            genres.append(val)

    return list(set(genres))

# =========================================================
# SHOULD UPDATE
# =========================================================

def should_update(page):

    props = page.get("properties", {})

    checks = [

        props.get("Artist", {}).get("relation", []),
        props.get("Cover", {}).get("files", []),
        props.get("Genre", {}).get("relation", []),
        props.get("Format", {}).get("relation", [])
    ]

    if all(checks):
        return False

    return True

# =========================================================
# UPDATE PAGE
# =========================================================

def update_music_page(page, info):

    props = {}

    notion_props = page.get("properties", {})

    title = info.get("track") or info.get("title")

    artist = (
        info.get("artist")
        or "Unknown Artist"
    )

    thumbnail = info.get("thumbnail")

    print(f"Updating: {title}")

    # =====================================================
    # COVER
    # =====================================================

    existing_cover = notion_props.get(
        "Cover",
        {}
    ).get("files", [])

    if not existing_cover and thumbnail:

        props["Cover"] = {
            "files": [
                {
                    "name": "Cover",
                    "external": {
                        "url": thumbnail
                    }
                }
            ]
        }

    # =====================================================
    # ARTIST
    # =====================================================

    existing_artist = notion_props.get(
        "Artist",
        {}
    ).get("relation", [])

    if not existing_artist and artist:

        aid = get_or_create(
            artist,
            artist_cache,
            ARTIST_DB_ID
        )

        if aid:

            props["Artist"] = {
                "relation": [
                    {
                        "id": aid
                    }
                ]
            }

    # =====================================================
    # GENRE
    # =====================================================

    existing_genre = notion_props.get(
        "Genre",
        {}
    ).get("relation", [])

    if not existing_genre:

        genres = clean_genres(info)

        props["Genre"] = {
            "relation": build_existing_relations(
                genres,
                genre_cache,
                threshold=80
            )
        }

    # =====================================================
    # FORMAT
    # =====================================================

    existing_format = notion_props.get(
        "Format",
        {}
    ).get("relation", [])

    if not existing_format:

        format_id = fuzzy_find(
            "Song",
            format_cache,
            threshold=90
        )

        if format_id:

            props["Format"] = {
                "relation": [
                    {
                        "id": format_id
                    }
                ]
            }

    # =====================================================
    # NOTHING TO UPDATE
    # =====================================================

    if not props:

        print("Nothing to update")

        return False

    # =====================================================
    # PATCH
    # =====================================================

    response = requests.patch(
        f"https://api.notion.com/v1/pages/{page['id']}",
        headers=HEADERS,
        json={
            "properties": props
        }
    )

    if response.status_code == 200:

        print(f"Updated: {title}")

        return True

    else:

        print(response.text)

        return False

# =========================================================
# MAIN
# =========================================================

def main():

    print("Fetching songs...")

    pages = fetch_all_pages(MAIN_DB_ID)

    print(f"Found {len(pages)} songs")

    updated = 0
    skipped = 0

    for index, page in enumerate(pages):

        try:

            print("--------------------------------")
            print(f"Processing {index + 1}")

            props = page.get("properties", {})

            yt_link = props.get(
                "Url",
                {}
            ).get("url")

            # =================================================
            # ONLY YOUTUBE URLS
            # =================================================

            if not yt_link:

                print("Missing URL")

                skipped += 1
                continue

            if "youtube" not in yt_link.lower():

                print("Skipping non-youtube URL")

                skipped += 1
                continue

            # =================================================
            # SKIP FILLED
            # =================================================

            if not should_update(page):

                print("Skipping fully populated")

                skipped += 1
                continue

            # =================================================
            # FETCH METADATA
            # =================================================

            metadata = fetch_youtube_metadata(
                yt_link
            )

            if not metadata:

                skipped += 1
                continue

            success = update_music_page(
                page,
                metadata
            )

            if success:
                updated += 1
            else:
                skipped += 1

            time.sleep(1)

        except Exception as e:

            print(f"ERROR: {e}")

    print("================================")
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print("Done.")

# =========================================================

if __name__ == "__main__":
    main()
