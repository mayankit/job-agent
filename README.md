# AI Job Application Agent

An autonomous agent that reads your resume, searches multiple job portals, validates roles against your seniority and TC floor, generates personalized cover letters via Claude, and submits applications — across LinkedIn Easy Apply and six major ATS platforms.

**Zero personal data is hardcoded.** Everything is derived at runtime from your documents.

---

## How it works

```
Your resume ──► Claude extracts profile ──► Stored in profile.json (local only)
                                                       │
               Job portals searched ◄──── Your search config (titles, level, TC floor)
               (LinkedIn, Indeed, Dice…)
                          │
               Per-job pipeline:
                 1. Skip if already applied
                 2. Skip if JD contains "no sponsorship" language
                 3. Validate seniority via levels.fyi (cached 7 days)
                 4. Score domain relevance
                 5. Research company → generate cover letter via Claude
                 6. Fill application form (semantic field detection)
                 7. Submit + screenshot every step
                 8. Log to SQLite + evidence folder
```

---

## Supported job portals

| Portal | What it does |
|--------|-------------|
| **LinkedIn** | Easy Apply + links to external ATS. Recommended — highest coverage. |
| **Indeed** | Large general job board. External apply only. |
| **Dice** | Tech-focused board. Good for engineering roles. |
| **Wellfound** | Startup and growth-stage companies. |
| **Glassdoor** | Job listings with salary data (external apply). |
| **Levels.fyi** | TC-verified senior/staff roles. |

You select which portals to search during `--setup`. You can add more later by re-running `--setup`.

## Supported ATS platforms (where companies host applications)

Workday · Greenhouse · Lever · iCIMS · Taleo · SmartRecruiters · Generic fallback (any other ATS)

---

## Requirements

- Python 3.11+
- Google Chrome (Chromium is installed automatically by Playwright)
- Anthropic API key — get one at https://console.anthropic.com/

---

## First-time setup

### Step 1 — Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/job-agent.git
cd job-agent

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium

# Install the pre-commit security hook (blocks accidental secret commits)
bash install_hooks.sh
```

### Step 2 — Configure your API key

```bash
cp .env.example .env
```

Open `.env` in any text editor and set:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

That's the only thing you need to set manually. `ENCRYPTION_KEY` is auto-generated on first run.

### Step 3 — Add your resume

Drop your resume (PDF or DOCX) into:

```
my_documents/resume/
```

Optionally, drop STAR story documents (PDF, DOCX, MD, or TXT) into:

```
my_documents/stories/
```

Stories give the agent real career examples and metrics to use in cover letters. A "brag doc" or any document with 3–5 achievement stories works well.

### Step 4 — Run setup

```bash
python3 main.py --setup
```

The wizard will:

1. Parse your resume with Claude to build a structured profile
2. Ask for your job search preferences:
   - Target job titles (e.g. `Principal Engineer, Staff Engineer`)
   - Your target seniority level (e.g. `Amazon L7, Google L7`)
   - Minimum total compensation (used to filter via levels.fyi)
   - Location preference
   - Priority domains/industries (optional)
3. Ask you to pick which job portals to search
4. Ask for two email addresses:
   - **LinkedIn email** — to log in and search LinkedIn
   - **Application email** — used when creating accounts on company ATS portals (Workday, Greenhouse, etc.) and filling out application forms. Can be the same as LinkedIn or a dedicated job-search inbox.

All credentials are encrypted with Fernet and stored in `passwords.enc`. They are never written to any log, screenshot, or the database.

### Step 5 — Dry run first

```bash
python3 main.py --dry-run
```

This searches and filters jobs exactly as the real run does, but never opens a form or clicks Apply. Review the output — check that the job titles, companies, and seniority level look right.

### Step 6 — Run the agent

```bash
python3 main.py
```

A Chrome window will open. The agent logs in to LinkedIn, searches across your selected portals, and begins applying. You can watch it work. If a CAPTCHA appears, the agent pauses and asks you to solve it.

---

## Daily usage

```bash
# Apply to up to 5 jobs today
python3 main.py --max 5

# Only look at Google
python3 main.py --company Google

# Only search for "Staff Engineer" today
python3 main.py --title "Staff Engineer"

# Combine: 3 applications at Meta for Principal Engineer
python3 main.py --company Meta --title "Principal Engineer" --max 3

# See what's been applied to
python3 main.py --report

# Open the web dashboard
python3 main.py --ui
```

---

## CLI reference

| Command | Description |
|---------|-------------|
| `python3 main.py` | Full pipeline — search all portals and apply |
| `python3 main.py --setup` | First-run setup (profile + search config) |
| `python3 main.py --refresh-profile` | Re-parse resume/stories, overwrite profile |
| `python3 main.py --dry-run` | Search + filter, print matches, never apply |
| `python3 main.py --max N` | Cap at N applications this session |
| `python3 main.py --title "..."` | Override to search for one title only |
| `python3 main.py --company X` | Target one company only |
| `python3 main.py --report` | Print application history in terminal |
| `python3 main.py --export out.csv` | Export all applications to CSV |
| `python3 main.py --ui` | Launch web dashboard at http://localhost:8080 |
| `python3 main.py -v` | Verbose logging (debug level) |
| `python3 reveal_password.py` | View all stored portal passwords |
| `python3 reveal_password.py --master` | View master password only |
| `python3 reveal_password.py --site workday_google` | View one site's password |

---

## Web dashboard

```bash
python3 main.py --ui
# Opens http://localhost:8080 automatically
```

The dashboard shows:

- **Stats banner** — total / applied / failed / skipped counts
- **Filterable table** — filter by status, search by company or title, export CSV
- **Per-application detail page**:
  - Full rendered cover letter with copy + download buttons
  - Every form field submitted and its value
  - Screenshots of every step (click to zoom)
  - Job description text
  - Company research used to write the cover letter

---

## Evidence folders

Every application leaves a complete evidence folder:

```
applications/
└── Google/
    └── 2026-03-18_143022_12345678/
        ├── metadata.json           ← Status, TC, ATS platform, links
        ├── cover_letter.md         ← What was submitted
        ├── job_description.txt     ← Full JD scraped
        ├── company_research.txt    ← What Claude used to write the cover letter
        ├── form_data.json          ← Every field label + submitted value
        ├── screenshots/
        │   ├── 01_job_listing.png
        │   ├── 03_form_step_1.png
        │   └── 99_confirmation.png
        └── run.log                 ← Log output for this application only
```

---

## Updating your resume

```bash
# Replace the file in my_documents/resume/ then:
python3 main.py --refresh-profile
```

---

## Passwords and security

The agent creates one master password (24 chars, random) and reuses it across all ATS portals where it creates accounts.

```bash
python3 reveal_password.py          # Show all sites + decrypted passwords
python3 reveal_password.py --master # Show master password
```

The encryption key lives in `.env` as `ENCRYPTION_KEY`. It is auto-generated on first run and appended to `.env` automatically. Never commit `.env`.

---

## Pre-commit security hook

The repo ships with a pre-commit hook that blocks commits containing:

- API keys or secrets (`sk-ant-...`, `ENCRYPTION_KEY=...`)
- Resume files, profile.json, search_config.json
- `.env` file
- Application evidence folders / database
- Log files

To install it (done automatically by `bash install_hooks.sh`):

```bash
bash install_hooks.sh
```

If you ever need to bypass it (use with extreme caution):

```bash
git commit --no-verify
```

---

## FAQ

**Will it apply without me watching?**
Yes. Use `--dry-run` first to verify the job filter. The evidence folder is created before any form interaction, so you can review what was found.

**What if a CAPTCHA or 2FA appears?**
The agent pauses, prints clear instructions in the terminal, and waits for you to complete it in the browser. Then it continues automatically.

**What email do companies see?**
Your **application email** — set during `--setup`. Use a dedicated job-search address (e.g. `yourname.jobs@gmail.com`) to keep your inbox organized.

**Does it apply to the same job twice?**
No. Every `job_id` is tracked in `applications.db`. The agent checks before doing any work.

**What if a portal changes its HTML?**
The form filler uses semantic label detection (not hardcoded CSS selectors) so it adapts to most layout changes automatically. For known ATS platforms, there are dedicated handlers that use stable data-automation attributes.

**Is my resume sent anywhere?**
Only to Anthropic's API for profile extraction and cover letter generation. The text is sent as part of a Claude API call — the same API you're paying for with your key.

**What ATS platforms are fully supported?**
Workday, Greenhouse, Lever, iCIMS, Taleo, SmartRecruiters. Any other ATS is handled by the generic fallback handler which uses semantic form detection.

---

## Project structure

```
job-agent/
├── my_documents/           ← Your files (read-only to agent, never committed)
│   ├── README.txt
│   ├── resume/             ← Drop resume here
│   ├── stories/            ← Drop STAR story docs here (optional)
│   ├── profile.json        ← Auto-generated (gitignored)
│   └── search_config.json  ← Auto-generated (gitignored)
├── applications/           ← Evidence folders (gitignored)
├── agent/
│   ├── profile_extractor.py   LLM resume + story parser
│   ├── profile_store.py       Load/save profile.json
│   ├── form_filler.py         Semantic form-filling engine
│   ├── job_searcher.py        Multi-portal job search
│   ├── level_checker.py       levels.fyi TC validation
│   ├── cover_letter.py        Company research + cover letter
│   ├── application_runner.py  Easy Apply + external flow
│   ├── evidence_store.py      Folder / screenshot management
│   ├── password_manager.py    Fernet encryption
│   └── application_tracker.py SQLite logger
├── ats_handlers/
│   ├── base.py               Abstract base class
│   ├── generic.py            Fallback for any ATS
│   ├── workday.py
│   ├── greenhouse.py
│   ├── lever.py
│   ├── icims.py
│   ├── taleo.py
│   └── smartrecruiters.py
├── dashboard/
│   ├── app.py               FastAPI server
│   ├── templates/           Jinja2 HTML
│   └── static/              CSS
├── hooks/
│   └── pre-commit           Security scan hook (source)
├── main.py                  CLI entry point
├── config.py                All paths + settings
├── reveal_password.py       Decrypt stored passwords
├── install_hooks.sh         Installs git hooks
├── requirements.txt
├── .env.example             Template — copy to .env
└── .gitignore               Covers all personal data
```
