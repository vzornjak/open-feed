#!/usr/bin/env python3
"""Generate a complete, deduplicated KRIK podcast RSS feed."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SLUG = "krik-krimi-petak-na-prvom"
SHOW_URL = f"https://radio.hrt.hr/slusaonica/{SLUG}"
OFFICIAL_FEED_URL = f"https://feed.hrt.hr/podcast/{SLUG}.xml"
IMAGE_URL = "https://api.hrt.hr/media/eb/a6/krik-krimi-petak-na-prvom-20220802121653.webp"
DEFAULT_SELF_URL = "https://raw.githubusercontent.com/vzornjak/krik-feed/main/krik.xml"
PAGE_SIZE = 10
MAX_PAGES = 100
PAGE_BATCH = 8
USER_AGENT = "KRIK/1.0"

NS_ATOM = "http://www.w3.org/2005/Atom"
NS_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("atom", NS_ATOM)
ET.register_namespace("itunes", NS_ITUNES)


@dataclass
class Episode:
    title: str
    description: str
    audio_url: str
    published: dt.datetime
    audio_id: str | None = None
    length: int = 0
    page_url: str = SHOW_URL
    image_url: str = IMAGE_URL
    source: str = "KRIK"

    @property
    def key(self) -> str:
        return canonical_audio_url(self.audio_url)

    @property
    def guid(self) -> str:
        if self.audio_id:
            return f"urn:krik:audio:{self.audio_id}"
        digest = hashlib.sha256(self.key.encode("utf-8")).hexdigest()[:24]
        return f"urn:krik:audio:{digest}"


def request_bytes(url: str, *, method: str = "GET", headers: dict[str, str] | None = None) -> bytes:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers, method=method)
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError(f"Ne mogu dohvatiti {url}: {last_error}")


def request_json(url: str) -> dict:
    return json.loads(request_bytes(url).decode("utf-8"))


def parse_datetime(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(dt.timezone.utc)


def canonical_audio_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))


def audio_metadata(record: dict) -> tuple[str, str | None] | None:
    metadata = (record.get("audio") or {}).get("metadata") or []
    first = metadata[0] if metadata else None
    if not isinstance(first, dict) or not first.get("path"):
        return None
    return first["path"], str(first["id"]) if first.get("id") is not None else None


def episode_from_api(record: dict, source: str) -> Episode | None:
    audio = audio_metadata(record)
    if not audio:
        return None
    audio_url, audio_id = audio
    if source == "EMISIJE":
        content = ((record.get("bag") or {}).get("contentItems") or [{}])[0]
        published_raw = content.get("broadcastStart")
        query_name = "epizoda"
    else:
        published_raw = record.get("originalPublishedUtc")
        query_name = "podcast"
    if not published_raw:
        return None
    published = parse_datetime(published_raw)
    stamp = published.strftime("%Y%m%d%H%M")
    image_metadata = (record.get("thumbnail") or {}).get("metadata") or []
    first_image = image_metadata[0] if image_metadata and isinstance(image_metadata[0], dict) else {}
    image_url = first_image.get("path") or IMAGE_URL
    return Episode(
        title=(record.get("caption") or "KRIK").strip(),
        description=(record.get("intro") or "").strip(),
        audio_url=audio_url,
        audio_id=audio_id,
        published=published,
        page_url=f"{SHOW_URL}?{query_name}={stamp}",
        image_url=image_url,
        source=source,
    )


def fetch_api_collection(endpoint: str, data_key: str, source: str) -> list[Episode]:
    episodes: list[Episode] = []
    consecutive_empty = 0
    def fetch_page(offset: int) -> tuple[int, list[dict]]:
        query = urllib.parse.urlencode({"slug": SLUG, "offset": offset})
        payload = request_json(f"https://radio.hrt.hr/api/{endpoint}?{query}")
        records = (payload.get("data") or {}).get(data_key) or []
        return offset, records

    for batch_start in range(0, MAX_PAGES, PAGE_BATCH):
        offsets = list(range(batch_start, min(batch_start + PAGE_BATCH, MAX_PAGES)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=PAGE_BATCH) as pool:
            pages = sorted(pool.map(fetch_page, offsets))
        for offset, records in pages:
            # Izvor pri paralelnim pozivima rijetko vrati samo dio stranice.
            # Kratku stranicu zato potvrđujemo još dvaput i čuvamo najdulji odgovor.
            if len(records) < PAGE_SIZE:
                for _ in range(2):
                    _, confirmed = fetch_page(offset)
                    if len(confirmed) > len(records):
                        records = confirmed
            if not records:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    return episodes
                continue
            consecutive_empty = 0
            episodes.extend(item for record in records if (item := episode_from_api(record, source)))
    raise RuntimeError(f"API nije završio nakon {MAX_PAGES} stranica: {endpoint}")


def fetch_api_latest(endpoint: str, data_key: str, source: str) -> list[Episode]:
    """Fetch only the newest page, retrying rare partial responses."""
    query = urllib.parse.urlencode({"slug": SLUG, "offset": 0})
    url = f"https://radio.hrt.hr/api/{endpoint}?{query}"
    best: list[dict] = []
    for attempt in range(3):
        payload = request_json(url)
        records = (payload.get("data") or {}).get(data_key) or []
        if len(records) > len(best):
            best = records
        if len(best) >= PAGE_SIZE:
            break
        if attempt < 2:
            time.sleep(1)
    if not best:
        raise RuntimeError(f"API nije vratio najnovije stavke: {endpoint}")
    return [item for record in best if (item := episode_from_api(record, source))]


def fetch_official_feed() -> list[Episode]:
    root = ET.fromstring(request_bytes(OFFICIAL_FEED_URL))
    result: list[Episode] = []
    for item in root.findall("./channel/item"):
        enclosure = item.find("enclosure")
        pub_date = item.findtext("pubDate")
        if enclosure is None or not enclosure.get("url") or not pub_date:
            continue
        parsed_date = email.utils.parsedate_to_datetime(pub_date).astimezone(dt.timezone.utc)
        result.append(
            Episode(
                title=(item.findtext("title") or "KRIK").strip(),
                description=(item.findtext("description") or "").strip(),
                audio_url=enclosure.get("url", ""),
                published=parsed_date,
                length=int(enclosure.get("length") or 0),
                page_url=item.findtext("link") or SHOW_URL,
                source="SLUŽBENI RSS",
            )
        )
    return result


def load_existing_feed(path: Path) -> list[Episode]:
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    result: list[Episode] = []
    for item in root.findall("./channel/item"):
        enclosure = item.find("enclosure")
        pub_date = item.findtext("pubDate")
        if enclosure is None or not enclosure.get("url") or not pub_date:
            continue
        guid = item.findtext("guid") or ""
        match = re.fullmatch(r"urn:krik:audio:(.+)", guid)
        image = item.find(f"{{{NS_ITUNES}}}image")
        result.append(
            Episode(
                title=(item.findtext("title") or "KRIK").strip(),
                description=(item.findtext("description") or "").strip(),
                audio_url=enclosure.get("url", ""),
                audio_id=match.group(1) if match else None,
                published=email.utils.parsedate_to_datetime(pub_date).astimezone(dt.timezone.utc),
                length=int(enclosure.get("length") or 0),
                page_url=item.findtext("link") or SHOW_URL,
                image_url=image.get("href") if image is not None and image.get("href") else IMAGE_URL,
                source="POSTOJEĆI RSS",
            )
        )
    return result


def merge_episodes(groups: Iterable[Iterable[Episode]]) -> list[Episode]:
    merged: dict[str, Episode] = {}
    priority = {"POSTOJEĆI RSS": 0, "SLUŽBENI RSS": 1, "PODCAST": 2, "EMISIJE": 3}
    for group in groups:
        for episode in group:
            current = merged.get(episode.key)
            if current is None:
                merged[episode.key] = episode
                continue
            preferred, other = (episode, current) if priority[episode.source] > priority[current.source] else (current, episode)
            preferred.length = preferred.length or other.length
            preferred.audio_id = preferred.audio_id or other.audio_id
            preferred.description = preferred.description or other.description
            preferred.image_url = preferred.image_url or other.image_url
            preferred.published = min(preferred.published, other.published)
            merged[episode.key] = preferred
    return sorted(merged.values(), key=lambda item: (item.published, item.title), reverse=True)


def probe_audio_length(url: str) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = response.headers.get("Content-Length")
            return int(value) if value else 0
    except (urllib.error.URLError, TimeoutError, ValueError):
        return 0


def fill_audio_lengths(episodes: list[Episode], cache_path: Path) -> None:
    cache: dict[str, int] = {}
    if cache_path.exists():
        try:
            cache = {key: int(value) for key, value in json.loads(cache_path.read_text()).items()}
        except (json.JSONDecodeError, ValueError):
            cache = {}
    missing = [episode for episode in episodes if not episode.length and not cache.get(episode.key)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        lengths = pool.map(probe_audio_length, [episode.audio_url for episode in missing])
        for episode, length in zip(missing, lengths):
            if length:
                cache[episode.key] = length
    for episode in episodes:
        episode.length = episode.length or cache.get(episode.key, 0)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(dict(sorted(cache.items())), indent=2) + "\n")


def add_text(parent: ET.Element, tag: str, text: str, attributes: dict[str, str] | None = None) -> ET.Element:
    element = ET.SubElement(parent, tag, attributes or {})
    element.text = text
    return element


def build_rss(episodes: list[Episode], self_url: str) -> bytes:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    add_text(channel, "title", "krik-feed")
    add_text(channel, "link", self_url)
    add_text(channel, "description", "Neslužbeni osobni RSS.")
    add_text(channel, "language", "hr-hr")
    add_text(channel, "generator", "krik-feed")
    add_text(channel, f"{{{NS_ITUNES}}}author", "KRIK")
    add_text(channel, f"{{{NS_ITUNES}}}explicit", "false")
    ET.SubElement(channel, f"{{{NS_ITUNES}}}image", {"href": IMAGE_URL})
    ET.SubElement(channel, f"{{{NS_ATOM}}}link", {"href": self_url, "rel": "self", "type": "application/rss+xml"})
    image = ET.SubElement(channel, "image")
    add_text(image, "url", IMAGE_URL)
    add_text(image, "title", "krik-feed")
    add_text(image, "link", self_url)
    if episodes:
        add_text(channel, "lastBuildDate", email.utils.format_datetime(episodes[0].published, usegmt=True))

    for episode in episodes:
        item = ET.SubElement(channel, "item")
        add_text(item, "title", episode.title)
        add_text(item, "link", episode.page_url)
        add_text(item, "guid", episode.guid, {"isPermaLink": "false"})
        add_text(item, "pubDate", email.utils.format_datetime(episode.published, usegmt=True))
        ET.SubElement(item, "enclosure", {"url": episode.audio_url, "length": str(episode.length), "type": "audio/mpeg"})
        ET.SubElement(item, f"{{{NS_ITUNES}}}image", {"href": episode.image_url})
    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("krik.xml"))
    parser.add_argument("--cache", type=Path, default=Path("data/audio_lengths.json"))
    parser.add_argument("--self-url", default=os.environ.get("FEED_URL", DEFAULT_SELF_URL))
    parser.add_argument("--skip-lengths", action="store_true", help="Ne provjerava veličinu novih MP3 datoteka")
    args = parser.parse_args()

    existing = load_existing_feed(args.output)
    if existing:
        mode = "NOVO"
        official: list[Episode] = []
        emissions = fetch_api_latest("getEpisodes", "lastAvailableEpisodes", "EMISIJE")
        podcasts = fetch_api_latest("getPodcasts", "lastAvailablePodcasts", "PODCAST")
        episodes = merge_episodes([existing, podcasts, emissions])
    else:
        mode = "PUNA_ARHIVA"
        official = fetch_official_feed()
        emissions = fetch_api_collection("getEpisodes", "lastAvailableEpisodes", "EMISIJE")
        podcasts = fetch_api_collection("getPodcasts", "lastAvailablePodcasts", "PODCAST")
        episodes = merge_episodes([official, podcasts, emissions])
    if not args.skip_lengths:
        fill_audio_lengths(episodes, args.cache)
    args.output.write_bytes(build_rss(episodes, args.self_url))
    print(f"NAČIN={mode} EMISIJE={len(emissions)} PODCAST={len(podcasts)} JEDINSTVENO={len(episodes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
