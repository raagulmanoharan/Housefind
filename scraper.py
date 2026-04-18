"""
NoBroker listings scraper.

Uses Playwright to load the NoBroker search page, scrolls to trigger lazy
loading, and extracts per-listing fields from the rendered DOM. NoBroker's
markup changes periodically; if selectors break, run with --debug to dump
the first card's outerHTML and adjust SELECTORS below.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.async_api import Browser, Page, TimeoutError as PWTimeout, async_playwright


CITY_CODES = {
    "bangalore": "bangalore",
    "mumbai": "mumbai",
    "pune": "pune",
    "chennai": "chennai",
    "hyderabad": "hyderabad",
    "delhi": "delhi_ncr",
    "gurgaon": "gurgaon",
    "noida": "noida",
    "kolkata": "kolkata",
    "ahmedabad": "ahmedabad",
}

BHK_CODES = {"1": "BHK1", "2": "BHK2", "3": "BHK3", "4": "BHK4", "5": "BHK4PLUS"}

PROPERTY_TYPES = {
    "apartment": "AP",
    "independent": "IH",
    "villa": "VL",
    "builder_floor": "BF",
    "studio": "ST",
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class Listing:
    title: str = ""
    price: str = ""
    deposit: str = ""
    bhk: str = ""
    area: str = ""
    furnishing: str = ""
    locality: str = ""
    property_type: str = ""
    available_from: str = ""
    posted_by: str = ""
    url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def build_url(city: str, bhk: list[str] | None, prop_type: str | None,
              min_rent: int | None, max_rent: int | None) -> str:
    city_code = CITY_CODES.get(city.lower())
    if not city_code:
        raise ValueError(f"Unknown city {city!r}. Known: {', '.join(CITY_CODES)}")

    params: dict[str, str] = {"searchParam": "", "city": city_code}
    if bhk:
        params["type"] = ",".join(BHK_CODES[b] for b in bhk if b in BHK_CODES)
    if prop_type and prop_type in PROPERTY_TYPES:
        params["propertyType"] = PROPERTY_TYPES[prop_type]
    if min_rent is not None:
        params["rentMin"] = str(min_rent)
    if max_rent is not None:
        params["rentMax"] = str(max_rent)

    return f"https://www.nobroker.in/property/rent/{city_code}/multiple?{urlencode(params)}"


async def auto_scroll(page: Page, max_scrolls: int, pause_ms: int = 1500) -> None:
    prev_height = 0
    for i in range(max_scrolls):
        height = await page.evaluate("document.body.scrollHeight")
        if height == prev_height and i > 2:
            break
        prev_height = height
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(pause_ms)


def clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


async def extract_listings(page: Page) -> list[Listing]:
    cards = await page.query_selector_all('[data-testid="card-link"], article, div.nb__3_Rfp, div.card')
    if not cards:
        cards = await page.query_selector_all('a[href*="/detail/"]')

    results: list[Listing] = []
    seen_urls: set[str] = set()

    for card in cards:
        try:
            html = await card.evaluate("el => el.outerHTML")
        except Exception:
            continue

        text = clean(await card.inner_text())
        href = ""
        link = await card.query_selector('a[href*="/detail/"]') or card
        try:
            href = await link.get_attribute("href") or ""
        except Exception:
            pass
        if href and not href.startswith("http"):
            href = f"https://www.nobroker.in{href}"
        if href in seen_urls:
            continue
        seen_urls.add(href)

        listing = Listing(url=href, raw={"text": text})

        m = re.search(r"₹\s?([\d,]+)", text)
        if m:
            listing.price = m.group(0)
        m = re.search(r"(\d+(?:\.\d+)?)\s*BHK", text, re.I)
        if m:
            listing.bhk = m.group(0)
        m = re.search(r"(\d[\d,]*)\s*sqft", text, re.I)
        if m:
            listing.area = m.group(0)
        for kw in ("Fully Furnished", "Semi Furnished", "Unfurnished", "Semi-Furnished"):
            if kw.lower() in text.lower():
                listing.furnishing = kw
                break
        m = re.search(r"Deposit[:\s]*₹?\s?([\d,]+)", text, re.I)
        if m:
            listing.deposit = m.group(1)
        for pt in ("Apartment", "Independent House", "Villa", "Builder Floor", "Studio"):
            if pt.lower() in text.lower():
                listing.property_type = pt
                break

        title_el = await card.query_selector("h2, h3, [class*='heading']")
        if title_el:
            listing.title = clean(await title_el.inner_text())

        loc_el = await card.query_selector("[class*='location'], [class*='locality']")
        if loc_el:
            listing.locality = clean(await loc_el.inner_text())

        if not listing.price and not listing.bhk and not href:
            continue

        results.append(listing)

    return results


async def scrape(city: str, bhk: list[str] | None, prop_type: str | None,
                 min_rent: int | None, max_rent: int | None,
                 max_scrolls: int, headless: bool, debug: bool) -> list[Listing]:
    url = build_url(city, bhk, prop_type, min_rent, max_rent)
    print(f"[scrape] URL: {url}", file=sys.stderr)

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(user_agent=USER_AGENT, viewport={"width": 1366, "height": 900})
        page = await ctx.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except PWTimeout:
            print("[scrape] initial load timed out, proceeding anyway", file=sys.stderr)

        try:
            await page.wait_for_selector('a[href*="/detail/"]', timeout=15000)
        except PWTimeout:
            print("[scrape] no listing links found after 15s — page may be blocked or empty", file=sys.stderr)

        await auto_scroll(page, max_scrolls=max_scrolls)

        if debug:
            first = await page.query_selector('a[href*="/detail/"]')
            if first:
                html = await first.evaluate("el => el.closest('article,div') ? el.closest('article,div').outerHTML : el.outerHTML")
                Path("debug_card.html").write_text(html)
                print("[debug] wrote debug_card.html", file=sys.stderr)

        listings = await extract_listings(page)
        await browser.close()
        return listings


def save(listings: list[Listing], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix == ".json":
        out.write_text(json.dumps([asdict(l) for l in listings], indent=2, ensure_ascii=False))
    elif out.suffix == ".csv":
        fields = [f for f in Listing.__dataclass_fields__ if f != "raw"]
        with out.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for l in listings:
                row = asdict(l)
                row.pop("raw", None)
                writer.writerow(row)
    else:
        raise ValueError("Output file must end in .json or .csv")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape NoBroker rental listings.")
    p.add_argument("--city", default="bangalore", help=f"One of: {', '.join(CITY_CODES)}")
    p.add_argument("--bhk", nargs="*", default=None, choices=list(BHK_CODES), help="BHK filters, e.g. --bhk 2 3")
    p.add_argument("--type", dest="prop_type", default=None, choices=list(PROPERTY_TYPES))
    p.add_argument("--min-rent", type=int, default=None)
    p.add_argument("--max-rent", type=int, default=None)
    p.add_argument("--max-scrolls", type=int, default=10, help="How many infinite-scroll rounds to trigger")
    p.add_argument("--headed", action="store_true", help="Run browser with a visible window")
    p.add_argument("--debug", action="store_true", help="Dump first card HTML to debug_card.html")
    p.add_argument("-o", "--output", type=Path, default=Path("output/listings.json"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    listings = asyncio.run(scrape(
        city=args.city,
        bhk=args.bhk,
        prop_type=args.prop_type,
        min_rent=args.min_rent,
        max_rent=args.max_rent,
        max_scrolls=args.max_scrolls,
        headless=not args.headed,
        debug=args.debug,
    ))
    save(listings, args.output)
    print(f"[done] {len(listings)} listings -> {args.output}")


if __name__ == "__main__":
    main()
