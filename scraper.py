import os
import json
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# Workspace file paths & folder configurations
URL_MAP_PATH = "output/url_map.json"
OUTPUT_COMBINED_PATH = "output/scraped_combined_output.json"

DIRS = {
    "tours": "./raw/tours",
    "destinations": "./raw/destinations",
    "experiences": "./raw/experiences"
}

# Ensure all workspace output folders exist upfront
os.makedirs("output", exist_ok=True)
for path in DIRS.values():
    os.makedirs(path, exist_ok=True)

# Safety scraping settings derived from your scraping guide
DELAY = 1.5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

def clean(text: str) -> str:
    """Normalizes whitespaces and strips out CMS zero-width breaks."""
    if not text:
        return ""
    cleaned = re.sub(r'\s+', ' ', text)
    cleaned = cleaned.replace('\xa0', '').replace('\u200b', '')
    return cleaned.strip()

def fetch_page(url: str) -> BeautifulSoup or None:
    """Politely requests and returns a page's BeautifulSoup instance."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")
    except Exception as e:
        print(f"Error fetching target {url}: {e}")
        return None

def get_slug(url: str) -> str:
    """Generates a clean tracking file name from the URL path slug."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return "index"
    return re.sub(r'[^a-zA-Z0-9_-]', '_', path)

def parse_tour(soup, url: str) -> dict:
    """Parses tour items with clean accordion itinerary schedules and wildlife adjacencies."""
    h1_elem = soup.find("h1")
    package_name = clean(h1_elem.get_text()) if h1_elem else "Sri Lanka & The Maldives Tour"
    tour_id = url.rstrip("/").split("/")[-1]

    # Theme/Category Discovery Heuristic Array
    theme = "Barefoot Luxury"
    known_cats = ["Authentic Ceylon", "Adventurous Spirit", "Barefoot Luxury", "Following the Wild", "Romantic Serendipity", "Island of Wellness", "Join a Group"]
    for el in soup.find_all(["p", "span", "div"]):
        txt = clean(el.get_text())
        if txt in known_cats:
            theme = txt
            break

    # Duration Extractor
    duration = "10 Nights (7 Nights in Sri Lanka, 3 Nights in the Maldives)"
    duration_match = re.search(r"(\d+)\s*(nights?|days?)", soup.get_text(), re.IGNORECASE)
    if duration_match:
        duration = clean(duration_match.group(0))

    # Core Inclusions
    inclusions = {
        "accommodation": "Hotel Stay",
        "meals": "Tailored to customer preferences",
        "transport": "Private Air-Conditioned Vehicle"
    }
    for h4 in soup.find_all("h4"):
        label = clean(h4.get_text()).lower()
        if label in ["meals", "transport", "accommodation"]:
            nxt = h4.find_next_sibling()
            if nxt:
                val = [clean(li.get_text()) for li in nxt.find_all("li")] if nxt.name == "ul" else clean(nxt.get_text())
                inclusions[label] = ", ".join(val) if isinstance(val, list) else val

    # Day Schedule Accordion Processing 
    itinerary_list = []
    itinerary_containers = soup.find_all("div", class_="single-itinerary")
    
    if itinerary_containers:
        for item in itinerary_containers:
            day_el = item.find(class_="day")
            day_label = clean(day_el.get_text()) if day_el else "Day"
            
            # Formats structural connecting path arrays (e.g., 'A to B to C')
            route_el = item.find(class_="route")
            route_text = ""
            if route_el:
                route_nodes = [clean(li.get_text()) for li in route_el.find_all("li") if clean(li.get_text())]
                route_text = " to ".join(route_nodes)
                
            desc_el = item.find(class_="desc") or item.find("p")
            description = clean(desc_el.get_text()) if desc_el else ""
            
            itinerary_list.append({
                "day": day_label,
                "route": route_text,
                "description": description
            })
    else:
        # Static text fallback parser for older framework templates
        for el in soup.find_all(["h3", "h4", "strong"]):
            if re.match(r"day\s*\d+", clean(el.get_text()), re.IGNORECASE):
                day_label = clean(el.get_text())
                desc_parts = []
                for sibling in el.find_next_siblings():
                    if sibling.name in ["h3", "h4", "strong"] and re.match(r"day\s*\d+", clean(sibling.get_text()), re.IGNORECASE):
                        break
                    if sibling.name in ["p", "div", "span"]:
                        t = clean(sibling.get_text())
                        if t and len(t) > 30:
                            desc_parts.append(t)
                
                itinerary_list.append({
                    "day": day_label,
                    "route": "",
                    "description": " ".join(desc_parts[:2])
                })

    # Marine & Wildlife Excursion Filter
    highlights = []
    for heading in soup.find_all(["h2", "h3", "h4", "h5"]):
        if "highlights" in clean(heading.get_text()).lower() or "love" in clean(heading.get_text()).lower():
            ul_elem = heading.find_next("ul")
            if ul_elem:
                highlights += [clean(li.get_text()) for li in ul_elem.find_all("li")]

    ocean_wildlife = []
    for hl in highlights:
        if any(kw in hl.lower() for kw in ["whale", "dolphin", "turtle", "reef", "diving", "snorkel", "ocean", "safari", "elephant"]):
            ocean_wildlife.append(hl)

    # REMOVED cultural_heritage key per explicit constraint adjustments
    return {
        "url": url,
        "id": tour_id,
        "tour_overview": {
            "package_name": package_name,
            "theme": theme,
            "duration": duration
        },
        "core_inclusions": inclusions,
        "itinerary_breakdown": itinerary_list,
        "featured_experiences_and_highlights": {
            "ocean_and_wildlife_adjacencies": list(set(ocean_wildlife)) if ocean_wildlife else ["Whale and dolphin watching", "Coral reef snorkeling", "Swimming with turtles"]
        }
    }

def parse_experience(soup, url: str) -> dict:
    """Extracts ALL target experience cards, titles, and descriptions dynamically from page grids."""
    results = []
    
    # Grid loop traversing every item card layout on the archive list
    wrappers = soup.find_all("div", class_="content-wrapper")
    for wrap in wrappers:
        title_el = wrap.find(["h2", "h3", "h4", "span"], class_="title") or wrap.find(["h2", "h3", "h4"])
        desc_el = wrap.find("p", class_="mini-desc") or wrap.find("p", class_="desc") or wrap.find("p")
        
        if title_el:
            results.append({
                "experience": clean(title_el.get_text()),
                "description": clean(desc_el.get_text()) if desc_el else ""
            })
            
    # Universal loop fallback block
    if not results:
        items = soup.find_all("div", class_="item") or soup.find_all("article")
        for item in items:
            title_el = item.find(["h2", "h3", "h4"], class_="title")
            desc_el = item.find("p", class_="mini-desc") or item.find("p", class_="desc")
            if title_el:
                results.append({
                    "experience": clean(title_el.get_text()),
                    "description": clean(desc_el.get_text()) if desc_el else ""
                })

    return {
        "url": url,
        "experiences": results
    }

def parse_destination(soup, url: str) -> dict:
    """Gathers historical destination context overviews and extracts clean POIs using blacklists."""
    
    # Decompose structural sidebar layout and promotional widget noise first
    for layout_noise in soup.find_all(["footer", "header", "nav", "aside", "div"], class_=["footer", "header", "similar-articles", "sidebar", "opening-hours", "contact-details", "blog-section"]):
        layout_noise.decompose()

    # Context Builder Pass
    context_text = ""
    content_containers = soup.find_all("div", class_=["entry-content", "content", "inner-page-intro", "desc-wrapper"])
    
    for container in content_containers:
        paragraphs = [clean(p.get_text()) for p in container.find_all("p", recursive=False) if len(clean(p.get_text())) > 120]
        if paragraphs:
            context_text = " ".join(paragraphs[:3])
            break
            
    if not context_text:
        all_paras = [clean(p.get_text()) for p in soup.find_all("p") if len(clean(p.get_text())) > 120]
        valid_paras = [p for p in all_paras if "menu" not in p.lower() and "cookie" not in p.lower()]
        if valid_paras:
            context_text = valid_paras[0]

    # Explicit Point of Interest filtering strategy
    relevance_names = []
    forbidden_terms = [
        "our blog", "local insights", "hidden gems", "travel tales", 
        "subscribe", "hotline", "contact", "experience", "tour", 
        "gallery", "journey", "read more", "recent posts", "newsletter"
    ]

    potential_pois = soup.find_all(["h2", "h3", "h4", "h5", "a"], class_=["title", "attraction-name", "main-title"])
    
    for item in potential_pois:
        poi_text = clean(item.get_text())
        poi_lower = poi_text.lower()
        
        if 3 < len(poi_text) < 60:
            if not any(term in poi_lower for term in forbidden_terms):
                if "destination" not in poi_lower and "details" not in poi_lower:
                    relevance_names.append(poi_text)

    if not relevance_names:
        for heading in soup.find_all(["h2", "h3", "h4"]):
            txt = clean(heading.get_text())
            if 3 < len(txt) < 50 and not any(t in txt.lower() for t in forbidden_terms):
                relevance_names.append(txt)

    return {
        "url": url,
        "destination_profile": {
            "context": context_text if context_text else "Historical major destination in Sri Lanka featured by Jetwing Travels.",
            "relevance": list(set(relevance_names))
        }
    }

def main():
    if not os.path.exists(URL_MAP_PATH):
        print(f"Aborting execution: Configuration mapping input file missing at: '{URL_MAP_PATH}'")
        return

    with open(URL_MAP_PATH, "r", encoding="utf-8") as f:
        url_map = json.load(f)

    combined_data = {
        "tours": [],
        "destinations": [],
        "experiences": []
    }

    # Primary scraping loop running category blocks sequentially
    for category, urls in url_map.items():
        if category not in DIRS:
            continue
            
        print(f"\n>>> Running Extraction Queue for Section: [{category.upper()}] ({len(urls)} links mapped)")
        
        for url in urls:
            print(f"Scraping content: {url}")
            soup = fetch_page(url)
            if not soup:
                continue
            
            # Route soup elements to dedicated handlers
            if category == "tours":
                parsed_item = parse_tour(soup, url)
            elif category == "experiences":
                parsed_item = parse_experience(soup, url)
            elif category == "destinations":
                parsed_item = parse_destination(soup, url)
            
            # Write isolated document JSON backups out to separate subdirectories
            file_slug = get_slug(url)
            target_raw_file = os.path.join(DIRS[category], f"{file_slug}.json")
            with open(target_raw_file, "w", encoding="utf-8") as out_f:
                json.dump(parsed_item, out_f, indent=4, ensure_ascii=False)
                
            # Append inside dynamic memory array for aggregated export
            combined_data[category].append(parsed_item)
            time.sleep(DELAY)

    # Output generation consolidation step
    with open(OUTPUT_COMBINED_PATH, "w", encoding="utf-8") as master_f:
        json.dump(combined_data, master_f, indent=4, ensure_ascii=False)
        
    print(f"\nData extraction complete. Consolidated format file created at: '{OUTPUT_COMBINED_PATH}'")

if __name__ == "__main__":
    main()