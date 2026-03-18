#!/usr/bin/env python3
"""
main.py — AI Job Application Agent CLI

Usage:
  python main.py                           # Full pipeline (search + apply)
  python main.py --setup                   # First-run: extract profile + configure search
  python main.py --setup-linkedin          # Populate LinkedIn profile from profile.json
  python main.py --refresh-profile         # Re-parse documents, overwrite profile.json
  python main.py --dry-run                 # Search + filter jobs, print matches, NO applying
  python main.py --max 10                  # Cap at N applications this session
  python main.py --title "Staff Engineer"  # Override search to this title only
  python main.py --company Google          # Target this company only
  python main.py --report                  # Print application summary in terminal
  python main.py --export out.csv          # Export applications to CSV
  python main.py --ui                      # Launch dashboard at http://localhost:8080
"""
import argparse
import asyncio
import json
import logging
import os
import random
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import config
from agent import (
    application_tracker,
    cover_letter as cover_letter_module,
    evidence_store,
    level_checker,
    password_manager,
    profile_extractor,
    profile_store,
)
from agent.job_searcher import (
    fetch_job_descriptions,
    has_no_sponsorship_language,
    login_linkedin,
    score_domain_relevance,
    search_all_portals,
)
from agent.job_deduplicator import canonical_key as _canonical_key_for
from agent.application_runner import run_easy_apply, run_external_apply

# ──────────────────────────────────────────────
# Logging setup
# ──────────────────────────────────────────────

def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(str(config.LOG_FILE)))
    except Exception:
        pass
    logging.basicConfig(level=level, format=fmt, handlers=handlers)


logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Setup flow
# ──────────────────────────────────────────────

def _print_welcome() -> None:
    print("""
┌─────────────────────────────────────────────────────────┐
│  Welcome to AI Job Application Agent                     │
│                                                          │
│  To get started, add your files:                         │
│                                                          │
│  1. Drop your resume (PDF or DOCX) into:                 │
│       my_documents/resume/                               │
│                                                          │
│  2. (Optional) Drop any STAR story documents into:       │
│       my_documents/stories/                              │
│     These help generate richer, more personal cover      │
│     letters with real examples from your career.         │
│                                                          │
│  3. Run: python main.py --setup                          │
│     to extract your profile and configure your search.   │
└─────────────────────────────────────────────────────────┘
""")


def _prompt(question: str, default: str = "") -> str:
    if default:
        prompt_str = f"{question} [{default}]: "
    else:
        prompt_str = f"{question}: "
    val = input(prompt_str).strip()
    return val if val else default


def run_setup(refresh: bool = False) -> None:
    """Interactive first-run setup: extract profile + configure search."""
    config.ensure_dirs()

    # Check for resume
    resume_files = list(config.RESUME_DIR.glob("*"))
    supported_resume = [f for f in resume_files if f.suffix.lower() in (".pdf", ".docx", ".doc")]
    if not supported_resume:
        _print_welcome()
        print("No resume found. Please add your resume to my_documents/resume/ and re-run.")
        sys.exit(0)

    if not refresh and profile_store.profile_exists():
        print("Profile already exists. Use --refresh-profile to re-parse documents.")
        _configure_search_interactively()
        return

    print("\n📄 Extracting profile from your documents...")
    try:
        extracted = profile_extractor.extract_all()
        profile = extracted.get("profile", {})
        print(f"✓ Profile extracted for: {profile.get('full_name', 'Unknown')}")
        print(f"  Current role: {profile.get('current_title')} at {profile.get('current_company')}")
        print(f"  Experience: {profile.get('years_of_experience')} years")
        if extracted.get("stories"):
            print(f"  Stories extracted: {len(extracted['stories'])}")
    except Exception as exc:
        logger.error("Profile extraction failed: %s", exc)
        print(f"\n✗ Failed to extract profile: {exc}")
        sys.exit(1)

    search_config = _configure_search_interactively()
    profile_store.save_profile(extracted, search_config=search_config)
    print("\n✓ Profile saved to my_documents/profile.json")
    print("✓ Ready to run!\n")
    print("Next steps:")
    print("  python main.py --dry-run      # See matching jobs without applying")
    print("  python main.py                # Run the full agent")


_PORTAL_DESCRIPTIONS = {
    "linkedin":   "LinkedIn        — Easy Apply + external ATS links (recommended)",
    "indeed":     "Indeed          — Large job board, mostly external apply",
    "glassdoor":  "Glassdoor       — Job listings with salary data",
    "dice":       "Dice            — Tech-focused job board",
    "wellfound":  "Wellfound       — Startup and growth-stage companies",
    "levels_fyi": "Levels.fyi Jobs — TC-verified senior/staff roles",
}

_ALL_PORTALS = list(_PORTAL_DESCRIPTIONS.keys())


def _select_portals() -> list[str]:
    print("\n── Job Portals ───────────────────────────────────────────────\n")
    print("Which job portals should the agent search?")
    print("(Enter comma-separated numbers, e.g. 1,2 — press Enter for LinkedIn only)\n")
    for i, key in enumerate(_ALL_PORTALS, 1):
        desc = _PORTAL_DESCRIPTIONS[key]
        print(f"  {i}. {desc}")
    print()

    selection_raw = _prompt("Your selection", "1")
    selected: list[str] = []
    for part in selection_raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(_ALL_PORTALS):
                selected.append(_ALL_PORTALS[idx])
        elif part.lower() in _ALL_PORTALS:
            selected.append(part.lower())

    if not selected:
        selected = ["linkedin"]

    print(f"\n  Selected portals: {', '.join(selected)}")
    return selected


def _configure_search_interactively() -> dict:
    print("\n── Job Search Configuration ─────────────────────────────────\n")

    titles_raw = _prompt(
        "What job titles are you targeting?\n"
        "  (e.g. Principal Engineer, Staff Engineer, Senior Staff Engineer)",
        "Principal Engineer, Staff Engineer",
    )
    titles = [t.strip() for t in titles_raw.split(",") if t.strip()]

    target_level = _prompt(
        "\nWhat is your target company level equivalent?\n"
        "  (e.g. Amazon L7, Google L7, Meta E7)",
        "Amazon L6",
    )

    min_tc_raw = _prompt(
        "\nMinimum total compensation you'd consider? (USD/year)",
        "300000",
    )
    try:
        min_tc = int(min_tc_raw.replace(",", "").replace("$", ""))
    except ValueError:
        min_tc = 300000

    location = _prompt(
        "\nPreferred job location?",
        "United States",
    )

    domains_raw = _prompt(
        "\nAny domains/industries to prioritize? (optional, comma-separated)\n"
        "  (e.g. distributed systems, ML platform, e-commerce, fintech)",
        "",
    )
    priority_domains = [d.strip() for d in domains_raw.split(",") if d.strip()]

    # ── Portals ──────────────────────────────────────────────────
    portals = _select_portals()

    # ── Account credentials ───────────────────────────────────────
    print("\n── Account Credentials ──────────────────────────────────────\n")
    print("These are stored locally in passwords.enc (encrypted). Never committed to git.\n")

    linkedin_email = _prompt(
        "LinkedIn email address?\n"
        "  (Used to log in to LinkedIn and search for jobs)",
    )

    print(
        "\nApplication email address?\n"
        "  This email will be used when the agent creates accounts on company ATS portals\n"
        "  (Workday, Greenhouse, etc.) and when filling out application forms.\n"
        "  Tip: use a dedicated job-search email so your inbox stays organized.\n"
        "  Can be the same as your LinkedIn email if you prefer."
    )
    app_email = _prompt("  Application email", linkedin_email)

    search_config = {
        "target_titles": titles,
        "target_level": target_level,
        "min_tc": min_tc,
        "location": location,
        "priority_domains": priority_domains,
        "portals": portals,
        "linkedin_email": linkedin_email,
        "application_email": app_email,
        "configured_at": datetime.now(timezone.utc).isoformat(),
    }

    print("\n── Configuration Summary ────────────────────────────────────")
    print(f"  Titles:           {', '.join(titles)}")
    print(f"  Target level:     {target_level}")
    print(f"  Min TC:           ${min_tc:,}")
    print(f"  Location:         {location}")
    print(f"  Portals:          {', '.join(portals)}")
    if priority_domains:
        print(f"  Domains:          {', '.join(priority_domains)}")
    print(f"  LinkedIn email:   {linkedin_email}")
    print(f"  Application email:{app_email}")
    print()

    return search_config


# ──────────────────────────────────────────────
# First-run encryption key generation
# ──────────────────────────────────────────────

def _ensure_encryption_key() -> None:
    """Generate ENCRYPTION_KEY if not present and write it to .env."""
    if config.ENCRYPTION_KEY:
        return

    key = password_manager.generate_encryption_key()
    env_path = config.BASE_DIR / ".env"

    # Append to .env
    with open(env_path, "a") as f:
        f.write(f"\nENCRYPTION_KEY={key}\n")

    # Reload
    load_dotenv(override=True)
    os.environ["ENCRYPTION_KEY"] = key
    config.ENCRYPTION_KEY = key
    logger.info("Generated and saved new ENCRYPTION_KEY to .env")


def _ensure_master_password() -> str:
    """Get or create the master portal password."""
    _ensure_encryption_key()
    master = password_manager.get_master()
    if not master:
        master = password_manager.generate_master_password()
        password_manager.store_master(master)
        logger.info("Generated new master portal password")
    return master


# ──────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────

def print_report() -> None:
    s = application_tracker.stats()
    rows = application_tracker.list_applications(limit=500)
    print("\n── Application Report ────────────────────────────────────────")
    print(f"  Total:        {s['total']}")
    for status, count in s.get("by_status", {}).items():
        print(f"  {status:<20} {count}")
    if s.get("last_applied"):
        print(f"  Last applied: {s['last_applied'][:10]}")
    print()
    if rows:
        print(f"  {'Company':<25} {'Title':<35} {'Status':<12} {'Date'}")
        print("  " + "-" * 85)
        for r in rows[:30]:
            date = (r.get("applied_at") or "")[:10] or "—"
            print(f"  {(r.get('company') or ''):<25} {(r.get('job_title') or ''):<35} {(r.get('status') or ''):<12} {date}")
        if len(rows) > 30:
            print(f"  ... and {len(rows) - 30} more")
    print()


# ──────────────────────────────────────────────
# Main agent loop
# ──────────────────────────────────────────────

async def run_agent(
    dry_run: bool = False,
    max_apps: int | None = None,
    title_override: str | None = None,
    company_override: str | None = None,
) -> None:
    """Main agent loop: search → filter → cover letter → apply."""
    from playwright.async_api import async_playwright

    # Validate config
    if not config.ANTHROPIC_API_KEY:
        print("✗ ANTHROPIC_API_KEY is not set. Add it to .env")
        sys.exit(1)

    application_tracker.init_db()
    config.ensure_dirs()

    # Load profile
    try:
        full_profile_data = profile_store.load_profile()
    except FileNotFoundError:
        print("No profile found. Run: python main.py --setup")
        sys.exit(1)

    profile = full_profile_data.get("profile", {})
    stories = full_profile_data.get("stories", [])
    search_config = profile_store.get_search_config()

    # Override titles/company if flags passed
    if title_override:
        search_config = dict(search_config)
        search_config["target_titles"] = [title_override]
    if company_override:
        search_config = dict(search_config)
        search_config["_company_filter"] = company_override.lower()

    effective_max = max_apps or config.MAX_APPLICATIONS_PER_RUN
    master_password = _ensure_master_password()
    linkedin_email = search_config.get("linkedin_email", profile.get("email", ""))
    # application_email is used by form_filler and ATS handlers when creating portal accounts
    application_email = search_config.get("application_email", linkedin_email)
    profile["_application_email"] = application_email  # injected so form_filler can use it

    # Find resume PDF
    resume_files = sorted(config.RESUME_DIR.glob("*.pdf"))
    resume_path = str(resume_files[0]) if resume_files else ""
    if not resume_path:
        docx_files = sorted(config.RESUME_DIR.glob("*.docx"))
        resume_path = str(docx_files[0]) if docx_files else ""

    logger.info("Starting agent. dry_run=%s, max=%d", dry_run, effective_max)
    if dry_run:
        print("\n🔍 DRY RUN — will search and filter jobs but NOT apply to anything\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # LinkedIn login
        logged_in = await login_linkedin(page, linkedin_email, master_password)
        if not logged_in:
            print("\n⚠️  LinkedIn login failed. Check credentials and try again.")
            await browser.close()
            return

        # Search for jobs across all configured portals
        portals = search_config.get("portals", ["linkedin"])
        print(f"\n🔎 Searching {len(portals)} portal(s): {', '.join(portals)}")
        jobs = await search_all_portals(page, search_config, max_per_title=30)

        # Company filter
        company_filter = search_config.get("_company_filter", "")
        if company_filter:
            jobs = [j for j in jobs if company_filter in j.get("company", "").lower()]
            logger.info("Company filter applied: %d jobs remaining", len(jobs))

        print(f"   Found {len(jobs)} candidate jobs")

        # Fetch job descriptions
        print("📋 Fetching job descriptions...")
        jobs = await fetch_job_descriptions(page, jobs, max_jobs=min(len(jobs), 100))

        applied_count = 0

        for job in jobs:
            if applied_count >= effective_max:
                logger.info("Reached max applications (%d)", effective_max)
                break

            job_id = job["job_id"]
            company = job.get("company", "Unknown")
            job_title = job.get("title", "")
            jd = job.get("job_description", "")
            # Canonical key is attached by deduplicate(); compute fallback if missing
            c_key = job.get("_canonical_key") or _canonical_key_for(company, job_title)
            portal = job.get("portal", "linkedin")

            print(f"\n{'─' * 60}")
            print(f"  {company} — {job_title}  [{portal}]")
            print(f"  {job.get('location', '')}")

            # ── Duplicate check (both portal job_id AND canonical key) ──────────
            if application_tracker.has_applied(job_id):
                print("  ⏭  Already applied (same portal job ID) — skipping")
                continue

            already_applied, prior_url = application_tracker.has_applied_canonical(c_key)
            if already_applied:
                print(f"  ⏭  Already applied to this role on a different portal")
                print(f"      Prior application: {prior_url or 'see DB'}")
                continue

            # No-sponsorship gate
            if has_no_sponsorship_language(jd) and not profile.get("immigration_status", "").lower() in ("us citizen", "citizen", "green card", "permanent resident"):
                print("  ⏭  'No sponsorship' language found — skipping")
                application_tracker.upsert_application({
                    "job_id": job_id,
                    "canonical_key": c_key,
                    "company": company,
                    "job_title": job_title,
                    "location": job.get("location"),
                    "job_url": job.get("apply_url"),
                    "status": "skipped_no_sponsorship",
                })
                continue

            # Level check
            passes_level, est_tc = await level_checker.is_at_target_level(
                company=company,
                job_title=job_title,
                target_level_desc=search_config.get("target_level", ""),
                min_tc=search_config.get("min_tc", 0),
            )
            if not passes_level:
                print(f"  ⏭  Below target level (est. TC: ${est_tc:,}) — skipping")
                application_tracker.upsert_application({
                    "job_id": job_id,
                    "canonical_key": c_key,
                    "company": company,
                    "job_title": job_title,
                    "location": job.get("location"),
                    "job_url": job.get("apply_url"),
                    "estimated_tc": est_tc,
                    "status": "below_level",
                })
                continue

            # Domain relevance score
            domain_score = score_domain_relevance(
                jd, search_config.get("priority_domains", [])
            )
            print(f"  ✓  Passes checks. Est. TC: ${est_tc:,} | Domain score: {domain_score}/100 | key: {c_key}")

            # Create evidence folder
            folder = evidence_store.create_evidence_folder(
                company=company,
                job_id=job_id,
                metadata=evidence_store.build_initial_metadata(
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    location=job.get("location", ""),
                    job_url=job.get("apply_url", ""),
                    application_type="easy_apply" if job.get("is_easy_apply") else "external",
                ),
            )
            app_logger_handler = evidence_store.setup_app_logger(folder)

            # Save JD
            evidence_store.save_job_description(folder, jd)

            # Pre-register in DB (BEFORE any form interaction)
            application_tracker.upsert_application({
                "job_id": job_id,
                "canonical_key": c_key,
                "company": company,
                "job_title": job_title,
                "location": job.get("location"),
                "job_url": job.get("apply_url"),
                "application_type": "easy_apply" if job.get("is_easy_apply") else "external",
                "levels_verified": int(passes_level),
                "estimated_tc": est_tc,
                "domain_score": domain_score,
                "evidence_folder": str(folder),
                "status": "pending",
            })

            if dry_run:
                print(f"  🔍 [DRY RUN] Would apply. Evidence folder: {folder.name}")
                application_tracker.update_status(job_id, "dry_run")
                evidence_store.update_metadata(folder, {"status": "dry_run"})
                logging.getLogger().removeHandler(app_logger_handler)
                continue

            # Generate cover letter
            print("  ✍  Generating cover letter...")
            try:
                cl_text, research = await cover_letter_module.generate_cover_letter_async(
                    profile=profile,
                    stories=stories,
                    job_title=job_title,
                    company=company,
                    job_description=jd,
                )
                evidence_store.save_cover_letter(folder, cl_text)
                evidence_store.save_company_research(folder, research)
            except Exception as exc:
                logger.error("Cover letter generation failed: %s", exc)
                cl_text = ""

            # Apply
            success = False
            await asyncio.sleep(random.uniform(
                config.ACTION_DELAY_MIN,
                config.ACTION_DELAY_MAX,
            ))

            if job.get("is_easy_apply"):
                success = await run_easy_apply(
                    page=page,
                    job=job,
                    profile=profile,
                    cover_letter=cl_text,
                    resume_path=resume_path,
                    folder=folder,
                    dry_run=False,
                )
            elif job.get("apply_url"):
                job["external_url"] = job["apply_url"]
                success = await run_external_apply(
                    page=page,
                    job=job,
                    profile=profile,
                    cover_letter=cl_text,
                    resume_path=resume_path,
                    folder=folder,
                    master_password=master_password,
                    dry_run=False,
                )

            if success:
                applied_count += 1
                print(f"  ✅ Applied! ({applied_count}/{effective_max})")
            else:
                print(f"  ❌ Application failed")

            logging.getLogger().removeHandler(app_logger_handler)
            await asyncio.sleep(random.uniform(
                config.ACTION_DELAY_MIN * 2,
                config.ACTION_DELAY_MAX * 2,
            ))

        await browser.close()

    print(f"\n{'=' * 60}")
    print(f"Session complete. Applications submitted: {applied_count}")
    print_report()


# ──────────────────────────────────────────────
# UI launcher
# ──────────────────────────────────────────────

def launch_ui() -> None:
    import uvicorn
    print(f"\n🌐 Launching dashboard at http://localhost:{config.DASHBOARD_PORT}")
    print("   Press Ctrl+C to stop.\n")
    webbrowser.open(f"http://localhost:{config.DASHBOARD_PORT}")
    uvicorn.run(
        "dashboard.app:app",
        host="0.0.0.0",
        port=config.DASHBOARD_PORT,
        reload=False,
        log_level="warning",
    )


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Job Application Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--setup", action="store_true",
                        help="First-run: extract profile + configure search")
    parser.add_argument("--refresh-profile", action="store_true",
                        help="Re-parse documents, overwrite profile.json")
    parser.add_argument("--setup-linkedin", action="store_true",
                        help="Populate LinkedIn profile from profile.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Search + filter jobs, print matches, NO applying")
    parser.add_argument("--max", type=int, default=None, metavar="N",
                        help="Cap at N applications this session")
    parser.add_argument("--title", type=str, default=None,
                        help="Override search to this title only")
    parser.add_argument("--company", type=str, default=None,
                        help="Target this company only")
    parser.add_argument("--report", action="store_true",
                        help="Print application summary in terminal")
    parser.add_argument("--export", type=str, default=None, metavar="FILE",
                        help="Export applications to CSV file")
    parser.add_argument("--ui", action="store_true",
                        help="Launch dashboard at http://localhost:8080")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)
    config.ensure_dirs()
    application_tracker.init_db()

    if args.setup or args.refresh_profile:
        run_setup(refresh=args.refresh_profile)
        return

    if args.report:
        print_report()
        return

    if args.export:
        out = Path(args.export)
        application_tracker.export_csv(out)
        print(f"Exported to {out}")
        return

    if args.ui:
        launch_ui()
        return

    # Check profile exists before running
    if not profile_store.profile_exists():
        resume_files = list(config.RESUME_DIR.glob("*"))
        supported = [f for f in resume_files if f.suffix.lower() in (".pdf", ".docx", ".doc")]
        if not supported:
            _print_welcome()
        else:
            print("Profile not found. Run: python main.py --setup")
        sys.exit(0)

    # Run the agent
    asyncio.run(
        run_agent(
            dry_run=args.dry_run,
            max_apps=args.max,
            title_override=args.title,
            company_override=args.company,
        )
    )


if __name__ == "__main__":
    main()
