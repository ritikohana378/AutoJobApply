# Auto Job Apply (LinkedIn)

Auto Job Apply is a Python-based LinkedIn automation tool that discovers, evaluates, and applies to relevant Easy Apply roles using Playwright Chromium, a Flask monitoring dashboard, dynamic `resume.txt` parsing, and Google Gemini AI for form-filling.

It is designed to help you:

- search and apply to relevant LinkedIn Easy Apply jobs across global tech and banking hubs
- filter out irrelevant domains and overly senior roles before applying
- evaluate job fit dynamically against your live `resume.txt`
- answer multi-step Easy Apply screening questions automatically using the Gemini API
- track all applications locally in SQLite to prevent duplicate submissions
- monitor progress through a lightweight Flask dashboard while keeping a visible browser window for human-in-the-loop checkpoints

## Why this project exists

Applying to international roles manually involves repeating the same search filters, screening forms, and experience calculations across dozens of listings. This project automates the repetitive browser workflow while enforcing strict role/experience guardrails and pausing cleanly whenever LinkedIn prompts for login, 2FA, or CAPTCHA verification.

## Key features

- **LinkedIn Easy Apply automation:** Targets jobs posted within the **past week** (`f_TPR=r604800`) with **Easy Apply** enabled (`f_AL=true`) across GCC (Saudi Arabia, UAE/Dubai, Qatar, Oman, Kuwait, Bahrain), European (UK, Switzerland, Germany, Netherlands, Ireland, Luxembourg, Austria, France, Belgium, Spain, Poland), and APAC/North American (Singapore, Hong Kong, Malaysia, Australia, Canada) hubs.
- **Smart role & seniority filtering:** Automatically targets Software Development, Backend Engineering, Implementation Engineering, Application/Production Support, Software/Technical Consulting, and Core Banking roles while skipping Accounting, Finance, Pre-Sales, Sales, Project Management, HR, Staff, Manager, Principal, Director, VP, and roles requiring more than **4 years** of experience.
- **Live `resume.txt` parsing & fit scoring:** Reads `resume.txt` directly from disk on every job so updates take effect immediately without restarting. Combines resume keyword overlap with Gemini semantic fit scoring against your `MATCH_THRESHOLD`.
- **AI-powered screening form filler:** Auto-discovers active Gemini Flash models to fill text inputs, numeric fields, dropdowns, React SDUI radio button groups, and required checkboxes. Automatically skips CGPA/GPA fields, preserves pre-filled contact info, and converts your target salary (`TARGET_SALARY_LACS_PKR`) into each country's local currency.
- **Visible Chromium & persistent sessions:** Launches Chromium in non-headless mode using `chrome_user_data/` so login cookies persist across runs, with automatic `.env` credential login and a human-in-the-loop pause for 2FA/CAPTCHA checkpoints.
- **Flask web dashboard & SQLite tracking:** Monitor live status at `http://localhost:5000` and track applied/external jobs in `jobs.db` with a configurable `DAILY_LIMIT`.
- **Optional Chrome extension:** Bundled extension in `extension/` for manual form autofill assistance.

## Tech stack

- Python 3.12+
- Playwright (Chromium browser automation)
- Google Gemini API (`google-generativeai`)
- Flask
- SQLite
- `python-dotenv`

## Repository structure

```text
.
├── app.py                # Flask web dashboard entry point
├── main.py               # CLI automation and diagnostics entry point
├── config.py             # Environment variables, thresholds, daily limits, and job titles
├── db.py                 # SQLite database helpers (jobs.db)
├── gemini_engine.py      # Gemini API client, live resume parser, fit scoring, and salary conversion
├── hitl_engine.py        # Human-in-the-loop pause/resume logic
├── linkedin_driver.py    # Playwright LinkedIn Easy Apply automation driver
├── resume_matcher.py     # Local resume loader and matcher helper
├── resume.txt            # Your plain-text resume (read live on every job)
├── requirements.txt      # Python package dependencies
├── .env                  # Local secrets (API key & LinkedIn credentials — never commit)
├── chrome_user_data/     # Persistent Chromium profile cookies/session
├── extension/            # Optional Chrome extension source
└── templates/            # Flask dashboard HTML templates
```

## Prerequisites

- Python 3.12 or newer
- A Google Gemini API key (from Google AI Studio)
- A LinkedIn account
- Terminal access with `pip`

## Installation

1. **Clone the repository** and navigate into the project directory:

```bash
git clone <your-repo-url>
cd Auto_job_apply-main
```

2. **Create and activate a virtual environment:**

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Install Python dependencies:**

```bash
pip install -r requirements.txt
```

*(If installing manually without `requirements.txt`: `pip install flask playwright google-generativeai python-dotenv scikit-learn`)*

4. **Install Playwright's Chromium browser binary:**

```bash
playwright install chromium
```

## Configuration

### 1. Create `.env`

Create a `.env` file in the project root with your Gemini API key and LinkedIn credentials:

```env
GEMINI_API_KEY=your_gemini_api_key_here
LINKEDIN_EMAIL=your_linkedin_email@example.com
LINKEDIN_PASSWORD=your_linkedin_password_here
```

### 2. Add your resume (`resume.txt`)

Paste your full plain-text resume into `resume.txt` in the project root. The engine parses your contact info, skills, and work-experience timeline dynamically from this file on every job—you can edit and save `resume.txt` anytime without restarting the server.

### 3. Tune search & matching settings (`config.py` & `gemini_engine.py`)

- **`config.py`:** Adjust `JOB_TITLES`, `MATCH_THRESHOLD` (default `65.0`), and `DAILY_LIMIT` (default `30`).
- **`gemini_engine.py`:** Adjust `TARGET_SALARY_LACS_PKR` (auto-converted to local currencies like SGD, AED, SAR, EUR, GBP, CHF), `MAX_ALLOWED_EXPERIENCE_YEARS` (default `4`), or set `OVERRIDE_TOTAL_YOE` to pin a fixed years-of-experience integer.

## Running the project

Make sure your virtual environment is active (`(venv)` visible in your terminal).

### 1. Run diagnostics check

Verify your environment, database, config, and dependencies before launching:

```bash
python main.py --mode test
```

### 2. Launch the web dashboard (Recommended)

```bash
python main.py --mode web
```

*(Or run Flask directly via `python app.py`.)*

Open your browser and go to:

```text
http://localhost:5000
```

Click **Start Automation** to launch Chromium and monitor progress in real time.

### 3. Run via CLI

```bash
python main.py --mode cli --platform linkedin
```

## Chrome extension (Optional)

A bundled Chrome extension is included in `extension/`. Load it manually by opening `chrome://extensions/`, enabling **Developer mode**, clicking **Load unpacked**, and selecting the `extension/` folder (or running `LOAD_EXTENSION.bat` on Windows).

## Environment and data files

Keep the following local files and folders in `.gitignore` so credentials and session data are never pushed to GitHub:

- `.env` — API key and LinkedIn login credentials
- `chrome_user_data/` — persistent Chromium cookies and session state
- `jobs.db` — local SQLite application log
- `venv/` — Python virtual environment

## Notes on usage

- **First-time login:** On your first run (or after clearing `chrome_user_data/`), the script opens LinkedIn and signs in using `.env`. If LinkedIn triggers a CAPTCHA or 2FA code, complete it manually in the visible Chromium window—automation will detect the logged-in feed and resume automatically.
- **Persistent sessions:** Subsequent runs reuse cookies saved in `chrome_user_data/` to avoid repeated logins.
- **Daily cap:** Applications stop automatically once `DAILY_LIMIT` is reached for the current date in `jobs.db`.

## Safety and compliance

Use this project responsibly and only on accounts where you have permission to automate job applications. Respect LinkedIn's terms of use, keep `DAILY_LIMIT` reasonable, and avoid excessive request rates.

## License

This project is provided under the repository license included in the project root.

## Contributing

Pull requests and improvements are welcome. Keep `README.md` up to date when adding configuration options or driver changes, and verify changes with `python main.py --mode test`.