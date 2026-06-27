# Fortune 500 Internship Radar 🎯

A web scraper that watches Fortune 500 / large-employer career boards for
**internships**, verifies each one is genuinely open and applyable, and
announces it to a **Discord** server with the key details: release date,
deadline, requirements, locations, and salary.

It does both things you asked for:

- **Finds internships as they open** — each run detects postings that are new
  since the last run and announces them immediately ("🆕 Just opened").
- **Catches the ones already open** — on first run (or when you add a company)
  it backfills internships that are open right now but haven't closed yet
  ("📌 Open now").

Every posting is announced **once** (tracked in a local SQLite store), and the
apply link is **verified** before it's posted so you never get a dead listing.

---

## How it works

```
companies.yaml ──▶ source adapters ──▶ parsing/normalize ──▶ dedup store
                  (Greenhouse, Lever,    (release date,        (announce once)
                   Ashby, Workday)        deadline, salary,          │
                                          requirements, ...)         ▼
                                                            verify applyable
                                                                    │
                                                                    ▼
                                                            Discord webhook
```

| Component | File |
|-----------|------|
| Normalized posting model | `fortune_scraper/models.py` |
| Field extraction (salary, deadline, requirements, internship detection) | `fortune_scraper/parsing.py` |
| ATS adapters | `fortune_scraper/sources/{greenhouse,lever,ashby,workday}.py` |
| "Is it actually applyable?" check | `fortune_scraper/verifier.py` |
| Discord embeds | `fortune_scraper/discord_notifier.py` |
| Dedup / closed-tracking store | `fortune_scraper/store.py` |
| Orchestration | `fortune_scraper/pipeline.py` |
| CLI | `fortune_scraper/cli.py` |

### Supported ATS platforms

Most large employers run one of these, and all four expose a public JSON feed:

- **Greenhouse** — `boards.greenhouse.io/<token>`
- **Lever** — `jobs.lever.co/<token>`
- **Ashby** — `jobs.ashbyhq.com/<token>`
- **Workday** — `<tenant>.<dc>.myworkdayjobs.com/...` (the most common among the
  Fortune 500)

Add more companies by editing [`data/companies.yaml`](data/companies.yaml) —
that file documents exactly how to find each company's slug.

---

## Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure your Discord webhook
cp .env.example .env
#   then edit .env and set DISCORD_WEBHOOK_URL
#   (Discord: Server Settings → Integrations → Webhooks → New Webhook → Copy URL)

# 3. Try it without posting anything
python main.py run --dry-run

# 4. Do it for real (announces to Discord)
python main.py run

# 5. Run continuously, scanning every 15 minutes
python main.py watch --interval 900
```

### Commands

| Command | What it does |
|---------|--------------|
| `python main.py run` | One scrape pass, then exit. |
| `python main.py watch --interval 900` | Loop forever, scanning on an interval. |
| `python main.py stats` | Print dedup-store statistics. |
| `--dry-run` | Scrape + log what *would* be announced, post nothing. |
| `-v` | Verbose logging. |

---

## What gets announced

Each internship becomes a rich Discord embed:

> **Software Engineering Intern, Summer 2025**
> **Stripe** — 🆕 Just opened
>
> 📍 Location: New York, NY (+1 more)  💰 Salary: $45–$55/hr
> 📅 Released: Jan 5, 2025          ⏰ Deadline: Mar 1, 2025
> ✅ Requirements: • Pursuing a CS degree • Python …
> *Apply now ↗* (links straight to the verified application page)

Salary, deadline, and requirements are parsed from the posting when the ATS
doesn't expose them as structured fields, so they show up "best effort" — if a
company genuinely doesn't list a salary, the field reads *Not listed* rather
than guessing.

---

## Configuration

Runtime knobs live in [`config.yaml`](config.yaml); secrets live in `.env`.

| Setting | Default | Meaning |
|---------|---------|---------|
| `verify_applyable` | `true` | Check the apply URL loads and isn't closed before posting. |
| `announce_backfill` | `true` | Announce already-open internships on first sight, not just new ones. |
| `max_backfill_per_run` | `25` | Cap on how many *already-open* postings a single run will announce (new ones are never capped). |
| `only_new_since_days` | `null` | Ignore postings older than N days. |
| `request_delay_seconds` | `0.5` | Politeness delay between companies. |

Any of these can be overridden via environment variables (see `.env.example`).

---

## Running on a schedule (GitHub Actions)

[`.github/workflows/scrape.yml`](.github/workflows/scrape.yml) runs the scraper
every 30 minutes and caches the dedup DB between runs. To use it:

1. In your repo: **Settings → Secrets and variables → Actions → New repository
   secret** → name `DISCORD_WEBHOOK_URL`, paste your webhook URL.
2. Enable Actions. New internships will start flowing into Discord automatically.

---

## "Is it actually applyable?"

Before announcing, the verifier (`fortune_scraper/verifier.py`):

1. Confirms there is a real `http(s)` application URL.
2. Fetches it (following redirects) and requires a 2xx response — `404`/`410`
   means the posting is gone.
3. Scans the page for closed markers ("no longer accepting applications",
   "position has been filled", etc.).

If verification fails, the posting is **skipped this cycle** and retried next
time rather than being permanently discarded — so a transient blip never costs
you a real opening. You can disable the network check with
`verify_applyable: false` (the URL-validity check always runs).

---

## Tests

```bash
pip install pytest
python -m pytest -q
```

The suite covers internship detection, salary/deadline/requirement parsing,
every ATS adapter (with canned API fixtures), dedup behavior, the
applyability check, and closed-posting reconciliation — all without touching
the network.

---

## Notes & limitations

- The starter company list in `data/companies.yaml` is a representative set;
  **verify each slug** against the live careers page and add the employers you
  care about. Slugs occasionally change.
- These public ATS feeds are not officially documented APIs. Be polite: the
  default keeps a delay between companies and retries with backoff.
- Salary/deadline parsing is heuristic. When a company exposes structured comp
  fields (Lever `salaryRange`, Ashby `compensation`, Greenhouse pay metadata)
  those are used directly; otherwise the text is parsed best-effort.
