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
FORMAT_DB_ID = "36d451056c5e8018bddfc238554cde03"
LANGUAGE_DB_ID = "24c451056c5e80a7b6a1c22847688e3f"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

FUZZY_THRESHOLD = 96

# =========================================================
# HELPERS
# =========================================================

def safe_json(response):

    try:
        return response.json()
    except:
        return {}

# =========================================================
# CLEAN TITLE
# =========================================================

def clean_track_title(title):

    if not title:
        return ""

    cleaned = title

    remove_patterns = [

        # =================================================
        # MOVIE TAGS
        # =================================================

        r'\(from ".*?"\)',
        r"\(from '.*?'\)",

        # =================================================
        # FEAT / FT
        # =================================================

        r'\(feat\..*?\)',
        r'\(ft\..*?\)',
        r'\[feat\..*?\]',
        r'\[ft\..*?\]',

        r'feat\..*',
        r'ft\..*',

        # =================================================
        # VIDEO TAGS
        # =================================================

        r'\(official video\)',
        r'\(official lyric video\)',
        r'\(lyric video\)',
        r'\(audio\)',
        r'\(video\)',
        r'\(full song\)',
        r'\(music video\)',

        r'\[official video\]',
        r'\[official lyric video\]',
        r'\[lyric video\]',
        r'\[audio\]',
        r'\[video\]',
        r'\[full song\]',
        r'\[music video\]',

        # =================================================
        # QUALITY TAGS
        # =================================================

        r'\(4k.*?\)',
        r'\(hd.*?\)',
        r'\[4k.*?\]',
        r'\[hd.*?\]',

        r'official video',
        r'official lyric video',
        r'lyric video',
        r'video song',
        r'full song',
        r'audio jukebox',
        r'music video',
        r'4k',
        r'hd'
    ]

    for pattern in remove_patterns:

        cleaned = re.sub(
            pattern,
            '',
            cleaned,
            flags=re.IGNORECASE
        )

    cleaned = re.sub(
        r'\s+',
        ' ',
        cleaned
    ).strip()

    cleaned = cleaned.strip("-|:[]() ")

    return cleaned

# =========================================================
# EXTRACT SINGERS
# =========================================================

def extract_singers(description):

    if not description:
        return []

    lines = description.splitlines()

    singers = []

    patterns = [

        r'playback singer[s]?\s*[:\-]\s*(.*)',
        r'singer[s]?\s*[:\-]\s*(.*)',
        r'vocals\s*[:\-]\s*(.*)',
        r'performed by\s*[:\-]\s*(.*)'
    ]

    for line in lines:

        clean_line = line.strip()

        for pattern in patterns:

            match = re.search(
                pattern,
                clean_line,
                flags=re.IGNORECASE
            )

            if match:

                raw = match.group(1)

                parts = re.split(
                    r',|&| and ',
                    raw
                )

                for part in parts:

                    name = part.strip()

                    if (
                        len(name) > 1
                        and len(name) < 60
                    ):
                        singers.append(name)

    singers = list(dict.fromkeys(singers))

    return singers

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
# LANGUAGE DETECTION
# =========================================================

def detect_language(info):

    title = info.get("track", "").lower()
    artist = info.get("artist", "").lower()
    description = info.get("description", "").lower()

    full_text = f"{title} {artist} {description}"

    for ch in full_text:

        code = ord(ch)

        if 0x0C00 <= code <= 0x0C7F:
            return "Telugu"

        if 0x0B80 <= code <= 0x0BFF:
            return "Tamil"

        if 0x0C80 <= code <= 0x0CFF:
            return "Kannada"

        if 0x0D00 <= code <= 0x0D7F:
            return "Malayalam"

        if 0x0900 <= code <= 0x097F:
            return "Hindi"

    label_map = {

        "aditya music": "Telugu",
        "mango music": "Telugu",
        "saregama telugu": "Telugu",

        "think music": "Tamil",
        "sony music south": "Tamil",

        "lahari music": "Kannada",

        "t-series": "Hindi",
        "zee music": "Hindi",
        "saregama": "Hindi"
    }

    for key, value in label_map.items():

        if key in full_text:
            return value

    return "English"

# =========================================================
# DETECT CONTEXT
# =========================================================

def detect_context(info):

    description = info.get("description", "").lower()
    title = info.get("track", "").lower()

    full_text = f"{title} {description}"

    if "background score" in full_text:
        return "Background Score"

    if "theme" in full_text:
        return "Theme Music"

    if (
        'from "' in full_text
        or "motion picture" in full_text
        or "ost" in full_text
    ):
        return "Soundtrack"

    return "Single"

# =========================================================
# DETECT VIBES
# =========================================================

def detect_vibes(info):

    title = info.get("track", "").lower()
    artist = info.get("artist", "").lower()
    description = info.get("description", "").lower()

    full_text = f"{title} {artist} {description}"

    vibes = []

    mass_words = [
        "mass",
        "boss",
        "king",
        "beast",
        "rowdy"
    ]

    if any(word in full_text for word in mass_words):
        vibes.append("Mass Song")

    elevation_words = [
        "theme",
        "fear",
        "rage",
        "arrival",
        "warning",
        "anthem"
    ]

    if any(word in full_text for word in elevation_words):
        vibes.append("Elevation Song")

    melody_words = [
        "melody",
        "acoustic",
        "soft"
    ]

    if any(word in full_text for word in melody_words):
        vibes.append("Melody Song")

    failure_words = [
        "breakup",
        "alone",
        "missing",
        "goodbye"
    ]

    if any(word in full_text for word in failure_words):
        vibes.append("Love Failure Song")

    dance_words = [
        "dance",
        "party",
        "club"
    ]

    if any(word in full_text for word in dance_words):
        vibes.append("Dance Beat")

    return vibes

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

        print("YOUTUBE STATUS:", response.status_code)

        items = data.get("items", [])

        if not items:
            return None

        item = items[0]

        snippet = item.get("snippet", {})

        raw_title = snippet.get("title", "")

        title = clean_track_title(raw_title)

        description = snippet.get("description", "")
        channel = snippet.get("channelTitle", "")
        published = snippet.get("publishedAt", "")

        thumbnails = snippet.get("thumbnails", {})

        thumbnail = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
        )

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

        singers = extract_singers(description)

        return {
            "track": track,
            "artist": artist,
            "singers": singers,
            "thumbnail": thumbnail,
            "published": published,
            "description": description
        }

    except Exception as e:

        print("YT ERROR:", e)
        return None

# =========================================================
# UPDATE PAGE
# =========================================================

def update_music_page(page, info):

    props = {}

    notion_props = page.get("properties", {})

    title = info.get("track")
    artist = info.get("artist")
    singers = info.get("singers", [])

    thumbnail = info.get("thumbnail")
    published = info.get("published")

    language_name = detect_language(info)
    context = detect_context(info)
    vibes = detect_vibes(info)

    print(f"Updating: {title}")
    print(f"Detected Language: {language_name}")
    print(f"Singers: {singers}")
    print(f"Context: {context}")
    print(f"Vibes: {vibes}")

    # =====================================================
    # TITLE
    # =====================================================

    current_title_data = notion_props.get(
        "Name",
        {}
    ).get("title", [])

    current_title = ""

    if current_title_data:

        current_title = current_title_data[0][
            "plain_text"
        ].strip()

    clean_title = title.strip()

    if clean_title and clean_title != current_title:

        print(f"Updating Title: {clean_title}")

        props["Name"] = {
            "title": [
                {
                    "text": {
                        "content": clean_title
                    }
                }
            ]
        }

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
    # ARTISTS + SINGERS
    # =====================================================

    current_artists = notion_props.get(
        "Artist",
        {}
    ).get("relation", [])

    if not current_artists:

        all_artists = [artist] + singers

        all_artists = list(dict.fromkeys(all_artists))

        relations = []

        for artist_name in all_artists:

            aid = get_or_create(
                artist_name,
                artist_cache,
                ARTIST_DB_ID
            )

            if aid:

                relations.append({
                    "id": aid
                })

        if relations:

            props["Artist"] = {
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
    # CONTEXT
    # =====================================================

    if "Context" in notion_props:

        current = notion_props.get(
            "Context",
            {}
        ).get("multi_select", [])

        if not current:

            props["Context"] = {
                "multi_select": [
                    {
                        "name": context
                    }
                ]
            }

    # =====================================================
    # VIBES
    # =====================================================

    if "Mood / Vibe" in notion_props:

        current = notion_props.get(
            "Mood / Vibe",
            {}
        ).get("multi_select", [])

        if not current and vibes:

            props["Mood / Vibe"] = {
                "multi_select": [
                    {
                        "name": vibe
                    }
                    for vibe in vibes
                ]
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

            if not yt_link:

                print("Missing URL")

                skipped += 1
                continue

            if "youtube" not in yt_link.lower():

                print("Skipping non-youtube URL")

                skipped += 1
                continue

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
