import os
import re
import json
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

FUZZY_THRESHOLD = 85

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

        r'\(from ".*?"\)',
        r"\(from '.*?'\)",

        r'\(telugu version\)',
        r'\(hindi version\)',
        r'\(tamil version\)',
        r'\(kannada version\)',
        r'\(malayalam version\)',

        r'\(telugu\)',
        r'\(hindi\)',
        r'\(tamil\)',
        r'\(kannada\)',
        r'\(malayalam\)',

        r'\[telugu version\]',
        r'\[hindi version\]',
        r'\[tamil version\]',
        r'\[kannada version\]',
        r'\[malayalam version\]',

        r'\[telugu\]',
        r'\[hindi\]',
        r'\[tamil\]',
        r'\[kannada\]',
        r'\[malayalam\]',

        r'\(feat\..*?\)',
        r'\(ft\..*?\)',
        r'\[feat\..*?\]',
        r'\[ft\..*?\]',

        r'feat\..*',
        r'ft\..*',

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
        r'\(\s*\)',
        '',
        cleaned
    )

    cleaned = re.sub(
        r'\[\s*\]',
        '',
        cleaned
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

    lines = [
        line.strip()
        for line in description.splitlines()
        if line.strip()
    ]

    singers = []

    capture = False

    for line in lines:

        lower = line.lower()

        if (
            "playback singer" in lower
            or lower.startswith("singer")
            or "performed by" in lower
            or lower.startswith("vocals")
        ):

            if ":" in line:

                value = line.split(":", 1)[1]

                parts = re.split(
                    r',|&| and ',
                    value
                )

                for part in parts:

                    name = part.strip()

                    if (
                        len(name) > 1
                        and len(name) < 60
                    ):
                        singers.append(name)

            else:
                capture = True

            continue

        if capture:

            stop_words = [

                "composer",
                "lyrics",
                "lyricist",
                "music",
                "label",
                "released",
                "producer",
                "directed",
                "album",
                "movie",
                "film"
            ]

            if any(
                stop in lower
                for stop in stop_words
            ):
                capture = False
                continue

            if (
                len(line) < 60
                and not re.search(r'http|www|\d{4}', line)
            ):

                singers.append(line)

    cleaned = []

    for singer in singers:

        singer = singer.strip()

        singer = re.sub(
            r'^[•\-\–]+',
            '',
            singer
        ).strip()

        if singer:
            cleaned.append(singer)

    cleaned = list(dict.fromkeys(cleaned))

    return cleaned

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
# MOVIE INFERENCE
# =========================================================

def infer_movie_name(info):

    title = info.get("track", "")
    description = info.get("description", "")

    # ============================================
    # FROM "MOVIE"
    # ============================================

    patterns = [

        r'from\s+"([^"]+)"',
        r"from\s+'([^']+)'",
        r'movie\s*[:\-]\s*(.*)',
        r'film\s*[:\-]\s*(.*)',
        r'album\s*[:\-]\s*(.*)'
    ]

    combined = title + "\n" + description

    for pattern in patterns:

        match = re.search(
            pattern,
            combined,
            flags=re.IGNORECASE
        )

        if match:

            value = match.group(1).strip()

            value = value.split("\n")[0].strip()

            if len(value) < 80:
                return value

    # ============================================
    # TITLE INFERENCE
    # ============================================

    known_movies = [

        "salaar",
        "leo",
        "jailer",
        "vikram",
        "beast",
        "master",
        "pushpa",
        "devara",
        "coolie",
        "kgf",
        "kantara",
        "rrr"
    ]

    lower = combined.lower()

    for movie in known_movies:

        if movie in lower:
            return movie.title()

    return None

# =========================================================
# WIKIDATA LANGUAGE
# =========================================================

def get_wikidata_language(search_term):

    try:

        response = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": search_term,
                "language": "en",
                "format": "json"
            },
            timeout=15
        )

        data = safe_json(response)

        search = data.get("search", [])

        blob = json.dumps(search).lower()

        mapping = {

            "tamil": "Tamil",
            "telugu": "Telugu",
            "hindi": "Hindi",
            "kannada": "Kannada",
            "malayalam": "Malayalam"
        }

        for key, value in mapping.items():

            if key in blob:
                return value

    except:
        pass

    return None

# =========================================================
# LANGUAGE DETECTION
# =========================================================

def detect_language(info):

    # ============================================
    # 1. MOVIE
    # ============================================

    movie = infer_movie_name(info)

    if movie:

        print(f"Movie Inferred: {movie}")

        lang = get_wikidata_language(movie)

        if lang:
            return lang

    # ============================================
    # 2. ARTIST
    # ============================================

    artist = info.get("artist")

    if artist:

        lang = get_wikidata_language(artist)

        if lang:
            return lang

    # ============================================
    # 3. DESCRIPTION
    # ============================================

    description = info.get(
        "description",
        ""
    ).lower()

    mapping = {

        "tamil": "Tamil",
        "telugu": "Telugu",
        "hindi": "Hindi",
        "kannada": "Kannada",
        "malayalam": "Malayalam"
    }

    for key, value in mapping.items():

        if key in description:
            return value

    return None

# =========================================================
# DETECT FORMAT
# =========================================================

def detect_format(info):

    title = info.get("track", "").lower()
    description = info.get("description", "").lower()

    full = f"{title} {description}"

    if "podcast" in full:
        return "Podcast"

    if "dj mix" in full:
        return "DJ Mix"

    if "live performance" in full:
        return "Live Performance"

    if "concert" in full:
        return "Concert"

    if "instrumental" in full:
        return "Instrumental"

    if "background score" in full:
        return "Background Score"

    if "theme" in full:
        return "Theme Music"

    if "ost" in full:
        return "OST"

    if "ep" in full:
        return "EP"

    if "album" in full:
        return "Album"

    if "single" in full:
        return "Single"

    return "Song"

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
                "part": "snippet",
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
    format_name = detect_format(info)

    print(f"Updating: {title}")
    print(f"Language: {language_name}")
    print(f"Format: {format_name}")
    print(f"Singers: {singers}")

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
    # ARTISTS
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
            format_name,
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

    if (
        language_name
        and not notion_props.get(
            "Language",
            {}
        ).get("relation", [])
    ):

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
