# BUILD PLAN — phases with acceptance checks

Do these in order. At the end of each phase: run `pytest -q` + `ruff check .`, show Praveen how to
try it locally (PowerShell commands), and wait for his OK before the next phase.

## Phase 0 — Prerequisites (Praveen, with Claude's guidance)
- [ ] Google Cloud project `yt-auto-uploader` with billing attached; APIs enabled: YouTube Data v3,
      Sheets, Gmail, Firestore, Cloud Storage, Secret Manager, Cloud Run, Cloud Scheduler, Cloud Build.
- [ ] OAuth consent screen External, **In production**; OAuth client type **Web application**
      with redirect URIs `http://localhost:8000/auth/callback` (+ the Cloud Run URL later).
- [ ] YouTube API audit form submitted (point it at the deployed app + `/privacy` once Phase 7 is live,
      or submit now and update).
- [ ] Anthropic API key (console.anthropic.com).
- [ ] gcloud CLI installed and logged in; Python 3.12; Git; repo pushed to a **private** GitHub repo.

## Phase 1 — Scaffold + sign-in
Build: FastAPI app, base layout (Tailwind, HTMX, Alpine), Google Sign-In, session cookie, allowlist,
CSRF, `/privacy` + `/terms`, `.env.example`, Dockerfile, Firestore client with emulator support.
Accept: only pravendalal@gmail.com reaches `/`; any other Google account gets 403; tests for allowlist.

## Phase 2 — Channels
Build: Connect/reconnect channel flow, encrypted token storage, channels page with defaults,
slot rules and AI profile editor; seed defaults from `config.yaml`; account connection (Sheets+Gmail).
Accept: all 4 channels connected and listed with correct handles; tokens unreadable in Firestore
console; revoking access in Google account shows "expired" after next check.

## Phase 3 — Upload + queue
Build: GCS bucket + CORS (script it), signed resumable upload, drop zone with per-file progress,
Short/Long detection, slot assignment, card editor, queue table + edit drawer, thumbnail + captions
attachments, validation identical to CLI `build_job` (move it to `app/services/youtube.py`).
Accept: drop 7 files for one channel → 6 Shorts Mon–Sat + 1 Long Sun at 19:00 IST assigned;
100 MB file uploads with progress; invalid title blocks "Ready" with a clear message.
Unit tests for slot assignment edge cases.

## Phase 4 — Worker
Build: `worker/run.py` reusing CLI upload logic but reading from GCS; Firestore claim transaction;
quota tracking; email summary; activity log; "Upload now" button (Run Admin API); stuck-row detection;
daily published-status + GCS cleanup.
Accept: with mocks — no double upload when two workers run at once; quota stop leaves remaining
videos `ready`; post-upload quota → warning, not re-upload. Real test: one throwaway clip to one
channel ends `scheduled` with URL (locked private pre-audit — expected).

## Phase 5 — Calendar
Build: FullCalendar month/week, channel colours + filter chips, drag-to-reschedule with the rules in
SPEC §5, click → drawer.
Accept: moving a draft changes only DB; moving a scheduled video updates publishAt on YouTube
(verify in Studio); moving into the past or a published video is refused with a message.

## Phase 6 — AI drafting
Build: `services/ai.py` with per-channel profile prompt, strict JSON + validation + one retry,
"Draft with AI" per card, "Draft all (empty fields only)", regenerate, recent-titles de-dup.
Accept: drafts respect length limits on 20 sample filenames per channel; kids channels pass the
COPPA-safe checklist; manual edits are never overwritten by "Draft all".

## Phase 7 — Sheet sync + deploy
Build: push/pull sync per SPEC §5 using the existing template columns; `deploy/deploy.sh` that
creates/updates Secret Manager secrets, Firestore, bucket, Cloud Run service + job, Scheduler (every
15 min), and prints the URL; add the Cloud Run URL to OAuth redirect URIs.
Accept: edit a Ready row's title in Sheets → appears in app after next run; app edits appear in
Sheets; deployed app works from phone; scheduler runs show in Activity.

## Phase 8 — Audit readiness
- `/privacy` and `/terms` reachable publicly; consent screen links to them.
- Record a 2–3 min screen video: sign in → connect channel → upload → schedule → result.
- Update the audit form with the app URL, video, and description (internal single-user tool for
  own channels; data stored: video metadata + IDs; tokens encrypted; no sharing).
- After approval: set `AUDIT_APPROVED=true`, remove banner, first real scheduled episode.
