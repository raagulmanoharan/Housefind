# Housefind

Playwright-based scraper for NoBroker rental listings. This is a **starter
scaffold** — NoBroker actively fights scrapers and the DOM changes often, so
expect to adjust selectors over time.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Usage

```bash
# Default: Bangalore, all BHKs, JSON output
python scraper.py

# 2/3 BHK apartments in Pune under 40k, write CSV
python scraper.py --city pune --bhk 2 3 --type apartment --max-rent 40000 \
    -o output/pune.csv

# Run with a visible browser to see what's happening
python scraper.py --headed

# Dump the first card's HTML so you can update selectors when they break
python scraper.py --debug
```

### CLI flags

| flag | description |
| --- | --- |
| `--city` | `bangalore`, `mumbai`, `pune`, `chennai`, `hyderabad`, `delhi`, `gurgaon`, `noida`, `kolkata`, `ahmedabad` |
| `--bhk` | one or more of `1 2 3 4 5` |
| `--type` | `apartment`, `independent`, `villa`, `builder_floor`, `studio` |
| `--min-rent` / `--max-rent` | integer rupees |
| `--max-scrolls` | how many infinite-scroll rounds (default 10) |
| `--headed` | show the browser window |
| `--debug` | dump first card HTML to `debug_card.html` |
| `-o` | output path (`.json` or `.csv`) |

## Fields extracted

`title`, `price`, `deposit`, `bhk`, `area`, `furnishing`, `locality`,
`property_type`, `available_from`, `posted_by`, `url`.

Many fields are parsed from card text via regex; if NoBroker reshapes a card,
the corresponding field will silently go empty. Use `--debug` to inspect.

## Caveats

- **ToS**: NoBroker's terms prohibit automated scraping. Use this for personal
  search only. Don't redistribute scraped data.
- **Anti-bot**: They use Cloudflare + JS challenges. If you see empty results
  or a challenge page, try `--headed`, add `playwright-stealth`, rotate
  residential proxies, or slow down scrolls.
- **Contact details**: Phone numbers are gated behind an OTP-verified login
  and are not scraped here.
- **Rate limiting**: The script currently hits one page per run. If you loop
  over cities/filters, add delays between runs and respect their servers.

## When selectors break

1. Run `python scraper.py --headed --debug` and watch the page.
2. Open `debug_card.html` and inspect class names / data attributes.
3. Update the selectors in `extract_listings()` in `scraper.py`.
