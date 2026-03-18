"""
cover_letter.py

Researches a company and generates a personalized cover letter using Claude.
Every cover letter is unique and grounded in real company information.
"""
import asyncio
import logging
import re
from typing import Any

import anthropic
import httpx
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

_FORBIDDEN_PHRASES = [
    "i am writing to",
    "i am a perfect fit",
    "passion for technology",
    "dream company",
    "synergy",
    "leverage my skills",
    "i am excited to apply",
]

_SYSTEM_TEMPLATE = """
You are an expert career coach writing a cover letter for a job applicant.
Your job is to write a cover letter that will impress a senior technical recruiter.

The applicant's profile:
- Name: {full_name}
- Current role: {current_title} at {current_company}
- Years of experience: {years_of_experience}
- Key achievements: {key_achievements}
- Most relevant story for this role:
  Title: {story_title}
  Result: {story_result}
  Metrics: {story_metrics}

Cover letter rules:
1. Open with a SPECIFIC hook about the company — reference something real from the
   company research (a recent launch, engineering blog post, product, or mission)
2. Paragraph 2: map 2-3 of the applicant's most relevant achievements to the JD
   requirements, using exact metrics from their profile
3. Paragraph 3: explain why THIS company specifically — reference the research
4. Close with a confident, peer-level call to action
5. Tone: confident and executive-ready — not sycophantic, not desperate
6. Length: 3-4 paragraphs, under 350 words
7. NEVER write: "I am writing to", "I am a perfect fit", "passion for technology",
   "dream company", "synergy", "leverage my skills", "I am excited to apply"
8. Do NOT mention salary, immigration status, or visa
9. Start directly with the hook — no "Dear Hiring Manager" opening needed
"""


async def _fetch_url(url: str, timeout: int = 10) -> str:
    """Fetch a URL and return cleaned text."""
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ""
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)[:3000]
    except Exception as exc:
        logger.debug("URL fetch failed %s: %s", url, exc)
        return ""


async def research_company(company: str, job_title: str) -> str:
    """
    Scrape company homepage + engineering blog + LinkedIn page.
    Returns a ≤400 word research summary.
    """
    slug = re.sub(r"[^a-z0-9]", "", company.lower())
    urls = [
        f"https://www.{slug}.com",
        f"https://www.{slug}.com/about",
        f"https://engineering.{slug}.com",
        f"https://blog.{slug}.com",
        f"https://www.linkedin.com/company/{slug}/",
    ]

    texts = await asyncio.gather(*[_fetch_url(u) for u in urls])
    combined = "\n\n".join(t for t in texts if t)[:6000]

    if not combined.strip():
        return f"No public information found for {company}."

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": (
                f"Summarize key facts about {company} relevant to a {job_title} "
                f"applicant in under 400 words. Focus on: recent product launches, "
                f"engineering culture, technical challenges, mission, recent news. "
                f"Be specific and factual.\n\nSource text:\n{combined}"
            ),
        }],
    )
    return response.content[0].text.strip()


def _pick_best_story(
    stories: list[dict[str, Any]],
    job_description: str,
) -> dict[str, Any]:
    """Select the most relevant STAR story based on keyword overlap with the JD."""
    if not stories:
        return {}

    jd_words = set(re.sub(r"[^\w\s]", "", job_description.lower()).split())

    def score(story: dict[str, Any]) -> int:
        keywords = set(k.lower() for k in story.get("keywords", []))
        text = " ".join([
            story.get("situation", ""),
            story.get("action", ""),
            story.get("result", ""),
        ]).lower()
        word_set = set(text.split()) | keywords
        return len(jd_words & word_set)

    return max(stories, key=score)


def generate_cover_letter(
    profile: dict[str, Any],
    stories: list[dict[str, Any]],
    job_title: str,
    company: str,
    job_description: str,
    company_research: str,
) -> str:
    """Generate a personalized cover letter. Returns Markdown text."""
    best_story = _pick_best_story(stories, job_description)

    system = _SYSTEM_TEMPLATE.format(
        full_name=profile.get("full_name", ""),
        current_title=profile.get("current_title", ""),
        current_company=profile.get("current_company", ""),
        years_of_experience=profile.get("years_of_experience", ""),
        key_achievements="\n".join(f"- {a}" for a in profile.get("key_achievements", [])[:6]),
        story_title=best_story.get("title", "N/A"),
        story_result=best_story.get("result", "N/A"),
        story_metrics=", ".join(best_story.get("metrics", [])),
    )

    user = (
        f"Job title: {job_title}\n"
        f"Company: {company}\n\n"
        f"Job description:\n{job_description[:3000]}\n\n"
        f"Company research:\n{company_research}"
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=800,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    letter = response.content[0].text.strip()

    # Sanity check for forbidden phrases
    lower = letter.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in lower:
            logger.warning("Cover letter contains forbidden phrase: '%s'", phrase)

    return letter


async def generate_cover_letter_async(
    profile: dict[str, Any],
    stories: list[dict[str, Any]],
    job_title: str,
    company: str,
    job_description: str,
) -> tuple[str, str]:
    """
    Full pipeline: research company + generate cover letter.
    Returns (cover_letter_text, company_research_text).
    """
    logger.info("Researching company: %s", company)
    research = await research_company(company, job_title)

    logger.info("Generating cover letter for %s / %s", company, job_title)
    letter = generate_cover_letter(
        profile=profile,
        stories=stories,
        job_title=job_title,
        company=company,
        job_description=job_description,
        company_research=research,
    )
    return letter, research
