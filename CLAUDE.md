# CLAUDE.md — YouTube Studio Scheduler (Praveen)

Read `docs/SPEC.md` (what to build) and `docs/BUILD_PLAN.md` (order + acceptance criteria) before writing code.
Work one phase at a time; finish its acceptance checks before starting the next.

## Context
- Owner: Praveen Dalal — not a developer by background. Explain decisions in plain language,
  give copy-paste commands for Windows PowerShell, and never assume prior cloud knowledge.
- Single-user web app to schedule uploads to 4 YouTube channels owned by pravendalal@gmail.com:
  Ink & Motion (@InkandMotionYT), Mirrorkin Press (@MirrorkinPress),
  Kidz Curious Labs (@KidzCuriousLabs), AIPraveen (@AIPraveen18).
- Cadence per channel: 1 Short daily Mon–Sat + 1 Long on Sunday, 19:00 Asia/Kolkata. Files 30–100 MB.
- The existing CLI in `src/` (uploader.py, common.py, auth_setup.py) is tested, working logic.
  **Reuse it** — move validation/upload logic into `app/services/`; don't rewrite from scratch.
  Keep `config.yaml` channel defaults as the seed data for the channels collection.

## Stack (decided — don't change without asking)
- Python 3.12, FastAPI, Jinja2 templates + HTMX + Alpine.js, Tailwind (CDN build is fine for v1),
  FullCalendar for the calendar view.
- Google Cloud project `yt-auto-uploader`, region `asia-south1`:
  Cloud Run **service** (web) + Cloud Run **job** (worker, same image), Firestore (Native),
  Cloud Storage (video staging), Secret Manager, Cloud Scheduler.
- Google APIs via `google-api-python-client`; Claude via the official `anthropic` SDK
  (model ID from env `ANTHROPIC_MODEL` — check docs.claude.com for the current Sonnet ID).

## Hard rules
- YouTube uploads: always `privacyStatus=private` + `publishAt` (UTC RFC3339). Always send
  `selfDeclaredMadeForKids` and `containsSyntheticMedia`. Never upload the same video twice:
  claim work with a Firestore transaction (Ready → Uploading) and never retry `videos.insert`
  after a response with a video ID was received.
- Quota: `videos.insert` has its own bucket (100/day, 1 unit each). Everything else shares 10,000
  units/day (thumbnail 50, playlistItems.insert 50, playlists.insert 50, captions.insert 400,
  videos.update 50). Track usage per Pacific-time day in Firestore; stop gracefully when exhausted.
- Until the YouTube API audit is approved, API uploads are locked private forever.
  Tests that hit real YouTube must use throwaway clips. Default `AUDIT_APPROVED=false` shows a banner.
- Browser uploads go **directly to Cloud Storage via signed resumable URLs** (Cloud Run has a 32 MB
  request limit). Never stream video bodies through the web service.
- Secrets: OAuth refresh tokens encrypted (Fernet key from Secret Manager) before storing in Firestore.
  Never log tokens, never commit `client_secret*.json`, `tokens/`, `.env`.
- Access: Google Sign-In; only emails in `ALLOWED_EMAILS` (pravendalal@gmail.com) get in. Everything
  else 403. CSRF protection on all POSTs.
- Times: store UTC, display Asia/Kolkata.

## Conventions
- Layout: `app/main.py`, `app/routers/`, `app/services/` (youtube.py, storage.py, ai.py, sheets.py,
  notify.py, scheduling.py, quota.py), `app/models.py` (Pydantic), `app/templates/`, `worker/run.py`.
- Tests: `pytest`, mock all Google/Anthropic calls; port `yt-test`-style tests for validation.
  Run `pytest -q` and `ruff check .` before saying a phase is done.
- Local dev: `uvicorn app.main:app --reload` with the Firestore emulator; document every env var in
  `.env.example`.
- Small commits per feature with clear messages.
