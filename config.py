import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

RESUME_PATH = BASE_DIR / "resume.txt"
DB_PATH = BASE_DIR / "jobs.db"
CHROME_USER_DATA = BASE_DIR / "chrome_user_data"

# Set to 65.0 so only jobs passing the role, <=4 YoE, and resume keyword checks apply
MATCH_THRESHOLD = 65.0
DAILY_LIMIT = 30

JOB_TITLES = [
    # Temenos & Core Banking
    "Temenos T24 Consultant",
    "Temenos Transact Developer",
    "Temenos L3 Java Extensibility Consultant",
    "Core Banking Software Engineer",
    "Temenos T24 Technical Consultant",
    "Temenos AA Consultant",
    "Core Banking Developer",

    # Payments & Fintech Backend
    "Backend Software Engineer - Payments",
    "Transaction Banking Software Engineer",
    "Payment Gateway Backend Developer",
    "ISO 8583 Backend Engineer",
    "Fintech Software Engineer",

    # Backend, Software Development, Implementation & Application Support
    "Senior Backend Engineer",
    "Senior Java Software Engineer",
    "Senior C++ Software Engineer",
    "Senior Software Engineer - Banking",
    "Software Developer",
    "Implementation Engineer",
    "Application Support Engineer",
    "Software Consultant",
    "Development & Configuration Specialist",
]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

__all__ = [
    "BASE_DIR",
    "RESUME_PATH",
    "DB_PATH",
    "CHROME_USER_DATA",
    "MATCH_THRESHOLD",
    "DAILY_LIMIT",
    "JOB_TITLES",
    "GEMINI_API_KEY",
]