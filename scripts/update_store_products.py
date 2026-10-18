#!/usr/bin/env python3
"""Collect eligible discounted products from public official retailer pages.

Only products with structured price, original/high price, image and product URL are
published as verified retailer offers. No paid APIs or credentials are used.
"""
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

OUT = Path("data/store-products.json")
MAX_PER_STORE = 18
MAX_TOTAL = 120
USER_AGENT = "Mozilla/5.0 (compatible; BubuCareDeals/1.0; +https://github.com/marwlo-ops/bubu-care)"

STORES = [
    {"name": "Rossmann", "url": "https://www.rossmann.pl/promocje", "hosts": ["rossmann.pl"]},
    {"name": "Hebe", "url": "https://www.hebe.pl/promocje/", "hosts": ["hebe.pl"]},
    {"name": "Super-Pharm", "url": "https://www.superpharm.pl/promocje", "hosts": ["superpharm.pl"]},
    {"name": "Reserved", "url": "https://www.reserved.com/pl/pl/wyprzedaz/kobieta", "hosts": ["reserved.com"]},
    {"name": "H&M", "url": "https://www2.hm.com/pl_pl/sale.html", "hosts": ["hm.com"]},
    {"name": "Sinsay", "url": "https://www.sinsay.com/pl/pl/all/wyprzedaz-do-50/l-sale-all", "hosts": ["sinsay.com"]},
    {"name": "New Yorker", "url": "https://www.newyorker.de/pl/", "hosts": ["newyorker.de"]},
    {"name": "Zara", "url": "https://www.zara.com/pl/pl/", "hosts": ["zara.com"]},
    {"name": "Bershka", "url": "https://www.bershka.com/pl/", "hosts": ["bershka.com"]},
    {"name": "Pull&Bear", "url": "https://www.pullandbear.com/pl/", "hosts": ["pullandbear.com"]},
    {"name": "Stradivarius", "url": "https://www.stradivarius.com/pl/", "hosts": ["stradivarius.com"]},
    {"name": "Cropp", "url": "https://www.cropp.com/pl/pl/", "hosts": ["cropp.com"]},
    {"name": "House", "url": "https://www.housebrand.com/pl/pl/", "hosts": ["housebrand.com"]},
    {"name": "Mohito", "url": "https://www.mohito.com/pl/pl/", "hosts": ["mohito.com"]},
    {"name": "CCC", "url": "https://ccc.eu/pl", "hosts": ["ccc.eu"]},
    {"name": "Deichmann", "url": "https://www.deichmann.com/PL/pl/shop/welcome.html", "hosts": ["deichmann.com"]},
]

CATEGORY_RULES = {
    "beauty": r"kosmet|pielęgn|pielegn|makijaż|makijaz|krem|serum|szampon|masecz|dezodor|pharmaceris|bioderma|cerave|svr|neboa|isana|rossmann|hebe|super.?pharm",
    "food": r"jedzen|spożyw|spozyw|kawa|herbat|czekolad|przekąsk|przekask|makaron|ryż|ryz|płatki|platki|słodycz|slodycz|żywno|zywno|skyr|jogurt|protein bar",
    "supplements": r"suplement|witamin|kreatyn|kolagen|białk|bialk|odżywka|odzywka|magnez|omega.?3|elektrolit",
    "fragrance": r"perfum|eau de|parfum|woda toaletowa|woda perfumowana|zapach",
    "shoes": r"buty|obuwie|sneaker|adidas|nike|puma|reebok|trampk|botk|sandał|sandal|ccc|deichmann",
    "clothes": r"ubran|odzież|odziez|sukien|spodnie|bluz|kurtk|sweter|koszul|bielizn|skarpet|new yorker|zara|bershka|pull.?bear|stradivarius|cropp|mohito|reserved|sinsay|h&m",
    "accessories": r"torebk|plecak|portfel|pasek|biżuteri|bizuteri|zegarek|okulary|czapk|szalik|rękawicz|rekawicz|akcesori|moda",
}

def clean_text(value):
    if isinstance(value, (dict, list)):
        return ""
    value = unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", value).strip()

def number(value):
    if isinstance(value, dict):
        value = value.get("value") or value.get("@value")
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        return float(str(value).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None

def walk(node):
    if isinstance(node, dict):
        typ = node.get("@type", "")
        types = typ if isinstance(typ, list) else [typ]
        if any(str(t).lower() == "product" for t in types):
            yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)

def image_url(value, base):
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("url") or value.get("@id") or ""
    value = urljoin(base, str(value or ""))
    return value if value.startswith("https://") else ""

def offer_values(product):
    offers = product.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if isinstance(offers, dict) and isinstance(offers.get("offers"), list):
        offers = offers["offers"][0] if offers["offers"] else offers
    if not isinstance(offers, dict):
        offers = {}
    price = number(offers.get("price") or offers.get("lowPrice") or product.get("price"))
    old = number(offers.get("highPrice") or offers.get("priceValidUntilOriginal") or product.get("highPrice"))
    currency = offers.get("priceCurrency") or "PLN"
    availability = str(offers.get("availability") or "")
    url = offers.get("url") or product.get("url") or ""
    return price, old, currency, availability, url

def category_of(title, description, store):
    text = (title + " " + description + " " + store).lower()
    for category, pattern in CATEGORY_RULES.items():
        if re.search(pattern, text, re.I):
            return category
    # Official retailer identity alone is not enough to guess a product category.
    return ""

def fetch_store(store):
    result = {"store": store["name"], "sourceUrl": store["url"], "count": 0, "status": "no_structured_discounted_products"}
    req = urllib.request.Request(store["url"], headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read(5_000_000).decode("utf-8", "replace")
        scripts = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>', raw, re.I | re.S)
        products = []
        seen = set()
        for script in scripts:
            try:
                payload = json.loads(unescape(script.strip()))
            except (json.JSONDecodeError, TypeError):
                continue
            for p in walk(payload):
                title = clean_text(p.get("name"))
                description = clean_text(p.get("description"))[:350]
                price, old, currency, availability, product_url = offer_values(p)
                image = image_url(p.get("image"), store["url"])
                product_url = urljoin(store["url"], str(product_url or ""))
                host = urlparse(product_url).netloc.lower()
                allowed_host = any(host == h or host.endswith("." + h) for h in store["hosts"])
                category = category_of(title, description, store["name"])
                if not title or not image or not allowed_host or not category or price is None or currency not in ("PLN", "zł", "PLN "):
                    continue
                if price <= 0 or price > 100 or old is None or old <= price:
                    continue
                discount = round((old - price) / old * 100)
                if discount < 20:
                    continue
                key = product_url
                if key in seen:
                    continue
                seen.add(key)
                products.append({
                    "id": store["name"] + "|" + key,
                    "store": store["name"], "title": title, "description": description,
                    "url": product_url, "image": image, "price": round(price, 2),
                    "oldPrice": round(old, 2), "discount": discount, "currency": "PLN",
                    "category": category, "source": store["name"] + " · oficjalny sklep",
                    "sourceUrl": store["url"], "verifiedAt": datetime.now(timezone.utc).isoformat(),
                    "availability": availability
                })
        products.sort(key=lambda x: (-x["discount"], x["price"]))
        result["count"] = min(len(products), MAX_PER_STORE)
        result["status"] = "ok" if products else "no_structured_discounted_products"
        result["items"] = products[:MAX_PER_STORE]
    except Exception as exc:
        result["status"] = "source_unavailable"
        result["error"] = type(exc).__name__ + ": " + str(exc)[:180]
        result["items"] = []
    return result

def main():
    all_products, statuses = [], []
    for store in STORES:
        result = fetch_store(store)
        statuses.append({k: result.get(k) for k in ("store", "sourceUrl", "count", "status", "error") if k in result})
        all_products.extend(result.get("items", []))
        print(f'{store["name"]}: {result["count"]} verified offers ({result["status"]})')
        time.sleep(0.4)
    payload = {
        "source": "Public structured product data from official retailer pages",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "rules": {"maxPricePLN": 100, "minimumDiscountPercent": 20, "requiresProductImage": True, "requiresOriginalPrice": True},
        "attribution": "Ceny i zdjęcia pobrane z oficjalnych stron sklepów. Sprawdź warunki oraz dostępność u sprzedawcy przed zakupem.",
        "statuses": statuses,
        "items": all_products[:MAX_TOTAL]
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(payload['items'])} eligible official-store offers.")

if __name__ == "__main__":
    main()
