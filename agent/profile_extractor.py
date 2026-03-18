"""
profile_extractor.py

Parses resume (PDF/DOCX) and optional STAR story documents using LLM-based
extraction. Returns a fully structured UserProfile dict.
Zero user data is hardcoded here — everything comes from files at runtime.
"""
import json
import logging
from pathlib import Path
from typing import Any

import anthropic
import pdfplumber
from docx import Document

import config

logger = logging.getLogger(__name__)

_RESUME_SYSTEM = """
You are a resume parser. Extract structured profile information from the provided
resume text and return ONLY valid JSON matching the schema below.
If a field cannot be found, use null. Never hallucinate data.

Schema:
{
  "full_name": "str",
  "first_name": "str",
  "last_name": "str",
  "email": "str",
  "phone": "str",
  "location": "str",
  "city": "str",
  "state": "str",
  "zip_code": "str or null",
  "country": "str",
  "linkedin_url": "str or null",
  "github_url": "str or null",
  "portfolio_url": "str or null",
  "current_title": "str",
  "current_company": "str",
  "years_of_experience": "int",
  "immigration_status": "str or null",
  "requires_sponsorship": "bool or null",
  "summary": "str",
  "skills": ["str"],
  "key_achievements": ["str"],
  "experience": [
    {
      "title": "str",
      "company": "str",
      "location": "str",
      "start_date": "str",
      "end_date": "str",
      "bullets": ["str"]
    }
  ],
  "education": [
    {
      "degree": "str",
      "institution": "str",
      "year": "str or null"
    }
  ],
  "certifications": ["str"],
  "languages": ["str"] or null,
  "eeo": {
    "gender": "Prefer not to say",
    "veteran_status": "I am not a protected veteran",
    "disability_status": "I don't wish to answer",
    "race_ethnicity": "I don't wish to answer"
  }
}
"""

_STORY_SYSTEM = """
Extract STAR (Situation, Task, Action, Result) stories from the text.
Return ONLY valid JSON:
{
  "stories": [
    {
      "title": "str",
      "situation": "str",
      "task": "str",
      "action": "str",
      "result": "str",
      "metrics": ["str"],
      "keywords": ["str"]
    }
  ]
}
"""


def _read_pdf(path: Path) -> str:
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


def _read_docx(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    elif suffix in (".docx", ".doc"):
        return _read_docx(path)
    elif suffix in (".md", ".txt"):
        return _read_txt(path)
    else:
        logger.warning("Unsupported file type: %s — skipping", path.name)
        return ""


def _call_claude(system: str, user: str) -> dict[str, Any]:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(raw)


def extract_resume(resume_dir: Path) -> dict[str, Any]:
    """Parse all resume files in the directory into a structured profile."""
    files = sorted(resume_dir.glob("*"))
    supported = [f for f in files if f.suffix.lower() in (".pdf", ".docx", ".doc")]
    if not supported:
        raise FileNotFoundError(
            f"No supported resume found in {resume_dir}. "
            "Please add a PDF or DOCX file."
        )

    resume_file = supported[0]
    if len(supported) > 1:
        logger.info("Multiple resume files found; using: %s", resume_file.name)

    logger.info("Parsing resume: %s", resume_file.name)
    resume_text = _read_file(resume_file)
    if not resume_text.strip():
        raise ValueError(f"Could not extract text from {resume_file.name}")

    profile = _call_claude(_RESUME_SYSTEM, f"Resume text:\n\n{resume_text}")
    profile["_source_resume"] = resume_file.name
    logger.info("Resume parsed. Name: %s", profile.get("full_name", "unknown"))
    return profile


def extract_stories(stories_dir: Path) -> list[dict[str, Any]]:
    """Parse all story documents and return a flat list of STAR stories."""
    all_stories: list[dict[str, Any]] = []
    files = sorted(stories_dir.glob("*"))
    supported = [
        f for f in files
        if f.suffix.lower() in (".pdf", ".docx", ".doc", ".md", ".txt")
    ]
    if not supported:
        logger.info("No story files found in %s — skipping", stories_dir)
        return []

    for story_file in supported:
        logger.info("Parsing story file: %s", story_file.name)
        text = _read_file(story_file)
        if not text.strip():
            continue
        try:
            result = _call_claude(_STORY_SYSTEM, f"Document text:\n\n{text}")
            stories = result.get("stories", [])
            for s in stories:
                s["_source_file"] = story_file.name
            all_stories.extend(stories)
            logger.info("Extracted %d stories from %s", len(stories), story_file.name)
        except Exception as exc:
            logger.warning("Failed to parse stories from %s: %s", story_file.name, exc)

    return all_stories


def extract_all(
    resume_dir: Path | None = None,
    stories_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Full extraction pipeline.
    Returns the merged profile+stories dict ready to be saved as profile.json.
    """
    resume_dir = resume_dir or config.RESUME_DIR
    stories_dir = stories_dir or config.STORIES_DIR

    profile = extract_resume(resume_dir)
    stories = extract_stories(stories_dir)

    source_stories = [
        s["_source_file"] for s in stories
        if "_source_file" in s
    ]

    return {
        "profile": profile,
        "stories": stories,
        "_meta": {
            "source_resume": profile.pop("_source_resume", ""),
            "source_stories": list(dict.fromkeys(source_stories)),
        },
    }
