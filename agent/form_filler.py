"""
form_filler.py

Generic semantic form-filling engine. Works on ANY website without hardcoded
selectors. Uses label text, placeholder, name attribute, and aria-label to
detect field meaning, then maps it to the user's profile.
"""
import asyncio
import json
import logging
import random
import re
from typing import Any

import anthropic
from playwright.async_api import Page, Locator

import config

logger = logging.getLogger(__name__)

# Regex patterns → profile field getter lambdas
FIELD_MAPPINGS: list[tuple[str, Any]] = [
    (r"first.?name",                        lambda p: p.get("first_name", "")),
    (r"last.?name|surname",                 lambda p: p.get("last_name", "")),
    (r"full.?name|your.?name",              lambda p: p.get("full_name", "")),
    # Use application_email (set during --setup) for ATS portal forms.
    # Falls back to resume email if not configured.
    (r"email",                              lambda p: p.get("_application_email") or p.get("email", "")),
    (r"phone|mobile|telephone|tel",         lambda p: p.get("phone", "")),
    (r"city",                               lambda p: p.get("city", "")),
    (r"state|province|region",             lambda p: p.get("state", "")),
    (r"zip|postal.?code",                  lambda p: p.get("zip_code", "")),
    (r"country",                            lambda p: p.get("country", "United States")),
    (r"linkedin",                           lambda p: p.get("linkedin_url", "")),
    (r"github",                             lambda p: p.get("github_url", "")),
    (r"website|portfolio|personal.?site",   lambda p: p.get("portfolio_url", "")),
    (r"current.?title|job.?title|position|role", lambda p: p.get("current_title", "")),
    (r"current.?company|employer|organization", lambda p: p.get("current_company", "")),
    (r"years.?of.?exp|experience.?years",   lambda p: str(p.get("years_of_experience", ""))),
    (r"gender|sex",                         lambda p: p.get("eeo", {}).get("gender", "Prefer not to say")),
    (r"veteran",                            lambda p: p.get("eeo", {}).get("veteran_status", "I am not a protected veteran")),
    (r"disabilit",                          lambda p: p.get("eeo", {}).get("disability_status", "I don't wish to answer")),
    (r"authorized.*(work|us)|work.?authorization", lambda p: "Yes"),
    (r"require.*sponsor|need.*sponsor|visa.*sponsor", lambda p: "No" if not p.get("requires_sponsorship") else "Yes"),
    (r"race|ethnic|national.?origin",       lambda p: p.get("eeo", {}).get("race_ethnicity", "I don't wish to answer")),
    (r"salary|compensation|pay|expected.*comp", lambda p: ""),
    (r"start.?date|available|availability", lambda p: "2-4 weeks / Negotiable"),
    (r"reloc",                              lambda p: "Open to discussion"),
    (r"address.*(line|street)|street.?addr", lambda p: p.get("location", "")),
    (r"summary|cover.?letter|additional.*info|why.*us|motivation", lambda p: "__cover_letter__"),
]


def _match_profile_field(label: str, profile: dict[str, Any]) -> str | None:
    """Return the profile value for a field label, or None if no match."""
    normalized = label.lower().strip()
    for pattern, getter in FIELD_MAPPINGS:
        if re.search(pattern, normalized):
            value = getter(profile)
            if value is None:
                return ""
            return str(value)
    return None


async def _get_field_label(el: Locator) -> str:
    """Extract the semantic label for a form element."""
    # Try aria-label
    aria = await el.get_attribute("aria-label") or ""
    if aria.strip():
        return aria.strip()

    # Try associated <label> via id
    field_id = await el.get_attribute("id") or ""
    if field_id:
        try:
            page = el.page
            label_el = page.locator(f'label[for="{field_id}"]')
            count = await label_el.count()
            if count > 0:
                text = await label_el.first.inner_text()
                if text.strip():
                    return text.strip()
        except Exception:
            pass

    # Try placeholder
    placeholder = await el.get_attribute("placeholder") or ""
    if placeholder.strip():
        return placeholder.strip()

    # Try name attribute
    name = await el.get_attribute("name") or ""
    if name.strip():
        return name.replace("_", " ").replace("-", " ").strip()

    # Try data-field-name
    data_field = await el.get_attribute("data-field-name") or ""
    if data_field.strip():
        return data_field.strip()

    return ""


async def _type_humanlike(el: Locator, text: str) -> None:
    """Type text with human-like delays."""
    await el.click()
    await el.clear()
    for char in text:
        await el.type(char)
        await asyncio.sleep(random.uniform(0.03, 0.12))


async def _handle_select(el: Locator, label: str, options: list[str], profile: dict[str, Any]) -> bool:
    """Use Claude to pick the best option from a dropdown."""
    direct = _match_profile_field(label, profile)
    if direct is not None and direct:
        # Try exact or case-insensitive match first
        for opt in options:
            if opt.lower() == direct.lower() or direct.lower() in opt.lower():
                await el.select_option(label=opt)
                logger.debug("Select '%s' → '%s' (direct)", label, opt)
                return True

    # Fall back to LLM
    try:
        answer = await _infer_field_answer(
            field_label=label,
            profile=profile,
            options=options,
        )
        for opt in options:
            if opt.lower() == answer.lower() or answer.lower() in opt.lower():
                await el.select_option(label=opt)
                logger.debug("Select '%s' → '%s' (llm)", label, opt)
                return True
        # Just select the closest
        if options:
            await el.select_option(label=options[0])
    except Exception as exc:
        logger.warning("select '%s' failed: %s", label, exc)

    return False


async def _infer_field_answer(
    field_label: str,
    profile: dict[str, Any],
    options: list[str] | None = None,
) -> str:
    """Ask Claude what to put in an unknown field given this user's profile."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    opts_str = ""
    if options:
        opts_str = f"\nAvailable options: {json.dumps(options)}"

    prompt = f"""You are helping fill out a job application form.

Field label: "{field_label}"{opts_str}

Applicant profile summary:
- Name: {profile.get("full_name", "")}
- Title: {profile.get("current_title", "")} at {profile.get("current_company", "")}
- Location: {profile.get("location", "")}
- Years of experience: {profile.get("years_of_experience", "")}
- Skills: {", ".join(profile.get("skills", [])[:10])}
- Immigration status: {profile.get("immigration_status", "US Citizen")}

{"Pick the single best matching option from the list above." if options else "Provide a short, appropriate answer for this field."}
Return ONLY the answer text, nothing else."""

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip().strip('"').strip("'")


async def fill_form(
    page: Page,
    profile: dict[str, Any],
    cover_letter: str = "",
    resume_path: str = "",
    form_data_log: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """
    Detect and fill all form fields on the current page.
    Returns list of {field_label, value} dicts for logging.
    Returns early without side effects on --dry-run (cover_letter == '__dry_run__').
    """
    dry_run = cover_letter == "__dry_run__"
    filled: list[dict[str, Any]] = []

    # --- Text inputs and textareas ---
    text_selectors = "input:not([type=hidden]):not([type=file]):not([type=submit]):not([type=button]):not([type=checkbox]):not([type=radio]), textarea"
    inputs = page.locator(text_selectors)
    count = await inputs.count()

    for i in range(count):
        el = inputs.nth(i)
        try:
            if not await el.is_visible():
                continue
            label = await _get_field_label(el)
            if not label:
                continue

            value = _match_profile_field(label, profile)
            if value == "__cover_letter__":
                value = cover_letter
            elif value is None:
                # Ask Claude
                try:
                    value = await _infer_field_answer(label, profile)
                except Exception:
                    value = ""

            if value and not dry_run:
                await _type_humanlike(el, value)
                await asyncio.sleep(random.uniform(
                    config.ACTION_DELAY_MIN * 0.3,
                    config.ACTION_DELAY_MAX * 0.3,
                ))

            filled.append({"field_label": label, "value": value})
            logger.debug("Filled: '%s' = '%s'", label, value[:60] if value else "")
        except Exception as exc:
            logger.debug("Skipping field %d: %s", i, exc)

    # --- Selects / dropdowns ---
    selects = page.locator("select")
    sel_count = await selects.count()
    for i in range(sel_count):
        el = selects.nth(i)
        try:
            if not await el.is_visible():
                continue
            label = await _get_field_label(el)
            options_els = el.locator("option")
            opt_count = await options_els.count()
            options = [
                await options_els.nth(j).inner_text()
                for j in range(opt_count)
                if (await options_els.nth(j).get_attribute("value") or "") not in ("", "0", "null")
            ]
            if not dry_run:
                await _handle_select(el, label, options, profile)
            filled.append({"field_label": label, "value": f"[dropdown: {options[:3]}...]"})
        except Exception as exc:
            logger.debug("Skipping select %d: %s", i, exc)

    # --- File upload (resume) ---
    if resume_path and not dry_run:
        file_inputs = page.locator("input[type=file]")
        fc = await file_inputs.count()
        for i in range(fc):
            el = file_inputs.nth(i)
            try:
                await el.set_input_files(resume_path)
                filled.append({"field_label": "resume_upload", "value": resume_path})
                logger.info("Uploaded resume: %s", resume_path)
                break
            except Exception as exc:
                logger.debug("File upload %d failed: %s", i, exc)

    if form_data_log is not None:
        form_data_log.extend(filled)

    return filled


async def click_next_button(page: Page) -> bool:
    """Click the most likely 'proceed' button on a multi-step form."""
    candidates = [
        "text=Next",
        "text=Continue",
        "text=Save and Continue",
        "text=Next Step",
        "text=Proceed",
        "text=Save & Continue",
        "[data-testid*=next]",
        "[data-automation*=next]",
        "button[type=submit]",
    ]
    for selector in candidates:
        btn = page.locator(selector).first
        try:
            if await btn.is_visible():
                await asyncio.sleep(random.uniform(
                    config.ACTION_DELAY_MIN,
                    config.ACTION_DELAY_MAX,
                ))
                await btn.click()
                logger.debug("Clicked: %s", selector)
                return True
        except Exception:
            pass
    return False


async def detect_submit_button(page: Page) -> Locator | None:
    """Return the final submit button if visible."""
    submit_texts = ["Submit", "Submit Application", "Apply Now", "Submit Application"]
    for text in submit_texts:
        btn = page.locator(f"text={text}").first
        try:
            if await btn.is_visible():
                return btn
        except Exception:
            pass
    return None
