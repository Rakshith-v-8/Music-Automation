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
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")

ARTIST_DB_ID = "36d451056c5e8045b879fb6a30b0b7e1"
GENRE_DB_ID = "222451056c5e81239bc7e95a553cef45"
FORMAT_DB_ID = "36d451056c5e8018bddfc238554cde03"
LANGUAGE_DB_ID = "YOUR_LANGUAGE_DB_ID"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

FUZZY_THRESHOLD = 96

# =========================================================
# LANGUAGE MAP
# =========================================================

LANGUAGE_MAP = {
    "en": "English",
    "hi": "Hindi",
    "te": "Telugu",
    "ta": "Tamil",
    "ml": "Malayalam",
    "kn": "Kannada",
    "mr": "Marathi",
    "bn": "Bengali",
    "gu": "Gujarati",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese"
}

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
# BUILD CACHE
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
language_cache = build_cache(LANGUAGE_DB_ID)

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

    if not keys:
        return None

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

    existing = fuzzy_find(name, cache)

    if existing:
        return existing

    print(f"Creating: {name}")

    pid = create_page(db_id, name)

    if pid:

        cache[name.lower()] = {
            "id": pid,
            "name": name
        }

    return pid

# =========================================================
# PARSE DURATION
# =========================================================

def parse_duration(duration):

    if not duration:
        return None

    match = re.match(
        r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?',
        duration
    )

    if not match:
        return None

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds

# =========================================================
# FETCH YOUTUBE METADATA
# =========================================================

def fetch_youtube_metadata(url):

    try:

        video_id = None

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
            print("Invalid video id")
            return None

        response = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet,contentDetails",
                "id": video_id,
                "key": YOUTUBE_API_KEY
            },
            timeout=20
        )

        data = safe_json(response)

        # DEBUG
        print("YOUTUBE STATUS:", response.status_code)
        print(data)

        items = data.get("items", [])

        if not items:
            return None

        item = items[0]

        snippet = item.get("snippet", {})
        details = item.get("contentDetails", {})

        title = snippet.get("title", "")
        channel = snippet.get("channelTitle", "")
        published = snippet.get("publishedAt", "")
        language = (
            snippet.get("defaultAudioLanguage")
            or snippet.get("defaultLanguage")
        )

        thumbnails = snippet.get("thumbnails", {})

        thumbnail = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
        )

        # =============================================
        # TITLE SPLIT
        # =============================================

        track = title
        artist = channel

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

        artist = artist.replace(" - Topic", "").strip()

        return {
            "track": track,
            "artist": artist,
            "thumbnail": thumbnail,
            "published": published,
            "language": language,
            "duration": details.get("duration")
        }

    except Exception as e:

        print("YT ERROR:", e)
        return None

# =========================================================
# GENRES
# =========================================================

def clean_genres(info):

    genres = []

    title = info.get("track", "").lower()

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
        props.get("Format", {}).get("relation", []),
        props.get("Language", {}).get("relation", []),
        props.get("Duration", {}).get("number"),
        props.get("Release Date", {}).get("date")
    ]

    return not all(checks)

# =========================================================
# UPDATE PAGE
# =========================================================

def update_music_page(page, info):

    props = {}

    notion_props = page.get("properties", {})

    title = info.get("track")
    artist = info.get("artist")
    thumbnail = info.get("thumbnail")
    published = info.get("published")
    language_code = info.get("language")

    duration = parse_duration(
        info.get("duration")
    )

    print(f"Updating: {title}")

    # =====================================================
    # COVER
    # =====================================================

    if not notion_props.get("Cover", {}).get("files", []):

        if thumbnail:

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

    if not notion_props.get("Artist", {}).get("relation", []):

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

    if not notion_props.get("Genre", {}).get("relation", []):

        genres = clean_genres(info)

        relations = []

        for genre in genres:

            gid = get_or_create(
                genre,
                genre_cache,
                GENRE_DB_ID
            )

            if gid:

                relations.append({
                    "id": gid
                })

        if relations:

            props["Genre"] = {
                "relation": relations
            }

    # =====================================================
    # FORMAT
    # =====================================================

    if not notion_props.get("Format", {}).get("relation", []):

        fid = get_or_create(
            "Song",
            format_cache,
            FORMAT_DB_ID
        )

        if fid:

            props["Format"] = {
                "relation": [
                    {
                        "id": fid
                    }
                ]
            }

    # =====================================================
    # LANGUAGE
    # =====================================================

    if not notion_props.get("Language", {}).get("relation", []):

        if language_code:

            language_code = language_code.lower()

            if "-" in language_code:
                language_code = language_code.split("-")[0]

            language_name = LANGUAGE_MAP.get(language_code)

            if language_name:

                lid = get_or_create(
                    language_name,
                    language_cache,
                    LANGUAGE_DB_ID
                )

                if lid:

                    props["Language"] = {
                        "relation": [
                            {
                                "id": lid
                            }
                        ]
                    }

    # =====================================================
    # DURATION
    # =====================================================

    if not notion_props.get("Duration", {}).get("number"):

        if duration:

            props["Duration"] = {
                "number": duration
            }

    # =====================================================
    # RELEASE DATE
    # =====================================================

    if not notion_props.get("Release Date", {}).get("date"):

        if published:

            props["Release Date"] = {
                "date": {
                    "start": published[:10]
                }
            }

    # =====================================================
    # PATCH
    # =====================================================

    if not props:

        print("Nothing to update")
        return False

    response = requests.patch(
        f"https://api.notion.com/v1/pages/{page['id']}",
        headers=HEADERS,
        json={
            "properties": props
        }
    )

    print("PATCH STATUS:", response.status_code)
    print(response.text)

    return response.status_code == 200

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
            # URL CHECK
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
            # METADATA
            # =================================================

            metadata = fetch_youtube_metadata(
                yt_link
            )

            if not metadata:

                print("Metadata fetch failed")

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

            print("MAIN ERROR:", e)

    print("================================")
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print("Done.")

# =========================================================

if __name__ == "__main__":
    main()
