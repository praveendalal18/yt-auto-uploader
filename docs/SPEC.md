# SPEC — YouTube Studio Scheduler

A private web app where Praveen connects his 4 YouTube channels once, drops in videos, gets
AI-drafted titles/descriptions, sees everything on a calendar, and the system uploads and
schedules each video automatically. Replaces the Sheet + script + terminal workflow
(the Google Sheet stays as an optional mirror).

## 1. User stories
1. Sign in with Google; nobody else can.
2. Connect each channel with a "Connect channel" button (OAuth, pick the brand channel). See
   connected/expired status and reconnect with one click.
3. Drag-and-drop a batch of videos onto a channel → each file shows a card with progress,
   auto-detected type (Short = vertical/square and ≤ 180 s, else Long), and an auto-assigned
   next free slot (Shorts Mon–Sat 19:00, Long Sun 19:00 IST).
4. Click "✨ Draft with AI" on one card or "Draft all" → Claude writes title, description, tags
   (and suggests a playlist) using the channel's profile + optional notes I type. I edit, then
   mark **Ready** (or "Ready all").
5. Optionally attach a thumbnail and caption files (.srt, with language) to a video.
6. Calendar shows all channels (colour per channel). Drag a post to a new date/time to reschedule —
   works before upload (DB only) and after upload (updates `publishAt` on YouTube).
7. Dashboard: next 7 days, errors needing attention, quota used today, audit status banner.
8. Get an email summary after each worker run that did something; see the same in an Activity log.
9. Everything also appears in the Google Sheet; edits to not-yet-uploaded rows in the Sheet come
   back into the app.
10. "Upload now" button to run the worker immediately instead of waiting for the schedule.

## 2. Pages
| Route | Purpose |
|---|---|
| `/login` | Google Sign-In |
| `/` Dashboard | Upcoming 7 days, errors, quota meters (uploads x/100, units x/10,000), audit banner |
| `/upload` | Channel picker + drop zone, cards with metadata editor, AI buttons, bulk actions |
| `/queue` | Table of all videos; filters (channel, status, type, date); side drawer to edit |
| `/calendar` | FullCalendar month/week, drag-to-reschedule, click opens drawer |
| `/channels` | Connect/reconnect; per-channel defaults; slot rules; AI profile (audience, tone, language, hashtags, kids-safe) |
| `/settings` | Notify email, Sheet ID + sync toggle, timezone, AUDIT_APPROVED toggle, worker frequency |
| `/activity` | Log of worker runs and per-video events |
| `/privacy`, `/terms` | Public pages (needed for OAuth consent + YouTube audit) |

## 3. Architecture
```
Browser ──HTTPS──> Cloud Run service "web" (FastAPI + Jinja/HTMX)
   │                    │  Firestore (channels, videos, runs, settings, quota)
   │ signed resumable   │  Secret Manager (OAuth client, Fernet key, Anthropic key)
   └──PUT──> Cloud Storage bucket  yt-staging-<project>   (lifecycle: delete 14 days after upload)
                        │
Cloud Scheduler (every 15 min) ──> Cloud Run job "worker" (same image, `python -m worker.run`)
                        ├─ YouTube Data API v3 (per-channel tokens)
                        ├─ Sheets API (mirror) · Gmail API (summary)
                        └─ updates Firestore
"Upload now" button ──> web calls Run Admin API `jobs.run` for the worker
```

## 4. Data model (Firestore)
**channels/{channelId}**: title, handle, colour, connected (bool), token_enc, token_status
(`ok|expired|revoked`), defaults {made_for_kids, ai_content, category_id, language,
notify_subscribers, default_playlist}, slot_rules [{type: Short|Long, weekdays:[0..6], time:"19:00"}],
ai_profile {audience, tone, language, title_style, hashtags[], banned_words[], kids_safe},
playlists_cache {name: id}, updated_at.

**videos/{id}**: channel_id, type, status (`draft|ready|uploading|scheduled|published|error|skipped`),
gcs_path, original_filename, size_bytes, duration_s, width, height,
title, description, tags[], playlist, category_id, language, made_for_kids, ai_content,
notify_subscribers, publish_at (UTC), thumbnail_gcs_path, captions [{lang, gcs_path}],
notes (user brief for AI), ai_drafted (bool), youtube_video_id, youtube_url, uploaded_at,
warnings[], error, attempts, sheet_row, created_at, updated_at, claimed_by, claimed_at.

**runs/{id}**: started_at, finished_at, trigger (`schedule|manual`), uploaded[], errors[],
quota_stop (reason|null), emailed (bool).

**quota/{YYYY-MM-DD PT}**: uploads_used, units_used.

**settings/app**: notify_email, sheet_id, sheet_sync, timezone, audit_approved, account_token_enc.

## 5. Key flows
**Connect channel**: `/auth/channel/start` → Google OAuth (web client, scope
`youtube.force-ssl`, `access_type=offline`, `prompt=select_account consent`) → callback →
`channels.list(mine=true)` → upsert channel by ID, encrypt and store token. If the handle isn't one
of the 4 expected, warn but allow.

**Connect account (Sheets + Gmail)**: same pattern, scopes `spreadsheets`, `gmail.send`
(Drive no longer needed — files come through Cloud Storage).

**Upload from browser**: client reads duration/width/height via a hidden `<video>` element →
POST `/api/videos/init` (filename, size, channel, metadata) → server creates a draft doc, assigns
a slot, returns a signed resumable URL → browser PUTs the file with a progress bar → POST `/complete`.
Bucket CORS must allow the web origin.

**Slot assignment** (`services/scheduling.py`): for a channel + type, walk forward from tomorrow and
return the first slot matching slot_rules that has no non-skipped video of that channel+type.
Bulk drop assigns in filename order. Unit-test thoroughly (week boundaries, DST-free IST, mixed types).

**AI drafting** (`services/ai.py`): input = channel ai_profile, type (Short/Long), filename,
user notes, previous 5 titles on that channel (avoid repeats). Output strict JSON
`{title, description, tags[], playlist_suggestion, hashtags[]}`, validated: title ≤ 100 chars,
no `<` `>`, description ≤ 4,800 chars, tags total ≤ 480 chars; retry once on invalid JSON.
Kids channels: simple language, no external links, no calls to action aimed at children,
COPPA-safe. Shorts: description short + `#Shorts`. Show cost-free "regenerate" and keep the user's
manual edits if they've changed a field (only fill empty fields on "Draft all").

**Worker** (`worker/run.py`): pull Sheet edits (if enabled) → select `ready` videos ordered by
publish_at → for each, Firestore transaction claim → validate (reuse `build_job`) → stream file
from GCS to YouTube with resumable upload (download to /tmp is acceptable for ≤ 100 MB; set job
memory 2 GiB) → thumbnail → playlist (create if missing) → captions → mark `scheduled` with
URL/warnings → push to Sheet → after loop, email summary if anything happened. Reuse the CLI's
rule: quota errors after the video exists become warnings, never re-uploads. Rows stuck in
`uploading` for > 2 h are flagged on the dashboard (not auto-retried).
Daily (first run after 00:00 IST): mark `scheduled` videos whose publish_at has passed as
`published` (videos.list, 1 unit per 50 IDs) and delete their GCS files after 14 days.

**Reschedule**: calendar drop → if not uploaded: update publish_at. If scheduled on YouTube and
new time is ≥ 20 min ahead: `videos.update(part=status)` with full status object (privacyStatus
private + new publishAt + kids/AI flags, so nothing is wiped). If already published: refuse.

**Sheet sync** (`services/sheets.py`): app is source of truth. Push on every change (debounced in
worker + immediate for single edits). Pull: for rows whose status is draft/ready, compare editable
columns; if the Sheet's "Last edited" (Apps-Script-free approach: compare against stored hash of
last pushed values) differs, apply Sheet values and log it. Never pull into uploaded rows.
Same column layout as the current template.

**Token health**: on `invalid_grant`, mark channel `token_status=expired`, error the affected
videos with "Reconnect channel", show red badge, include in email.

## 6. Non-functional
- Single user, low traffic: Cloud Run min instances 0; expect ₹0–200/month (Firestore + GCS free tiers).
- Mobile-friendly layout (check dashboard + calendar on phone width).
- All times shown in IST with the day name ("Sun 30 Nov, 7:00 PM").
- Accessibility basics: labels on inputs, keyboard-usable drawer, colour + text for status.
- Logging: structured JSON logs, no PII/tokens.

## 7. Out of scope for v1
Analytics, comment management, multi-user, TikTok/Instagram cross-posting, auto-transcription
(v2: Whisper/Gemini transcript → better AI drafts + auto captions), A/B thumbnails.

## 8. Environment variables
`GOOGLE_CLOUD_PROJECT, REGION, GCS_BUCKET, ALLOWED_EMAILS, SESSION_SECRET, FERNET_KEY,
OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, BASE_URL, ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
WORKER_JOB_NAME, AUDIT_APPROVED, TZ=Asia/Kolkata` (secrets via Secret Manager in prod, `.env` locally).
