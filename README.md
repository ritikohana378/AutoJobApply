# Auto Job Apply

Auto Job Apply is a Python-based automation project for applying to jobs on LinkedIn and Naukri using a browser-driven workflow with a lightweight web dashboard, resume matching, and optional AI-powered screening responses.

It is designed to help you:

- search and apply to relevant jobs faster
- track applications locally in a SQLite database
- monitor activity through a Flask dashboard
- pause and resume automation when the browser needs human input
- optionally use a Chrome extension for resume autofill and form assistance

## Why this project exists

The goal is to reduce repetitive job-application work while keeping a human-in-the-loop checkpoint for scenarios such as CAPTCHA, OTP verification, or other manual browser prompts.

## Key features

- LinkedIn automation
- Naukri automation
- Resume-to-job matching using TF-IDF similarity
- Flask dashboard for live status monitoring
- SQLite application tracking
- Optional Gemini integration for screening answers
- Chrome extension support for quicker form filling
- Daily application limits and configurable job search settings

## Tech stack

- Python 3.12+
- Flask
- Playwright
- SQLite
- Google Gemini API
- Chrome/Chromium browser automation

## Repository structure

```text
.
├── app.py                # Flask web dashboard entry point
├── main.py               # CLI automation and diagnostics entry point
├── config.py             # Project configuration and environment settings
├── db.py                 # Database helpers
├── gemini_engine.py      # Gemini API integration
├── hitl_engine.py        # Human-in-the-loop pause/resume logic
├── linkedin_driver.py    # LinkedIn automation driver
├── naukri_driver.py      # Naukri automation driver
├── resume_matcher.py     # Resume/job similarity logic
├── resume.txt            # Your resume content
├── .env                  # Local secrets and API configuration
├── chrome_user_data/     # Chromium profile data
├── extension/            # Chrome extension source
└── templates/            # Dashboard HTML templates
```

## Prerequisites

Before running the project, make sure you have:

- Python 3.12 or newer
- Google Chrome or Chromium installed
- Access to a terminal with pip available

## Installation

1. Clone the repository.
2. Create and activate a virtual environment if you want an isolated setup.
3. Install the dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Create a local `.env` file from the provided template if needed and set your API key:

```env
GEMINI_API_KEY=your_api_key_here
```

You should also update:

- `resume.txt` with your actual resume text
- `config.py` if you want to change the daily limit, matching threshold, or job search titles

## Running the project

### 1. Web dashboard

```bash
python main.py --mode web
```

Then open:

```text
http://localhost:5000
```

### 2. CLI automation on LinkedIn

```bash
python main.py --mode cli --platform linkedin --headless
```

### 3. CLI automation on Naukri

```bash
python main.py --mode cli --platform naukri --headless
```

### 4. Run both platforms

```bash
python main.py --mode cli --platform all --headless
```

### 5. Diagnostics check

```bash
python main.py --mode test
```

## Chrome extension

A bundled Chrome extension is included in the `extension/` folder. You can load it manually in Chrome using `chrome://extensions/` with Developer mode enabled, or use the provided `LOAD_EXTENSION.bat` helper.

The extension is useful for:

- filling forms faster
- reusing your resume data
- integrating Gemini-assisted autofill behavior

## Environment and data files

- `.env` contains local secrets and API settings
- `resume.txt` contains the resume text used for matching and autofill
- `jobs.db` stores application tracking data
- `chrome_user_data/` keeps browser profile state for persistent Chromium sessions

## Notes on usage

- The first run may require manual sign-in to LinkedIn or Naukri.
- Some sites may require CAPTCHAs, OTP verification, or a human confirmation step.
- The system pauses for human-in-the-loop intervention when needed.
- Daily application volume is capped by the configured limit.

## Safety and compliance

Use this project responsibly and only on websites where you have permission to automate job applications. Respect each platform's terms of use, rate limits, and anti-bot policies.

## License

This project is provided under the repository license included in the project root.

## Contributing

Pull requests and improvements are welcome. If you plan to make changes, keep the project documentation up to date and verify the behavior with the provided diagnostic mode whenever possible.
