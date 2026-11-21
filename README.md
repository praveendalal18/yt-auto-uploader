# YouTube Auto-Uploader (4 channels)

This script uploads and schedules videos to **Ink & Motion, Mirrorkin Press, Kidz Curious Labs and AIPraveen**. It takes the files from a Google Drive folder and the details from a Google Sheet.

**How it works:** you drop videos into Drive, fill one row per video in the Google Sheet, and set the row's Status to **Ready**. Every 3 hours a cloud job:

1. Uploads each Ready video to the right channel.
2. Schedules it for the date and time in the row (7 PM IST by default).
3. Adds the thumbnail, playlist and captions.
4. Writes the YouTube link back into the sheet.
5. Emails you a summary.

YouTube itself publishes each video at the scheduled time, so a whole week or month can be uploaded in advance.

```
config.yaml                 ← channel defaults (kids flag, AI flag, category…) – edit this
src/auth_setup.py           ← one-time login per channel (run on your laptop)
src/uploader.py             ← the job
src/make_template.py        ← builds the schedule template
deploy/deploy_cloud_run.sh  ← puts the job on Google Cloud, every 3 hours
.github/workflows/upload.yml← alternative: run on GitHub instead
```

---

## Part 1 — Google Cloud setup (≈30 min, one time)

Sign in as **pravendalal@gmail.com** at <https://console.cloud.google.com>.

1. **Create a project.** Use the project picker → New project. Name it `yt-auto-uploader`.
2. **Enable 4 APIs.** Go to APIs & Services → Library and enable:
   - **YouTube Data API v3**
   - **Google Drive API**
   - **Google Sheets API**
   - **Gmail API**
3. **Set up the OAuth consent screen.** Go to Google Auth Platform → Branding / Audience:
   - User type: **External**.
   - App name: `Praveen YouTube Uploader`. Support email: your Gmail.
   - Under **Audience**, click **Publish app** so the status becomes **In production**. Skip this and logins expire every 7 days.
   - You'll later see a "Google hasn't verified this app" screen. That's normal for a personal tool: click **Advanced → Go to … (unsafe)**.
4. **Create OAuth credentials.** Go to Clients → Create client → **Desktop app**. Download the JSON, rename it `client_secret.json`, and put it in this project folder.
5. **Submit the YouTube API audit.** Do this today, because it's what lifts the private lock.
   - Form: search "YouTube API Services Audit and Quota Extension Form".
   - Describe it as: *an internal tool used only by me to schedule uploads to my own 4 channels, single user, no third-party access, no data stored beyond video IDs*.
   - Give your project number (Dashboard).
   - They usually ask for a **privacy policy URL**. A simple page on aipraveen.com works.
   - A short screen recording of the script and sheet helps.

   > Until the audit is approved, **every video uploaded through the API is locked private and can never be made public**. Test only with throwaway clips, not real episodes.

## Part 2 — Drive folder and Google Sheet

1. **Create the Drive folder.** In Google Drive, make a folder **YouTube Uploads** with 4 sub-folders named *exactly*:
   - `Ink & Motion`
   - `Mirrorkin Press`
   - `Kidz Curious Labs`
   - `AIPraveen`

   Open *YouTube Uploads*. The ID at the end of the URL (`…/folders/THIS_PART`) is your **DRIVE_FOLDER_ID**.
2. **Create the Google Sheet.** Make a new Google Sheet → File → Import → upload `YouTube_Upload_Schedule.xlsx` → **Replace spreadsheet**. The ID in its URL (`…/d/THIS_PART/edit`) is your **SHEET_ID**.
3. **Check the date columns.** In the sheet, select columns *Publish Date* and *Publish Time* → Format → Number → **Plain text**. That way Google doesn't reformat them.

The template already has 4 weeks of rows: Shorts Mon–Sat and one Long video every Sunday, 7 PM, for each channel. Video file names are pre-filled as `YYYY-MM-DD_Short.mp4` / `YYYY-MM-DD_Long.mp4`. Name your files that way, or change the cell.

## Part 3 — Log in to the 4 channels (on your laptop, ≈10 min)

You need Python 3.12+ (<https://python.org>, tick "Add to PATH"). Then, in a terminal inside this folder:

```powershell
pip install -r requirements.txt
python src/auth_setup.py account     # pick pravendalal@gmail.com
python src/auth_setup.py channel     # pick Ink & Motion
python src/auth_setup.py channel     # pick Mirrorkin Press
python src/auth_setup.py channel     # pick Kidz Curious Labs
python src/auth_setup.py channel     # pick AIPraveen
python src/auth_setup.py list        # should show all 4 + main account
```

This creates `tokens/tokens.json`. **Treat it like a password.** Never email it or put it in a public place. If it ever leaks, go to <https://myaccount.google.com/permissions> and remove the app.

## Part 4 — Test locally

```powershell
$env:SHEET_ID="your-sheet-id"
$env:DRIVE_FOLDER_ID="your-folder-id"
python src/uploader.py --dry-run      # checks Ready rows, uploads nothing
python src/uploader.py --row 2        # really uploads just row 2 (use a test clip!)
```

## Part 5 — Put it in the cloud

**Option A: Google Cloud Run (recommended).** The project needs a billing account attached. At this volume the cost should be about ₹0, because it stays inside the free tier.

1. Install the gcloud CLI and run `gcloud auth login`.
2. Edit the 4 values at the top of `deploy/deploy_cloud_run.sh`.
3. Run it from Git Bash or Cloud Shell: `bash deploy/deploy_cloud_run.sh`
4. Test it: `gcloud run jobs execute yt-uploader --region asia-south1 --wait`

**Option B: GitHub Actions (no billing card).**

1. Push this folder to a **private** GitHub repo. `.gitignore` already keeps tokens out.
2. Add 3 repo secrets: `TOKENS_JSON` (paste the whole tokens file), `SHEET_ID`, `DRIVE_FOLDER_ID`.
3. It runs every 3 hours, and there's a "Run workflow" button for manual runs.

## Your weekly routine

1. Drop the week's videos (plus thumbnails and .srt files) into the channel folders.
2. Fill Title, Description, Tags, Playlist and so on, then set Status = **Ready**.
3. Wait for the email. Rows turn **Scheduled** with a link, or **Error** with the reason in *Notes*. Fix the row and set it back to Ready.

## Sheet columns

| Column | What to put |
|---|---|
| Status | Draft / **Ready** / Skip (the script sets Uploading, Scheduled, Error) |
| Channel | Dropdown: one of the 4 channels |
| Type | Short / Long (for your reference; YouTube detects Shorts from vertical video ≤ 3 min) |
| Video File | Exact file name in that channel's Drive folder |
| Title | Required, ≤ 100 characters, no `<` `>` |
| Description | Optional, ≤ 5000 characters |
| Tags | Comma separated |
| Playlist | Playlist name; created automatically if it doesn't exist |
| Publish Date / Time | `2026-11-23` / `19:00` (India time) |
| Made For Kids / AI Content | Yes / No; blank = channel default |
| Thumbnail File | JPG/PNG, 1280×720, < 2 MB (channel must be phone-verified) |
| Captions | `en:file_en.srt; hi:file_hi.srt` |
| Category / Language / Notify Subscribers | Blank = channel default |

## Limits worth knowing

- **Uploads:** 100 per day per project, which is plenty for ~32/week. If you bulk-load a month (~128), the script pauses at the limit and continues on the next run.
- **Everything else** (thumbnail 50, playlist 50, **each caption file 400**) shares 10,000 units per day. In practice that's ~20 videos with 2 caption files each per day. If quota runs out after a video is up, the video is **not** re-uploaded. The missing step is noted in *Notes* so you can add it in Studio.
- **Made for kids** videos get comments and some features turned off by YouTube. That's expected for Kidz Curious Labs and Mirrorkin Press.
- **Uploading stuck:** if a row stays "Uploading" (a crashed run), check YouTube Studio before setting it back to Ready, so you don't upload it twice.

---

# Web app (in progress — Phases 1–2: sign-in + channels)

A private web app is being built on top of the script above (see `docs/SPEC.md` and `docs/BUILD_PLAN.md`).
The script keeps working as before while that happens.

## Try it on your laptop (Windows PowerShell)

**1. One-time: Google sign-in client.** In Google Cloud Console → *APIs & Services* → *Credentials* →
*Create credentials* → *OAuth client ID* → type **Web application**. Under *Authorised redirect URIs* add
`http://localhost:8000/auth/callback`. Copy the Client ID and Client secret.

**2. One-time: install.** Open PowerShell in the project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Open `.env` in Notepad (`notepad .env`) and fill in:
- `SESSION_SECRET` = the long random line the last command printed
- `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` = from step 1
- `ALLOWED_EMAILS` = the Google account(s) allowed in

- `FERNET_KEY` = the output of
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  (this key encrypts your channel logins; store a copy somewhere safe)

The app keeps its data in Firestore. Let your laptop use it (one-time, opens a browser):

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project yt-auto-uploader
```

**3. Run it:**

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

Open http://localhost:8000. Sign in with your allowed account to reach the dashboard; any other Google
account gets "Access denied". Stop the server with `Ctrl+C`.

**Connect your channels:** go to *Channels* → **Connect** → choose pravendalal@gmail.com → pick the
channel (e.g. Ink & Motion) on Google's screen → allow. Repeat for each channel, then **Connect account**
once for Sheets + Gmail. The logins saved by the old script (`tokens/tokens.json`) belong to a different
OAuth client, so they can't be reused here; connecting again takes a minute per channel.
If a connection ever shows **Expired**, click **Reconnect**. *Check connections now* re-tests them all.

**Run the checks** (they also run automatically on GitHub for every push):

```powershell
pytest -q
ruff check .
```

## Daily database keep-alive

`.github/workflows/db-ping.yml` calls the deployed app's `/healthz/db` once a day (08:47 IST). The app then
writes and reads one tiny Firestore document (`system/heartbeat`). The workflow skips quietly until the
app is deployed (Phase 7) and you add two repository secrets: `APP_URL` (the Cloud Run URL) and
`PING_TOKEN` (the same value as the app's `PING_TOKEN` setting). Note: GitHub pauses scheduled workflows
in a repo with no activity for 60 days; re-enable it from the *Actions* tab if that happens.
