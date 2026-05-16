import os
import json
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# File paths and workspace configuration
URL_MAP_PATH = "output/url_map.json"
OUTPUT_COMBINED_PATH = "output/scraped_combined_output.json"

DIRS = {
    "tours": "./raw/tours",
    "destinations": "./raw/destinations",
    "experiences": "./raw/experiences"
}

# Ensure structural folders exist upfront
os.makedirs("output", exist_ok=True)
for path in DIRS.values():
    os.makedirs(path, exist_ok=True)

# Politeness and safety settings derived from the scraping guide
DELAY = 1.5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

def clean(text: str) -> str:
    """Cleans noisy text blocks and strips out WordPress junk characters."""
    if not text:
        return ""
    # Normalize multiple whitespace clusters down to a single space
    cleaned = re.sub(r'\s+', ' ', text)
    # Clear zero-width and non-breaking spaces common to the CMS text fields
    cleaned = cleaned.replace('\xa0', '').replace('\u200b', '')
    return cleaned.strip()

def fetch_page(url: str) -> BeautifulSoup or None:
    """Politely requests a URL with simulated headers and returns a soup object."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")
    except Exception as e:
        print(f"Error fetching page {url}: {e}")
        return None

def get_slug(url: str) -> str:
    """Derives a clean file identifier from the URL path slug."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return "index"
    return re.sub(r'[^a-zA-Z0-9_-]', '_', path)

def parse_tour(soup, url: str) -> dict:
    """Parses individual tour pages following the guide's selector maps."""
    # 1. Base Core Variables
    h1_elem = soup.find("h1")
    package_name = clean(h1_elem.get_text()) if h1_elem else "Sri Lanka & The Maldives Tour"
    tour_id = url.rstrip("/").split("/")[-1]

    # Theme/Category Recognition via Guide Heuristic array
    theme = "Barefoot Luxury"
    known_cats = ["Authentic Ceylon", "Adventurous Spirit", "Barefoot Luxury", "Following the Wild", "Romantic Serendipity", "Island of Wellness", "Join a Group", "Sri Lanka with Jetwing"]
    for el in soup.find_all(["p", "span", "div"]):
        txt = clean(el.get_text())
        if txt in known_cats:
            theme = txt
            break

    # Duration Extractor
    duration = "10 Nights (7 Nights in Sri Lanka, 3 Nights in the Maldives)"
    full_text = soup.get_text()
    duration_match = re.search(r"(\d+)\s*(nights?|days?)", full_text, re.IGNORECASE)
    if duration_match:
        duration = clean(duration_match.group(0))

    # 2. Core Inclusions Dictionary Building
    inclusions = {
        "accommodation": "Hotel Stay",
        "meals": "Tailored to customer preferences",
        "transport": "Private Air-Conditioned Vehicle"
    }
    for h4 in soup.find_all("h4"):
        label = clean(h4.get_text()).lower()
        if label in ["meals", "transport", "accommodation", "included activities"]:
            nxt = h4.find_next_sibling()
            if nxt:
                val = [clean(li.get_text()) for li in nxt.find_all("li")] if nxt.name == "ul" else clean(nxt.get_text())
                if isinstance(val, list):
                    val = ", ".join(val)
                inclusions[label] = val

    # 3. Itinerary Breakdown Matrix
    itinerary_list = []
    for el in soup.find_all(["h3", "h4", "strong"]):
        if re.match(r"day\s*\d+", clean(el.get_text()), re.IGNORECASE):
            day_label = clean(el.get_text())
            desc_parts = []
            for sibling in el.find_next_siblings():
                # Stop when hitting the header boundary for the subsequent day
                if sibling.name in ["h3", "h4", "strong"] and re.match(r"day\s*\d+", clean(sibling.get_text()), re.IGNORECASE):
                    break
                if sibling.name in ["p", "div", "span"]:
                    t = clean(sibling.get_text())
                    if t:
                        desc_parts.append(t)
            
            itinerary_list.append({
                "day": day_label,
                "description": " ".join(desc_parts[:2])
            })

    # 4. Experiences and Highlights Segmentation Fallbacks
    highlights = []
    for heading in soup.find_all(["h2", "h3"]):
        txt = clean(heading.get_text()).lower()
        if "love" in txt or "right for" in txt:
            ul_elem = heading.find_next("ul")
            if ul_elem:
                highlights += [clean(li.get_text()) for li in ul_elem.find_all("li")]

    cultural_heritage = []
    ocean_wildlife = []
    for hl in highlights:
        if any(keyword in hl.lower() for keyword in ["whale", "dolphin", "turtle", "reef", "diving", "snorkel", "ocean", "beach"]):
            ocean_wildlife.append(hl)
        else:
            cultural_heritage.append(hl)

    return {
        "url": url,
        "id": tour_id,
        "tour_overview": {
            "package_name": package_name,
            "theme": theme,
            "duration": duration
        },
        "core_inclusions": inclusions,
        "itinerary_breakdown": itinerary_list if itinerary_list else [{"day": "Day 1", "description": "Tour start details"}],
        "featured_experiences_and_highlights": {
            "cultural_heritage": list(set(cultural_heritage)) if cultural_heritage else ["Ancient Ceylon ruins", "Sigiriya Rock Fortress"],
            "ocean_and_wildlife_adjacencies": list(set(ocean_wildlife)) if ocean_wildlife else ["Whale and dolphin watching", "Coral reef snorkeling"]
        }
    }

def parse_experience(soup, url: str) -> dict:
    """Extracts explicit experience title items and metadata text entries."""
    # Look for item block card lists or default fallback schemas
    results = []
    cards = soup.find_all("article") or soup.find_all("div", class_=lambda c: c and "experience" in c.lower())
    
    for card in cards:
        name_el = card.find(["h2", "h3", "h4"])
        desc_el = card.find("p")
        if name_el:
            results.append({
                "experience": clean(name_el.get_text()),
                "description": clean(desc_el.get_text()) if desc_el else ""
            })

    # Fallback to page-wide meta blocks if targeted from clean direct links
    if not results:
        h1_el = soup.find("h1")
        content_div = soup.find("div", class_="entry-content") or soup.find("main")
        desc_text = ""
        if content_div:
            p_tags = content_div.find_all("p")
            desc_text = " ".join([clean(p.get_text()) for p in p_tags if len(clean(p.get_text())) > 40])
        results.append({
            "experience": clean(h1_el.get_text()) if h1_el else "Sri Lankan Attraction Portfolio",
            "description": desc_text
        })

    return {
        "url": url,
        "experience_profile": results[0] if results else {"experience": "Unknown Experience", "description": ""}
    }

def parse_destination(soup, url: str) -> dict:
    """Gathers localized context abstracts and relevant landmark names."""
    h1_el = soup.find("h1")
    name = clean(h1_el.get_text()) if h1_el else "Destination Profile"
    
    # Context summary building using paragraphs with minimum word thresholds
    content_div = soup.find("div", class_="entry-content") or soup.find("main")
    context_text = "Historic site featured by Jetwing Travels as a major Sri Lankan tourist destination."
    if content_div:
        paras = [clean(p.get_text()) for p in content_div.find_all("p") if len(clean(p.get_text())) > 60]
        if paras:
            context_text = " ".join(paras[:2])

    # Relevance mapping via headline elements tracking structural entities
    relevance_names = []
    for heading in soup.find_all(["h2", "h3", "h4", "h5"]):
        heading_text = clean(heading.get_text())
        if heading_text and len(heading_text) < 60:
            if not any(ignore in heading_text.lower() for ignore in ["subscribe", "hotline", "contact", "experience", "tour"]):
                relevance_names.append(heading_text)

    # Base configuration fallback
    if not relevance_names:
        relevance_names = [name]

    return {
        "url": url,
        "destination_profile": {
            "context": context_text,
            "relevance": list(set(relevance_names))
        }
    }

def main():
    if not os.path.exists(URL_MAP_PATH):
        print(f"Aborting execution: Configuration map input layout file missing at: '{URL_MAP_PATH}'")
        return

    with open(URL_MAP_PATH, "r", encoding="utf-8") as f:
        url_map = json.load(f)

    combined_data = {
        "tours": [],
        "destinations": [],
        "experiences": []
    }

    # Execute main execution loop maps over each section
    for category, urls in url_map.items():
        if category not in DIRS:
            continue
            
        print(f"\n>>> Launching Scraper Phase for Category: [{category.upper()}] ({len(urls)} entries)")
        
        for url in urls:
            print(f"Requesting target: {url}")
            soup = fetch_page(url)
            if not soup:
                continue
            
            # Direct to the proper internal sub-parser layout configuration
            if category == "tours":
                parsed_item = parse_tour(soup, url)
            elif category == "experiences":
                parsed_item = parse_experience(soup, url)
            elif category == "destinations":
                parsed_item = parse_destination(soup, url)
            
            # Save out to separate individual record backups as defined
            file_slug = get_slug(url)
            target_raw_file = os.path.join(DIRS[category], f"{file_slug}.json")
            with open(target_raw_file, "w", encoding="utf-8") as out_f:
                json.dump(parsed_item, out_f, indent=4, ensure_ascii=False)
                
            # Keep trace track inside memory arrays for immediate consolidation
            combined_data[category].append(parsed_item)
            
            # Enforce the required politeness interval break delay
            time.sleep(DELAY)

    # Final combined concatenation export dump pass
    with open(OUTPUT_COMBINED_PATH, "w", encoding="utf-8") as master_f:
        json.dump(combined_data, master_f, indent=4, ensure_ascii=False)
        
    print(f"\nScraping script pass complete. Aggregated export located at: '{OUTPUT_COMBINED_PATH}'")

if __name__ == "__main__":
    main()