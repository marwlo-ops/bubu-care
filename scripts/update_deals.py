#!/usr/bin/env python3
"""Refresh the public Pepper RSS snapshot for Bubu Care. Uses Python stdlib only."""
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from html import unescape
import re

FEED_URL = "https://www.pepper.pl/rss/wszystkie?feeder_proxy=1"
OUT = Path("data/pepper.json")
MAX_ITEMS = 80

def clean_html(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", unescape(value)).strip()

def text_of(node, name):
    found = node.find(name)
    return (found.text or "").strip() if found is not None else ""

def main():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "BubuCareDeals/1.0 (RSS reader)"})
    with urllib.request.urlopen(req, timeout=25) as response:
        raw = response.read()
    root = ET.fromstring(raw)
    items = []
    for item in root.findall(".//item")[:MAX_ITEMS]:
        title = clean_html(text_of(item, "title"))
        link = text_of(item, "link")
        if not title or not link.startswith("https://www.pepper.pl/"):
            continue
        pub_date = text_of(item, "pubDate")
        try:
            published = parsedate_to_datetime(pub_date).astimezone(timezone.utc).isoformat()
        except Exception:
            published = ""
        description = clean_html(text_of(item, "description"))[:500]
        items.append({
            "title": title,
            "url": link,
            "publishedAt": published,
            "description": description,
            "source": "Pepper.pl"
        })
    if not items:
        raise RuntimeError("RSS feed returned no usable offers; keeping previous snapshot.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "Pepper.pl RSS",
        "sourceUrl": FEED_URL,
        "attribution": "Okazje pochodzą z Pepper.pl. Warunki, ceny i dostępność sprawdź na stronie źródłowej.",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "items": items
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(items)} Pepper offers to {OUT}")

if __name__ == "__main__":
    main()
