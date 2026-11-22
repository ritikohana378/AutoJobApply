# Auto Job Apply (LinkedIn Edition)

A customized, Python-based LinkedIn job application automation tool powered by Playwright Chromium, Flask, SQLite, and the Google Gemini API.

## Origin & Attribution

This project is based on the original open-source repository by **Madan Ayyanavara**:
- **Original Repository:** [https://github.com/MadanAyyanavara/Auto_job_apply](https://github.com/MadanAyyanavara/Auto_job_apply)

Starting from that codebase, this version has been **re-architected and configured exclusively for LinkedIn** (with the Naukri driver removed) and tailored to custom requirements around target roles, global locations, salary conversion, resume parsing, and LinkedIn's updated UI.

---

## Customizations & Modifications Made

Compared to the upstream repository, this customized version includes the following updates:

- **LinkedIn-Only Workflow:** Removed Naukri integration to focus exclusively on LinkedIn Easy Apply (`f_AL=true`) jobs posted within the **past week** (`f_TPR=r604800`).
- **Role & Seniority Filtering:**
  - Targets **Software Development, Backend Engineering, Implementation Engineering, Application/Production Support, Software/Technical Consulting**, and **Core Banking / Payments** roles.
  - Automatically skips unrelated domains (**Accounting, Finance, Pre-Sales, Sales, Project Management, HR, Marketing**) and overly senior titles (**Staff, Manager, Principal, Director, VP, Chief**), as well as roles requiring **more than 4 years of experience**.
- **Expanded Global & GCC Target Locations:** Configured verified LinkedIn Geo IDs across:
  - **GCC / Middle East:** Saudi Arabia, United Arab Emirates (including Dubai), Qatar, Oman, Kuwait, and Bahrain.
  - **Europe:** Switzerland, United Kingdom, Luxembourg, Germany, Netherlands, Ireland, Austria, France, Belgium, Spain, and Poland.
  - **Asia-Pacific & North America:** Singapore, Hong Kong, Malaysia, Australia, and Canada.
- **Location-Aware Salary Conversion:** Converts a configurable target salary in PKR Lacs (`TARGET_SALARY_LACS_PKR`) automatically into each job's local currency (`SAR`, `AED`, `QAR`, `OMR`, `KWD`, `BHD`, `SGD`, `EUR`, `GBP`, `CHF`, `PLN`, `HKD`, `MYR`, `AUD`, `CAD`, `USD`, `PKR`), accounting for monthly vs. annual phrasing.
- **Live `resume.txt` Parsing & Smarter Screening Answers:**
  - Reads `resume.txt` directly from disk on every job so resume edits apply immediately without restarting.
  - Evaluates job fit by combining resume keyword overlap, experience-level compatibility, and Gemini scoring.
  - Dynamically extracts personal contact details from `resume.txt`, protects pre-filled contact fields, skips CGPA/GPA fields, and applies consistent total experience across coding languages and technical tools (Python, Java, C++, InfoBasic, APIs, Docker, SQL, etc.).
  - Handles common HR screening fields cleanly (reasonable adjustments, start availability, country of residence, visa sponsorship, and language proficiency).
- **Updated LinkedIn UI & Gemini Reliability:**
  - Fixed Easy Apply modal handling for LinkedIn's React SDUI `<dialog>` layout, including `<div>`-based radio button groups, dropdowns, character counters, and modal scrolling.
  - Auto-discovers active Gemini Flash models via `list_models()` to avoid deprecated model errors.
  - Runs Chromium in **visible (non-headless) mode** with persistent `chrome_user_data/` sessions and `.env`-based LinkedIn login with human-in-the-loop pauses for 2FA or CAPTCHA checkpoints.

---

## Tech Stack

- **Python 3.12+**
- **Playwright (Chromium)** — browser automation and persistent session management
- **Google Gemini API (`google-generativeai`)** — job fit evaluation and screening question responses
- **Flask** — local web dashboard (`http://localhost:5000`)
- **SQLite** — local tracking (`jobs.db`) to prevent duplicate applications
- **`python-dotenv`** — environment and credential management

---

## Repository Structure

```text
.
├── app.py                # Flask web dashboard entry point
├── main.py               # CLI runner and diagnostics entry point
├── config.py             # Search titles, thresholds, daily limits, and env config
├── db.py                 # SQLite application tracking helpers (jobs.db)
├── gemini_engine.py      # Gemini API client, live resume parser, fit & salary logic
├── hitl_engine.py        # Human-in-the-loop pause/resume support
├── linkedin_driver.py    # Playwright LinkedIn Easy Apply automation driver
├── resume_matcher.py     # Local resume loader helper
├── resume.txt            # Plain-text resume (parsed live on every job)
├── requirements.txt      # Python dependencies
├── .env                  # Local API key & LinkedIn credentials (gitignored)
├── chrome_user_data/     # Persistent Chromium profile & cookies (gitignored)
├── extension/            # Optional Chrome extension for manual autofill
└── templates/            # Flask dashboard HTML templates
```

---

## Prerequisites

- Python 3.12 or newer
- A Google Gemini API key (Google AI Studio)
- A LinkedIn account

---

## Setup & Installation

1. **Clone this repository** and open the project directory:

```bash
git clone <your-repo-url>
cd Auto_job_apply
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

3. **Install dependencies:**

```bash
pip install -r requirements.txt
```

4. **Install Playwright's Chromium browser:**

```bash
playwright install chromium
```

---

## Configuration

### 1. Create `.env`

Add your Gemini API key and LinkedIn credentials in a `.env` file at the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
LINKEDIN_EMAIL=your_linkedin_email@example.com
LINKEDIN_PASSWORD=your_linkedin_password_here
```

### 2. Add Your Resume (`resume.txt`)

Paste your plain-text resume into `resume.txt`. Contact details, skills, and total experience are parsed dynamically from this file on every job.

### 3. Adjust Preferences

- **`config.py`:** Customize `JOB_TITLES`, `MATCH_THRESHOLD` (default `65.0`), and `DAILY_LIMIT` (default `30`).
- **`gemini_engine.py`:** Customize `TARGET_SALARY_LACS_PKR`, `MAX_ALLOWED_EXPERIENCE_YEARS` (default `4`), or set `OVERRIDE_TOTAL_YOE` to lock a fixed years-of-experience value.
- **`linkedin_driver.py`:** Edit the `locations` dictionary inside `_search_keyword()` to add or remove target countries.

---

## Running the Project

Make sure your virtual environment is active (`(venv)` shown in your terminal).

### 1. Run Diagnostics

```bash
python main.py --mode test
```

### 2. Start the Web Dashboard (Recommended)

```bash
python main.py --mode web
```
*(Or run `python app.py` directly.)*

Open `http://localhost:5000` in your browser and click **Start Automation**.

### 3. Run via CLI

```bash
python main.py --mode cli --platform linkedin
```

---

## Notes & Compliance

- **First-Time Sign-In:** On your first run, Chromium logs in using `.env` and pauses if LinkedIn prompts for 2FA or a CAPTCHA. Once completed, your session persists inside `chrome_user_data/`.
- **Keep Secrets Local:** Ensure `.env`, `chrome_user_data/`, `jobs.db`, and `venv/` stay in `.gitignore`.
- **Responsible Use:** Keep daily limits moderate and use this tool in accordance with LinkedIn's terms of service.

---

## Credits & License

- Original base project: [MadanAyyanavara/Auto_job_apply](https://github.com/MadanAyyanavara/Auto_job_apply)
- License: Refer to the `LICENSE` file in the repository root.