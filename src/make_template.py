"""Build the schedule template (Excel) to import into Google Sheets.

    python src/make_template.py 2026-11-23 4     # start date (a Monday), number of weeks
"""
import sys
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, str(Path(__file__).parent))
from common import CATEGORY_IDS, ROOT, load_config  # noqa: E402
from uploader import COLS  # noqa: E402

WIDTHS = {"Status": 11, "Channel": 18, "Type": 7, "Video File": 26, "Title": 40, "Description": 45,
          "Tags": 28, "Playlist": 20, "Publish Date": 12, "Publish Time": 11, "Made For Kids": 9,
          "AI Content": 9, "Thumbnail File": 24, "Captions": 26, "Category": 18, "Language": 9,
          "Notify Subscribers": 9, "Video ID": 14, "Video URL": 28, "Uploaded At": 16, "Notes": 40}

INSTRUCTIONS = [
    ("HOW TO USE", ""),
    ("1", "Put each video (and thumbnail / .srt files) in its channel's folder in Google Drive: "
          "YouTube Uploads/<Channel name>/"),
    ("2", "Fill a row: Video File = exact file name in that folder (e.g. 2026-11-23_Short.mp4). "
          "Title is required. Description, Tags (comma separated), Playlist are optional."),
    ("3", "Publish Date = YYYY-MM-DD, Publish Time = 24h HH:MM in India time (19:00 = 7 PM)."),
    ("4", "Leave Made For Kids / AI Content / Category / Language / Notify blank to use the channel "
          "default from config.yaml, or type Yes / No to override."),
    ("5", "Captions: language:filename pairs separated by ;   e.g.  en:2026-11-23_en.srt; hi:2026-11-23_hi.srt"),
    ("6", "When a row is complete, change Status from Draft to Ready. The uploader only touches Ready rows."),
    ("7", "The script fills Video ID, Video URL, Uploaded At, and sets Status to Scheduled "
          "(or Error + a reason in Notes). Fix an Error row and set it back to Ready."),
    ("", ""),
    ("STATUS VALUES", "Draft = not ready · Ready = upload on next run · Uploading = in progress · "
                      "Scheduled = done · Error = see Notes · Skip = ignore"),
    ("LIMITS", "Title ≤ 100 chars · Description ≤ 5000 · no < or > characters · Shorts: vertical, ≤ 3 min"),
    ("THUMBNAILS", "JPG/PNG, 1280×720, under 2 MB. Channel must be phone-verified (youtube.com/verify). "
                   "Usually skip for Shorts."),
]


def main():
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 11, 23)
    weeks = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    cfg = load_config()
    names = [c["name"] for c in cfg["channels"]]

    wb = Workbook()
    ws = wb.active
    ws.title = "Uploads"
    ws.append(COLS)
    head_fill = PatternFill("solid", fgColor="1F3864")
    auto_fill = PatternFill("solid", fgColor="E7E6E6")
    for i, c in enumerate(COLS, start=1):
        cell = ws.cell(row=1, column=i)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = auto_fill if c in ("Video ID", "Video URL", "Uploaded At", "Notes") else head_fill
        if c in ("Video ID", "Video URL", "Uploaded At", "Notes"):
            cell.font = Font(bold=True, color="000000")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[cell.column_letter].width = WIDTHS.get(c, 14)
    ws.freeze_panes = "C2"

    # Default rhythm: Shorts Mon–Sat, one Long video on Sunday, 7 PM, every channel.
    for d in range(weeks * 7):
        day = start + timedelta(days=d)
        kind = "Long" if day.weekday() == 6 else "Short"
        for n in names:
            row = {c: "" for c in COLS}
            row.update({"Status": "Draft", "Channel": n, "Type": kind,
                        "Video File": f"{day.isoformat()}_{kind}.mp4",
                        "Publish Date": day.isoformat(), "Publish Time": "19:00"})
            ws.append([row[c] for c in COLS])

    last = ws.max_row + 300
    def dv(col, options):
        v = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
        letter = ws.cell(row=1, column=COLS.index(col) + 1).column_letter
        v.add(f"{letter}2:{letter}{last}")
        ws.add_data_validation(v)
    dv("Status", ["Draft", "Ready", "Uploading", "Scheduled", "Error", "Skip"])
    dv("Channel", names)
    dv("Type", ["Short", "Long"])
    for c in ("Made For Kids", "AI Content", "Notify Subscribers"):
        dv(c, ["Yes", "No"])
    # Category list is too long for an inline dropdown, so it lives on a "Lists" tab.
    lists = wb.create_sheet("Lists")
    for i, c in enumerate(sorted(k.title() for k in CATEGORY_IDS), start=1):
        lists.cell(row=i, column=1, value=c)
    cv = DataValidation(type="list", formula1=f"=Lists!$A$1:$A${len(CATEGORY_IDS)}", allow_blank=True)
    letter = ws.cell(row=1, column=COLS.index("Category") + 1).column_letter
    cv.add(f"{letter}2:{letter}{last}")
    ws.add_data_validation(cv)

    for r in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in r:
            cell.alignment = Alignment(vertical="top")
            cell.number_format = "@"  # keep dates/times as plain text so the script reads them exactly

    ins = wb.create_sheet("How to use")
    ins.column_dimensions["A"].width = 16
    ins.column_dimensions["B"].width = 120
    for a, b in INSTRUCTIONS:
        ins.append([a, b])
        ins.cell(row=ins.max_row, column=1).font = Font(bold=True)
        ins.cell(row=ins.max_row, column=2).alignment = Alignment(wrap_text=True)

    ch = wb.create_sheet("Channels")
    ch.append(["Channel", "Handle", "Drive folder", "Made for kids", "AI content", "Category", "Language"])
    for c in cfg["channels"]:
        ch.append([c["name"], c["handle"], c["drive_folder"], "Yes" if c["made_for_kids"] else "No",
                   "Yes" if c["ai_content"] else "No", c["category"], c["language"]])
    for cell in ch[1]:
        cell.font = Font(bold=True)
    for col in "ABCDEFG":
        ch.column_dimensions[col].width = 20

    out = ROOT / "YouTube_Upload_Schedule.xlsx"
    wb.save(out)
    print("Saved", out)


if __name__ == "__main__":
    main()
