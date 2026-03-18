╔══════════════════════════════════════════════════════════════╗
║         AI Job Application Agent — My Documents              ║
╚══════════════════════════════════════════════════════════════╝

This folder is READ-ONLY to the agent. It reads your files here
but never modifies or deletes them.

──────────────────────────────────────────────────────────────
STEP 1 — Add your resume
──────────────────────────────────────────────────────────────

Drop your resume file into:

    my_documents/resume/

Supported formats: PDF, DOCX
One file is enough. The agent will parse it automatically.

──────────────────────────────────────────────────────────────
STEP 2 — (Optional) Add STAR story documents
──────────────────────────────────────────────────────────────

Drop any career story documents into:

    my_documents/stories/

Supported formats: PDF, DOCX, MD, TXT
These are used to write richer, more personal cover letters
with real examples and metrics from your career.

Examples of what to include:
  - A document with 3-5 STAR stories (Situation, Task, Action, Result)
  - Any performance review excerpts with quantified wins
  - A "brag document" you keep for promotion discussions

──────────────────────────────────────────────────────────────
STEP 3 — Run setup
──────────────────────────────────────────────────────────────

    python main.py --setup

This will:
  1. Parse your resume and stories
  2. Save your profile to my_documents/profile.json
  3. Ask a few questions to configure your job search

──────────────────────────────────────────────────────────────
FILES GENERATED HERE (by the agent, safe to delete & re-run)
──────────────────────────────────────────────────────────────

  profile.json        — Extracted profile (auto-generated)
  search_config.json  — Your job search preferences (auto-generated)

──────────────────────────────────────────────────────────────
UPDATING YOUR RESUME
──────────────────────────────────────────────────────────────

Drop the new file into my_documents/resume/ (replace the old one),
then run:

    python main.py --refresh-profile

