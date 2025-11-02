# LinkedIn Profile Matcher, Name + Face

**Objective:** Given a person’s full name and one face photo, the system finds public LinkedIn profile links, downloads each candidate’s profile photo, compares faces with an AI model, and returns the best match.\
**Primary rule:** a profile is valid only if the full name matches exactly and it has the highest image similarity among results.\
**Bonus:** a fallback fuzzy name match is included (RapidFuzz).

## 1) System overview

**Workflow:**

- **Make JSON inputs** — one JSON per source image (name inferred from filename).  
  `utils/make_persons_jsons.py`

### There are two flows for scraping images:
**Google image scraping flow:**
- **Search & collect candidates** — opens Google images results for `"Full Name site:linkedin.com/in"`, extract profile URLs, pictures and names
  `scraper/scrape_from_GImages.py`

**ALTERNATIVE: Full resolution scraping flow**
 - Login — Connects to LinkedIn and saves a `login_state.json` for LinkedIn session reuse.  
  `scraper/login_headless.py`
 - Search & collect candidates — opens DuckDuckGo HTML results for `"Full Name site:linkedin.com/in"`, extract profile URLs  
  `scraper/scrape_links.py`
  - Download profile images — visits each LinkedIn profile, opens the photo modal, and saves the full-size image (or marks `no_image`).  
  `scraper/scrape_profile_photos_simple.py`

### Then:
- **Match** — for each candidate, computes face similarity vs the source image, then picks the highest-score candidate and checks if it's the same name.  
  If the name is close output says `"Probable Match(Fuzzy Name)"`  
  `matcher.py`

- **Output** — aggregates a compact JSON with the final results.  
  `main.py → output.json`

**Key components**

- `main.py` — Orchestrates the full pipeline.
- `scraper/` — Login / search / photo download via Playwright.
- `face_recognize/face_compare.py` — Face similarity via DeepFace (ArcFace).
- `utils/json_store.py` — Appends candidates & stores photo paths / face metrics.
- `utils/name_match.py` — Exact & fuzzy name checks (RapidFuzz).

**Each component can be tested independently and replaced if necessary**

---

## 2) AI model & similarity scoring

**Model:** DeepFace with ArcFace

**Distance:** cosine distance (lower is better)

**Score mapping:** distance → sigmoid similarity in \[0, 1]:

sigmoid = 1 / (1 + exp(k*(distance - threshold)))

We return a dict like:
```json
{
  "distance": 0.28,
  "threshold": 0.30,
  "sigmoid": 0.63,
  "verified": true,
  "model": "ArcFace",
  "detector": "retinaface"
}
```

**Why sigmoid?** It converts “distance vs model threshold” into a stable, comparable 0–1 score across candidates.

## 3) Matching logic (name + image)

**For each candidate with a usable profile photo:**

- Compute face similarity once.
- Pick the candidate with max `face.sigmoid`.
- **Primary rule:** accept only if exact name match **AND** it’s the top image match.
- **Bonus fallback:** if the top image candidate is not an exact match but name similarity ≥ 92 (RapidFuzz `token_sort_ratio`), we label it  
  **"Probable Match (Fuzzy Name)".**

## 4) Setup & Limitations

**Requirements (Python 3.11+)**

```bash
pip install -r requirements.txt
playwright install
```
**Credentials**

Create a **`.env`** (only necessary in full-picture mode)

```dotenv
LINKEDIN_EMAIL=you@example.com
LINKEDIN_PASSWORD=********
```

Since LinkedIn has rate limitations and really strict research,
(For example, missing one letter and the user is not foundable anymore)
we use Google images or duckduckGo HTML search since it rarely asks for CAPTCHA solving.

## Run :
```python main.py --src-dir SrcDir```

### Options (what each flag adds/changes):
General\
```--src-dir PATH``` — where your source face images live. Default: Source

```--persons-dir PATH``` — where per-person JSONs are written/loaded. Default: Persons_JSONS

```--output PATH``` — write final aggregated results here. Default: output.json


```--headless``` — run the browser headless (omit for a visible window).

Default flow - Google Images scraping\
```--gimages-limit INT``` — max profiles to collect per person. Default: 10

Full-pictures flow - Linkedin login + max-size photos\
```--full-pictures``` — switch to the LinkedIn flow (requires login).

```--email EMAIL``` — LinkedIn login; falls back to LINKEDIN_EMAIL env var.

```--password PASS``` — LinkedIn password; falls back to LINKEDIN_PASSWORD env var.

```--max-pages INT``` — how many result pages to crawl. Default: 1

```--scrape-delay FLOAT``` — delay between search page actions (seconds). Default: 1.0

```--photos-delay FLOAT``` — delay between photo grabs (seconds). Default: 0.9

```--state PATH``` — Chromium/LinkedIn session state file. Default: login_state.json


## 5) LLM disclosure

I used an LLM to speed up routine coding tasks, drafting boilerplate, refining regex/selectors, tidying function signatures, and polishing docstrings.\
All core architecture, matching logic, and integration choices are my own, and the code was implemented and tested locally by me.

## 6) Repository layout
```text
.
├── main.py
├── requirements.txt
├── scraper/
│   ├── login_headless.py
│   ├── scrape_links.py
│   ├── scrape_profile_photos_simple.py
│   └── scrape_from_GImages.py
├── face_recognize/
│   └── face_compare.py
├── utils/
│   ├── img_load.py
│   ├── json_store.py
│   ├── make_persons_jsons.py
│   └── name_match.py
├── Persons_JSONS/
└── Persons_photos/
```

## 7)Notes

The Google image scraping flow has been added and set as the default for a few practical reasons:

- Signing into a LinkedIn account adds traceability to all the searches.
- At scale, opening each LinkedIn profile is slow and can trigger botting/ban risk since it's not allowed by LinkedIn.
- This flow is simpler and faster overall.
- The thumbnail size is good enough to tell if it’s the right person for our matcher.
- Images are already base64 in the page, so we decode them directly, no extra download step.
- No need for an `.env` or managing LinkedIn credentials.

