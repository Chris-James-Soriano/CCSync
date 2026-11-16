# CCSync — Class Schedule System

CCSync is a Flask-based class scheduling system for the College of Computer
Studies at Laguna State Polytechnic University. A single dean role manages a
shared, persistent class schedule.

## What the project currently does

- Stores accounts, faculty, subjects, sections, rooms, and schedules in SQLite.
- Seeds a starter curriculum for BSCS and BSIT sections across all four years.
- Shows a Monday-through-Sunday master grid in 30-minute increments from 7 AM
  through the 5 PM boundary. First-year sections receive a Sunday NSTP block;
  other regular classes are scheduled Monday through Saturday.
- Lets dean accounts manage faculty, faculty subjects, section subjects, and
  lecture/laboratory rooms, then automatically generate a conflict-free schedule
  with daily load limits and break periods. Before replacing the current
  schedule it runs a pre-flight check; if the data cannot fit the rules, nothing
  is changed and the page explains exactly which sections or faculty to fix.
  Online subjects do not consume in-person load (5 h/day, 2 sessions/day, Mon–
  Sat 07:00–17:00).
- Dean accounts confirm before generating: the confirmation dialog warns that
  Generate replaces ALL current schedule blocks. The schedule is only
  replaced when a complete conflict-free placement exists. Each click uses a
  fresh random seed and never re-applies the current grid when another valid
  arrangement exists, so repeated clicks produce different schedules.
- Lets dean accounts edit/reassign subjects and remove subjects or faculty;
  related schedule blocks and section assignments are cleaned up safely.
- Lets dean accounts pin a subject to one specific room ("Fixed room" on the
  subject form). The generator and manual scheduling only use that room, e.g.
  PATHFIT is held in the CCS Quadrangle only.
- Lets dean accounts bulk-import faculty, sections, and rooms from `.xlsx`
  files (downloadable templates on the Import page). Invalid rows are reported;
  duplicates are skipped. The faculty file can also carry a subject per row
  (Subject Code, Subject Title, Units, Room Type, Delivery, Fixed Room) —
  one subject per row, repeat the faculty on extra rows to add several.
  Existing faculty are not duplicated; their subjects are added to them.
- Supports online subjects, displayed as `Online` instead of a room assignment.
- Lets the dean edit saved schedule entries. Room, faculty, section, day,
  and time conflicts are rejected with feedback.
- Lets the dean export saved schedules as PDF, Excel (`.xlsx`), or PNG.
- Lets dean accounts manage the whole system from a Settings tab: download a
  restorable `.xlsx` backup of everything (schedule, faculty, subjects, sections,
  rooms — never accounts), restore it atomically, or permanently delete every
  scheduled class block with a confirmation dialog ("Delete schedule").
- Hashes account passwords; all pages require authentication.

The initial SQLite file is created in `instance/ccsync.sqlite3`. Set
`CCSYNC_DATABASE` to use a different database path. Starter records are added
only when missing, so user-created records persist across restarts.

## Technology

- **Backend:** Python, Flask, and Jinja
- **Frontend:** HTML, CSS, and JavaScript
- **Exports:** ReportLab (PDF), openpyxl (Excel), and Pillow (PNG)
- **Tests:** pytest

## Project layout

Run the app from this project directory:

```text
backend/
frontend/
tests/
run.py
requirements.txt
```

Flask renders pages from `frontend/templates/` and serves assets from
`frontend/static/`. The routes are implemented with Flask blueprints in
`backend/app/routes/`.

## Run on Windows

From the repository root, open PowerShell and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

Visit <http://127.0.0.1:5000/login>. The development server runs in the
terminal; press **Ctrl+C** to stop it.

If PowerShell prevents environment activation, use Command Prompt:

```cmd
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python run.py
```

## Run tests

From the project directory with the virtual environment activated:

```powershell
python -m pytest
```

## Main pages

| Area | Page | Route |
|---|---|---|
| Account | Login | `/login` |
| Account | Sign up | `/signup` |
| Account | Logout | `/logout` |
| Account | More information | `/more-information` |
| Dean | Master schedule | `/dean/master-schedule` |
| Dean | Faculty and subjects | `/dean/faculty` |
| Dean | Sections and subjects | `/dean/sections` |
| Dean | Rooms | `/dean/rooms` |
| Dean | Export schedules | `/dean/export` |
| Dean | Import data | `/dean/import` |
| Dean | Settings (backup / restore / reset) | `/dean/settings` |
| Dean | Download backup | `/dean/settings/backup` |
| Dean | Restore backup (POST) | `/dean/settings/restore` |
| Dean | Delete schedule (POST) | `/dean/settings/delete-schedule` |

The default database contains starter department records so schedule
generation is available immediately. Create an account on `/signup`, then sign
in at `/login`. Dean generation replaces the current schedule only after every
assigned section-subject can be placed without a room, faculty, or section
overlap.
