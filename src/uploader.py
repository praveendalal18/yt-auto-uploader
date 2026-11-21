"""YouTube Auto-Uploader — main job.

Reads the Google Sheet, uploads every row whose Status is "Ready",
schedules it, adds thumbnail / playlist / captions, writes results back,
and emails a summary.

    python src/uploader.py              # normal run
    python src/uploader.py --dry-run    # check the sheet only, upload nothing
    python src/uploader.py --row 12     # process only sheet row 12

Environment variables: SHEET_ID, DRIVE_FOLDER_ID (required),
TOKENS_FILE, CONFIG_FILE (optional).
"""
import argparse
import base64
import io
import os
import random
import re
import tempfile
import time
import traceback
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from common import CATEGORY_IDS, account_services, load_config, load_tokens, youtube_for_handle

# Sheet columns (header text must match row 1 of the "Uploads" tab).
COLS = [
    "Status", "Channel", "Type", "Video File", "Title", "Description", "Tags",
    "Playlist", "Publish Date", "Publish Time", "Made For Kids", "AI Content",
    "Thumbnail File", "Captions", "Category", "Language", "Notify Subscribers",
    "Video ID", "Video URL", "Uploaded At", "Notes",
]
RETRYABLE = {500, 502, 503, 504}
QUOTA_REASONS = {"quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded", "rateLimitExceeded"}


class QuotaHit(Exception):
    pass


class RowError(Exception):
    pass


# ----------------------------------------------------------------- helpers
def col_letter(idx):
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def yes_no(value, default):
    v = (value or "").strip().lower()
    if v in ("yes", "y", "true", "1"):
        return True
    if v in ("no", "n", "false", "0"):
        return False
    return default


DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y"]
TIME_FORMATS = ["%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p", "%I %p", "%I:%M%p", "%I%p"]


def parse_publish(date_s, time_s, tz):
    date_s, time_s = (date_s or "").strip(), (time_s or "").strip().upper()
    d = t = None
    for f in DATE_FORMATS:
        try:
            d = datetime.strptime(date_s, f).date()
            break
        except ValueError:
            pass
    for f in TIME_FORMATS:
        try:
            t = datetime.strptime(time_s, f).time()
            break
        except ValueError:
            pass
    if d is None:
        raise RowError(f"Can't read Publish Date '{date_s}' (use YYYY-MM-DD)")
    if t is None:
        raise RowError(f"Can't read Publish Time '{time_s}' (use HH:MM, e.g. 19:00)")
    return datetime.combine(d, t, tzinfo=ZoneInfo(tz))


def http_reason(err):
    try:
        return err.error_details[0].get("reason", "") if err.error_details else ""
    except Exception:
        return ""


def check_quota(err):
    if isinstance(err, HttpError) and http_reason(err) in QUOTA_REASONS:
        raise QuotaHit(http_reason(err))


# ----------------------------------------------------------------- Drive
class Drive:
    def __init__(self, svc, root_id):
        self.svc, self.root_id, self._folders = svc, root_id, {}

    @staticmethod
    def _q(s):
        return s.replace("\\", "\\\\").replace("'", "\\'")

    def folder(self, name):
        if name not in self._folders:
            res = self.svc.files().list(
                q=f"'{self.root_id}' in parents and name='{self._q(name)}' and "
                  "mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute().get("files", [])
            if not res:
                raise RowError(f"Drive folder '{name}' not found inside the uploads folder")
            self._folders[name] = res[0]["id"]
        return self._folders[name]

    def find(self, folder_name, file_name):
        res = self.svc.files().list(
            q=f"'{self.folder(folder_name)}' in parents and name='{self._q(file_name)}' and trashed=false",
            fields="files(id,name,size)", supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute().get("files", [])
        if not res:
            raise RowError(f"File '{file_name}' not found in Drive folder '{folder_name}'")
        return res[0]

    def download(self, file_id, dest):
        req = self.svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        with io.FileIO(dest, "wb") as fh:
            dl = MediaIoBaseDownload(fh, req, chunksize=16 * 1024 * 1024)
            done = False
            while not done:
                _, done = dl.next_chunk(num_retries=5)
        return dest


# ----------------------------------------------------------------- YouTube
def resumable_upload(request):
    response, attempt = None, 0
    while response is None:
        try:
            _, response = request.next_chunk()
        except HttpError as e:
            check_quota(e)
            if e.resp.status not in RETRYABLE or attempt >= 8:
                raise
            attempt += 1
            time.sleep(min(60, 2 ** attempt + random.random()))
        except (ConnectionError, TimeoutError, OSError):
            if attempt >= 8:
                raise
            attempt += 1
            time.sleep(min(60, 2 ** attempt + random.random()))
    return response


def get_or_create_playlist(yt, cache_key, title, cfg, cache):
    key = (cache_key, title.lower())
    if key in cache:
        return cache[key]
    page = None
    while True:
        res = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=page).execute()
        for p in res.get("items", []):
            cache[(cache_key, p["snippet"]["title"].lower())] = p["id"]
        page = res.get("nextPageToken")
        if not page:
            break
    if key in cache:
        return cache[key]
    if not cfg.get("create_missing_playlists", True):
        raise RowError(f"Playlist '{title}' doesn't exist on the channel")
    p = yt.playlists().insert(part="snippet,status", body={
        "snippet": {"title": title},
        "status": {"privacyStatus": cfg.get("new_playlist_privacy", "public")},
    }).execute()
    cache[key] = p["id"]
    return p["id"]


# ----------------------------------------------------------------- per-row
def build_job(row, cfg, channels, tz, now):
    """Validate one sheet row and return a dict of everything needed to upload it."""
    g = lambda c: (row.get(c) or "").strip()
    ch = channels.get(g("Channel"))
    if not ch:
        raise RowError(f"Unknown Channel '{g('Channel')}' (must match config.yaml)")
    if not g("Video File"):
        raise RowError("Video File is empty")
    title = g("Title")
    if not title:
        raise RowError("Title is empty")
    if len(title) > 100:
        raise RowError(f"Title is {len(title)} characters (max 100)")
    desc = row.get("Description") or ""
    if len(desc.encode("utf-8")) > 5000:
        raise RowError("Description is longer than 5000 bytes")
    if re.search(r"[<>]", title + desc):
        raise RowError("Title/Description can't contain < or >")
    tags = [t.strip() for t in g("Tags").split(",") if t.strip()]
    if len(",".join(tags)) > 480:
        raise RowError("Tags are too long (YouTube limit ~500 characters)")

    publish = parse_publish(g("Publish Date"), g("Publish Time") or cfg["default_publish_time"], tz)
    if publish < now + timedelta(minutes=cfg.get("min_minutes_ahead", 20)):
        raise RowError(f"Publish time {publish:%d %b %Y %H:%M} is in the past / too soon")

    cat = g("Category") or ch.get("category", "Education")
    cat_id = cat if cat.isdigit() else CATEGORY_IDS.get(cat.lower())
    if not cat_id:
        raise RowError(f"Unknown Category '{cat}'")

    captions = []
    for part in re.split(r"[;\n]", g("Captions")):
        if part.strip():
            if ":" not in part:
                raise RowError(f"Captions entry '{part.strip()}' must look like en:file.srt")
            lang, fname = part.split(":", 1)
            captions.append((lang.strip(), fname.strip()))

    lang = g("Language") or ch.get("language", "en")
    return {
        "channel": ch,
        "video_file": g("Video File"),
        "thumbnail": g("Thumbnail File"),
        "playlist": g("Playlist"),
        "captions": captions,
        "publish": publish,
        "notify": yes_no(g("Notify Subscribers"), ch.get("notify_subscribers", True)),
        "body": {
            "snippet": {
                "title": title, "description": desc, "tags": tags, "categoryId": cat_id,
                "defaultLanguage": lang, "defaultAudioLanguage": lang,
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "selfDeclaredMadeForKids": yes_no(g("Made For Kids"), ch.get("made_for_kids", False)),
                "containsSyntheticMedia": yes_no(g("AI Content"), ch.get("ai_content", False)),
                "embeddable": True,
                "license": "youtube",
            },
        },
    }


def process(job, bundle, drive, cfg, playlist_cache, workdir):
    ch = job["channel"]
    yt, saved = youtube_for_handle(bundle, ch["handle"])
    warnings = []
    state = {"quota": None}

    def after_upload_error(step, e):
        # The video is already on YouTube: never re-upload, just record what was skipped.
        if isinstance(e, HttpError) and http_reason(e) in QUOTA_REASONS:
            state["quota"] = http_reason(e)
            warnings.append(f"{step} skipped: daily quota reached — add it in YouTube Studio")
        else:
            warnings.append(f"{step} failed: {short_err(e)}")

    vf = drive.find(ch["drive_folder"], job["video_file"])
    local = drive.download(vf["id"], os.path.join(workdir, "video" + os.path.splitext(vf["name"])[1]))

    req = yt.videos().insert(
        part="snippet,status", body=job["body"], notifySubscribers=job["notify"],
        media_body=MediaFileUpload(local, chunksize=8 * 1024 * 1024, resumable=True),
    )
    video = resumable_upload(req)
    vid = video["id"]
    os.remove(local)

    if job["thumbnail"]:
        try:
            tf = drive.find(ch["drive_folder"], job["thumbnail"])
            tpath = drive.download(tf["id"], os.path.join(workdir, "thumb" + os.path.splitext(tf["name"])[1]))
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(tpath)).execute()
            os.remove(tpath)
        except (HttpError, RowError) as e:
            after_upload_error("thumbnail", e)

    if job["playlist"] and not state["quota"]:
        try:
            pid = get_or_create_playlist(yt, saved["id"], job["playlist"], cfg, playlist_cache)
            yt.playlistItems().insert(part="snippet", body={
                "snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}},
            }).execute()
        except (HttpError, RowError) as e:
            after_upload_error("playlist", e)

    for lang, fname in job["captions"]:
        if state["quota"]:
            warnings.append(f"caption {lang} skipped: daily quota reached")
            continue
        try:
            cf = drive.find(ch["drive_folder"], fname)
            cpath = drive.download(cf["id"], os.path.join(workdir, f"cap_{lang}.srt"))
            yt.captions().insert(part="snippet", body={
                "snippet": {"videoId": vid, "language": lang, "name": "", "isDraft": False},
            }, media_body=MediaFileUpload(cpath, mimetype="application/octet-stream")).execute()
            os.remove(cpath)
        except (HttpError, RowError) as e:
            after_upload_error(f"caption {lang}", e)

    return vid, warnings, state["quota"]


def short_err(e):
    if isinstance(e, HttpError):
        return f"{e.resp.status} {http_reason(e) or ''} {getattr(e, 'reason', '')}".strip()[:200]
    return str(e)[:200]


# ----------------------------------------------------------------- sheet I/O
class Sheet:
    def __init__(self, svc, sheet_id, tab):
        self.svc, self.id, self.tab = svc, sheet_id, tab
        values = svc.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{tab}'!A1:ZZ", valueRenderOption="FORMATTED_VALUE",
        ).execute().get("values", [])
        if not values:
            raise SystemExit(f"Tab '{tab}' is empty")
        self.header = [h.strip() for h in values[0]]
        missing = [c for c in ("Status", "Channel", "Video File", "Title", "Publish Date") if c not in self.header]
        if missing:
            raise SystemExit(f"Sheet is missing columns: {missing}")
        self.rows = []
        for i, vals in enumerate(values[1:], start=2):
            self.rows.append((i, {h: (vals[j] if j < len(vals) else "") for j, h in enumerate(self.header)}))

    def write(self, rownum, **cells):
        data = []
        for name, val in cells.items():
            col = name.replace("_", " ")
            if col in self.header:
                data.append({"range": f"'{self.tab}'!{col_letter(self.header.index(col))}{rownum}",
                             "values": [[val]]})
        if data:
            self.svc.spreadsheets().values().batchUpdate(
                spreadsheetId=self.id, body={"valueInputOption": "RAW", "data": data}).execute()


# ----------------------------------------------------------------- email
def send_summary(gmail, to, lines, subject):
    msg = MIMEText("\n".join(lines), "plain", "utf-8")
    msg["to"], msg["subject"] = to, subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId="me", body={"raw": raw}).execute()


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--row", type=int)
    args = ap.parse_args()

    cfg = load_config()
    tz = cfg.get("timezone", "Asia/Kolkata")
    sheet_id, folder_id = os.environ.get("SHEET_ID"), os.environ.get("DRIVE_FOLDER_ID")
    if not sheet_id or not folder_id:
        raise SystemExit("Set SHEET_ID and DRIVE_FOLDER_ID environment variables")

    bundle = load_tokens()
    svc = account_services(bundle)
    sheet = Sheet(svc["sheets"], sheet_id, cfg.get("sheet_tab", "Uploads"))
    drive = Drive(svc["drive"], folder_id)
    channels = {c["name"]: c for c in cfg["channels"]}
    now = datetime.now(ZoneInfo(tz))

    ok, failed, skipped_quota = [], [], []
    playlist_cache = {}
    quota_hit = None

    ready = [(n, r) for n, r in sheet.rows
             if (r.get("Status") or "").strip().lower() == "ready" and (args.row in (None, n))]
    ready.sort(key=lambda x: (x[1].get("Publish Date", ""), x[1].get("Publish Time", "")))
    print(f"{len(ready)} row(s) marked Ready")

    with tempfile.TemporaryDirectory() as workdir:
        for rownum, row in ready:
            label = f"Row {rownum} [{row.get('Channel')}] {row.get('Title', '')[:60]}"
            if quota_hit:
                skipped_quota.append(label)
                continue
            try:
                job = build_job(row, cfg, channels, tz, now)
                if args.dry_run:
                    print(f"OK (dry run): {label} -> {job['publish']:%d %b %Y %H:%M}")
                    ok.append(f"{label} — valid (dry run)")
                    continue
                sheet.write(rownum, Status="Uploading", Notes="")
                vid, warns, post_quota = process(job, bundle, drive, cfg, playlist_cache, workdir)
                url = f"https://youtu.be/{vid}"
                note = "; ".join(warns)
                sheet.write(rownum, Status="Scheduled", Video_ID=vid, Video_URL=url,
                            Uploaded_At=datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M"), Notes=note)
                ok.append(f"{label}\n    {url}  publishes {job['publish']:%a %d %b %H:%M}"
                          + (f"\n    ⚠ {note}" if note else ""))
                print("Uploaded:", label, url)
                if post_quota:
                    quota_hit = post_quota
            except QuotaHit as e:
                quota_hit = str(e)
                if not args.dry_run:
                    sheet.write(rownum, Status="Ready", Notes=f"Quota reached ({e}); will retry next run")
                skipped_quota.append(label)
            except RowError as e:
                failed.append(f"{label}\n    ✗ {e}")
                if not args.dry_run:
                    sheet.write(rownum, Status="Error", Notes=str(e))
                print("Error:", label, e)
            except Exception as e:  # unexpected — keep going with other rows
                traceback.print_exc()
                failed.append(f"{label}\n    ✗ {short_err(e)}")
                if not args.dry_run:
                    sheet.write(rownum, Status="Error", Notes=short_err(e))

    stuck = [f"Row {n} [{r.get('Channel')}] {r.get('Title', '')[:60]}" for n, r in sheet.rows
             if (r.get("Status") or "").strip().lower() == "uploading"]

    lines = [f"YouTube uploader run — {now:%a %d %b %Y %H:%M} ({tz})", ""]
    if ok:
        lines += [f"✅ Scheduled ({len(ok)}):", *ok, ""]
    if failed:
        lines += [f"❌ Errors ({len(failed)}) — fix the row and set Status back to Ready:", *failed, ""]
    if skipped_quota:
        lines += [f"⏸ Daily quota reached ({quota_hit}); will retry next run:", *skipped_quota, ""]
    if stuck:
        lines += ["⚠ Rows stuck in 'Uploading' from an earlier crashed run — check YouTube Studio, "
                  "then set to Ready or Scheduled:", *stuck, ""]
    if not (ok or failed or skipped_quota or stuck):
        lines.append("Nothing marked Ready.")
    print("\n".join(lines))

    something = ok or failed or skipped_quota or stuck
    if cfg.get("notify_email") and not args.dry_run and (something or cfg.get("email_when_nothing_to_do")):
        subj = f"YouTube uploader: {len(ok)} scheduled, {len(failed)} errors"
        try:
            send_summary(svc["gmail"], cfg["notify_email"], lines, subj)
        except Exception as e:
            print("Could not send email:", short_err(e))


if __name__ == "__main__":
    main()
