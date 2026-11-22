import re
import logging
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

import google.generativeai as genai
from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

# ==============================================================================
# SALARY & EXPERIENCE CONFIGURATION
# ==============================================================================
# Target salary in Lacs PKR (1 Lac = 100,000 PKR). Auto-converts to local currency.
TARGET_SALARY_LACS_PKR = 5.0

# Reject any job requiring strictly more than this many minimum years of experience
MAX_ALLOWED_EXPERIENCE_YEARS = 4

# Optional: Set to an integer (e.g., 3 or 4) to force a fixed YoE, or leave None to auto-calculate from resume.txt
OVERRIDE_TOTAL_YOE = None

# 1. Block Staff/Manager/Principal/Executive titles AND non-dev domains (Accounting, Pre-Sales, PM, HR, etc.)
BLOCKED_TITLE_REGEX = re.compile(
    r"\b("
    r"staff|manager|mgr|principal|director|head\s+of|vice\s+president|vp|avp|svp|evp|"
    r"chief|cto|cio|ceo|coo|cfo|distinguished|fellow|"
    r"accountant|accounting|bookkeep\w*|buchhalter|finanzbuchhalter|steuer\w*|"
    r"audit\w*|tax|payroll|treasury|accounts\s+payable|accounts\s+receivable|"
    r"billing|controller|actuar\w*|underwriter|credit\s+analyst|financial\s+analyst|"
    r"wealth\s+advisor|relationship\s+officer|teller|"
    r"pre[\-\s]?sales|sales|account\s+executive|business\s+development|bdr|sdr|"
    r"marketing|seo|copywriter|content\s+writer|social\s+media|customer\s+success|"
    r"client\s+success|vertrieb\w*|"
    r"project\s+management|project\s+coordinator|project\s+lead|program\s+coordinator|"
    r"projektleiter|projektmanager|pmo|scrum\s+master|agile\s+coach|"
    r"product\s+owner|business\s+analyst|functional\s+analyst|functional\s+consultant|"
    r"recruiter|talent\s+acquisition|human\s+resources|hr|people\s+ops|reward\w*|"
    r"legal|counsel|attorney|paralegal|compliance|procurement|supply\s+chain|"
    r"logistics|warehouse|receptionist|executive\s+assistant|office\s+admin"
    r")\b",
    re.IGNORECASE,
)

# 2. Job title MUST match at least one relevant Software Dev / Implementation / App Support / Consultant keyword
ALLOWED_ROLE_TITLE_REGEX = re.compile(
    r"("
    r"\bsoftware\b|\bdeveloper\b|\bengineer\b|\bprogrammer\b|\bcoding\b|"
    r"\bbackend\b|\bback[\-\s]?end\b|\bfull[\-\s]?stack\b|"
    r"\bimplementation\b|\bapplication\s+support\b|\bapp\s+support\b|"
    r"\bproduction\s+support\b|\btechnical\s+support\b|\bsystems?\s+support\b|"
    r"\bit\s+support\b|\bsupport\s+(?:engineer|analyst|specialist|consultant)\b|"
    r"\bl2\b|\bl3\b|\btier\s*[23]\b|"
    r"\b(?:software|technical|technology|it|systems?|application|integration|core\s+banking|banking|temenos|t24|transact|payments?)\s+consultant\b|"
    r"\btemenos\b|\bt24\b|\btransact\b|\btafj\b|\binfobasic\b|\bcore\s+banking\b|"
    r"\bjava\b|c\+\+|\bpython\b|\bapi\b|\bapis\b|\bdocker\b|\bdevops\b|\bsre\b|"
    r"\bmiddleware\b|\bintegration\b|\bpayments?\b|\bswitch(?:ing)?\b|\bfintech\b|"
    r"\bsql\b|\bdatabase\b|\blinux\b|\bplatform\b|"
    r"\bentwickler\b|\bsoftwareentwickler\b|\bingenier\b|\bingenieur\b|\banwendungsbetreuer\b"
    r")",
    re.IGNORECASE,
)

PKR_PER_CURRENCY_UNIT = {
    "PKR": 1.0,
    "USD": 278.0,
    "SGD": 208.0,
    "EUR": 300.0,
    "GBP": 355.0,
    "CHF": 315.0,
    "AED": 75.7,
    "SAR": 74.1,
    "QAR": 76.3,
    "OMR": 722.0,
    "KWD": 905.0,
    "BHD": 737.0,
    "PLN": 70.0,
    "HKD": 35.7,
    "MYR": 63.0,
    "AUD": 182.0,
    "CAD": 200.0,
}

COUNTRY_CURRENCY_MAP = {
    "Saudi Arabia": "SAR",
    "United Arab Emirates": "AED",
    "Dubai": "AED",
    "Qatar": "QAR",
    "Oman": "OMR",
    "Kuwait": "KWD",
    "Bahrain": "BHD",
    "Switzerland": "CHF",
    "United Kingdom": "GBP",
    "Luxembourg": "EUR",
    "Germany": "EUR",
    "Netherlands": "EUR",
    "Ireland": "EUR",
    "Austria": "EUR",
    "France": "EUR",
    "Belgium": "EUR",
    "Spain": "EUR",
    "Poland": "PLN",
    "Singapore": "SGD",
    "Hong Kong": "HKD",
    "Malaysia": "MYR",
    "Australia": "AUD",
    "Canada": "CAD",
    "Pakistan": "PKR",
}

KNOWN_TECH_TERMS = [
    "temenos", "t24", "transact", "tafj", "infobasic", "jbase", "iris",
    "arrangement architecture", "ofs", "open financial service", "core banking",
    "banking", "fintech", "payment", "payments", "iso 8583", "iso8583",
    "payment switch", "switching", "transaction", "cards", "atm", "pos",
    "java", "c++", "python", "sql", "pl/sql", "oracle", "postgresql", "mysql",
    "linux", "rhel", "red hat", "unix", "bash", "shell", "docker", "kubernetes",
    "git", "github", "bitbucket", "jboss", "wildfly", "eclipse", "maven",
    "rest", "restful", "soap", "api", "apis", "json", "xml", "microservices",
    "multithreading", "concurrency", "socket", "tcp/ip", "debugging",
    "agile", "scrum", "ci/cd", "jenkins", "jira", "opencv", "nlp", "trocr",
    "machine learning", "deep learning", "computer vision", "backend",
    "software engineer", "technical consultant", "application support",
    "implementation", "l3", "extensibility",
]

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "have", "has", "had",
    "was", "were", "are", "work", "worked", "working", "experience", "years",
    "year", "role", "job", "team", "using", "used", "built", "developed",
    "responsible", "including", "across", "high", "new", "system", "systems",
}

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

HUMANIZED_SYSTEM_PROMPT = """You are a software engineer candidate answering job application screening questions based strictly on your provided resume.txt.

TONE & RULES:
- Read the exact question carefully and answer ONLY what is asked.
- If asked about reasonable adjustments / accommodations / disabilities: answer "No, I do not require any reasonable adjustments."
- If asked about availability to start / notice period: answer "30 days notice period (1 month)."
- If asked for a short factual value (City, Country, LinkedIn URL, GitHub/Portfolio link, Current Title, Current Employer, University): output ONLY that exact short value from the resume.
- If asked for CGPA or GPA: output nothing (empty string).
- For open-ended technical or behavioral questions: answer in first-person perspective ("I built...", "I worked with...") in 1 to 3 concise sentences grounded in resume.txt.
- Sound like a practical engineer—not corporate AI.
- BANNED WORDS: spearheaded, testament, delve, thrilled, passionate, leverage, in conclusion, furthermore, beacon, cutting-edge.
- Output ONLY the final answer. No preamble, no quotes, no conversational filler.
"""


def is_blocked_seniority_title(job_title: str) -> tuple[bool, str]:
    match = BLOCKED_TITLE_REGEX.search(job_title or "")
    if match:
        return True, match.group(0)
    return False, ""


def check_role_eligibility(job_title: str) -> tuple[bool, str]:
    title = (job_title or "").strip()
    if not title:
        return False, "Empty job title"

    is_blocked, blocked_term = is_blocked_seniority_title(title)
    if is_blocked:
        return False, f"Blocked title keyword ('{blocked_term}')"

    if not ALLOWED_ROLE_TITLE_REGEX.search(title):
        return False, "Title is not a Software Dev / Implementation / App Support / Technical Consultant role"

    return True, ""


def extract_required_min_years(job_description: str) -> int:
    if not job_description:
        return 0

    text = job_description.lower()
    word_to_num = {
        "four": "4", "five": "5", "six": "6", "seven": "7",
        "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
    }
    for word, digit in word_to_num.items():
        text = re.sub(rf"\b{word}\b", digit, text)

    detected_min_years = []

    strict_gt_pattern = re.compile(
        r"(?:more\s+than|over|above|exceeding)\s+(\d{1,2})\s*\+?\s*years?\s+(?:of\s+)?(?:[\w\-/]+\s+){0,4}experience"
    )
    for m in strict_gt_pattern.finditer(text):
        prefix = text[max(0, m.start() - 40):m.start()]
        if any(p in prefix for p in ["company", "we have", "our ", "founded", "business", "serving"]):
            continue
        yr = int(m.group(1))
        if 1 <= yr <= 12:
            detected_min_years.append(yr + 1)

    exp_patterns = [
        r"(\d{1,2})\s*\+?\s*(?:to|-|–|—)\s*\d{1,2}\s*\+?\s*years?\s+(?:of\s+)?(?:[\w\-/]+\s+){0,4}experience",
        r"(?:minimum|at\s+least|min\.?|requires?|requiring)\s+(?:of\s+)?(\d{1,2})\s*\+?\s*years?",
        r"(\d{1,2})\s*\+\s*years?\s+(?:of\s+)?(?:[\w\-/]+\s+){0,4}experience",
        r"(\d{1,2})\s*years?\s+(?:of\s+)?(?:[\w\-/]+\s+){0,4}experience",
        r"experience\s*[:\-]\s*(\d{1,2})\s*\+?\s*(?:(?:to|-|–|—)\s*\d{1,2})?\s*years?",
    ]
    for pat in exp_patterns:
        for m in re.finditer(pat, text):
            prefix = text[max(0, m.start() - 45):m.start()]
            if any(p in prefix for p in ["company", "we have", "our firm", "our team has", "founded", "established", "serving"]):
                continue
            try:
                yr = int(m.group(1))
                if 1 <= yr <= 12:
                    detected_min_years.append(yr)
            except Exception:
                pass

    return max(detected_min_years) if detected_min_years else 0


def load_resume_text(fallback_text: str = "") -> str:
    """Dynamically reads resume.txt from disk on every call."""
    base_dir = Path(__file__).resolve().parent
    candidate_paths = [
        base_dir / "resume.txt",
        Path.cwd() / "resume.txt",
        base_dir / "data" / "resume.txt",
    ]
    for path in candidate_paths:
        try:
            if path.exists() and path.is_file():
                content = path.read_text(encoding="utf-8", errors="ignore").strip()
                if content:
                    return content
        except Exception as e:
            logger.debug(f"Could not read {path}: {e}")
    return (fallback_text or "").strip()


def _calculate_experience_years_from_resume(text: str) -> float:
    """
    Calculates accurate professional years of experience from resume.txt by:
    1. Respecting OVERRIDE_TOTAL_YOE if configured.
    2. Using an explicit 'X years of experience' phrase in the resume summary if present.
    3. Isolating ONLY the Work Experience section (ignoring Education / Projects / Certifications)
       and merging month-year date intervals (excluding Student/Intern/Lab Assistant roles).
    """
    if OVERRIDE_TOTAL_YOE is not None:
        return float(OVERRIDE_TOTAL_YOE)

    if not text:
        return 3.5

    # 1. Explicit statement in resume summary (e.g., "3.5+ years of experience" or "4 years of experience")
    explicit_yoe = re.search(r"(\d+(?:\.\d+)?)\+?\s*years?\s+of\s+(?:professional\s+|industry\s+|relevant\s+|software\s+)?experience", text, re.I)
    if explicit_yoe:
        val = float(explicit_yoe.group(1))
        if 0.5 <= val <= 15.0:
            return val

    # 2. Extract only the Experience section so Education (e.g. 2019-2023) is never counted
    lines = text.splitlines()
    exp_lines = []
    in_exp_section = False
    exp_header_re = re.compile(r"^\s*(?:work\s+|professional\s+)?experience\b|^\s*employment\s+history\b", re.I)
    stop_header_re = re.compile(
        r"^\s*(?:education|academic|projects|certifications?|skills|technical\s+skills|publications?|awards?|honors?|languages?|references?)\b",
        re.I,
    )

    for line in lines:
        stripped = line.strip()
        if not in_exp_section:
            if exp_header_re.match(stripped) and len(stripped) < 45:
                in_exp_section = True
            continue
        if stop_header_re.match(stripped) and len(stripped) < 45:
            break
        exp_lines.append(stripped)

    exp_text = "\n".join(exp_lines) if exp_lines else text

    # 3. Parse month-year ranges (e.g., "June 2023 - June 2026", "Jun 2026 - Present")
    now = datetime.now()
    now_ym = now.year * 12 + now.month

    month_names = "|".join(MONTH_MAP.keys())
    date_range_re = re.compile(
        rf"(?:({month_names})\.?\s+)?(20\d{{2}})\s*(?:–|—|-|to)\s*(?:(present|current|now|till\s*date)|(?:({month_names})\.?\s+)?(20\d{{2}}))",
        re.I,
    )

    intervals = []
    for idx, line in enumerate(exp_lines if exp_lines else lines):
        line_low = line.lower()
        # Skip university / student assistant / intern lines when calculating professional full-time YoE
        context_block = " ".join(exp_lines[max(0, idx - 1):idx + 2]).lower() if exp_lines else line_low
        if any(skip_w in context_block for skip_w in ["lab assistant", "teaching assistant", "student ", "bachelor", "master", "university", "nuces", "fast"]):
            continue

        for m in date_range_re.finditer(line):
            s_month_str, s_year_str, is_present, e_month_str, e_year_str = m.groups()
            s_year = int(s_year_str)
            s_month = MONTH_MAP.get((s_month_str or "").lower(), 6)  # Default mid-year if month omitted
            start_ym = s_year * 12 + s_month

            if is_present:
                end_ym = now_ym
            else:
                e_year = int(e_year_str)
                e_month = MONTH_MAP.get((e_month_str or "").lower(), 6)
                end_ym = min(e_year * 12 + e_month, now_ym)

            if start_ym <= end_ym and (now.year - s_year) <= 15:
                intervals.append((start_ym, end_ym))

    if intervals:
        # Merge overlapping date intervals so concurrent roles aren't double-counted
        intervals.sort()
        merged = [intervals[0]]
        for start, end in intervals[1:]:
            prev_s, prev_e = merged[-1]
            if start <= prev_e:
                merged[-1] = (prev_s, max(prev_e, end))
            else:
                merged.append((start, end))

        total_months = sum(end - start for start, end in merged)
        years = round(total_months / 12.0, 1)
        if 0.5 <= years <= 15.0:
            return years

    return 3.5


def parse_resume_details(resume_text: str = "") -> dict:
    """Dynamically parses personal info, links, accurate total YoE, and keywords from resume.txt."""
    text = load_resume_text(resume_text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    full_name = ""
    if lines:
        first_line = re.sub(r"^(resume|curriculum vitae|cv)\s*[:\-]?\s*", "", lines[0], flags=re.I).strip()
        name_candidate = first_line.split("|")[0].split("-")[0].split(",")[0].strip()
        if 1 <= len(name_candidate.split()) <= 4 and not any(c.isdigit() for c in name_candidate):
            full_name = name_candidate

    name_parts = full_name.split() if full_name else []
    first_name = name_parts[0] if len(name_parts) >= 1 else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) >= 2 else ""

    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    email = email_match.group(0) if email_match else ""

    phone_match = re.search(r"(\+?\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4})", text)
    phone = phone_match.group(1).strip() if phone_match else ""

    linkedin_match = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_\-]+/?", text, re.I)
    linkedin = linkedin_match.group(0) if linkedin_match else ""
    if linkedin and not linkedin.startswith("http"):
        linkedin = f"https://{linkedin}"

    github_match = re.search(r"(?:https?://)?(?:[a-zA-Z0-9_\-]+\.github\.io|github\.com/[a-zA-Z0-9_\-]+)[^\s,)|]*", text, re.I)
    github = github_match.group(0) if github_match else ""
    if github and not github.startswith("http"):
        github = f"https://{github}"

    header_blob = "\n".join(lines[:10])
    city = "Karachi" if re.search(r"\bkarachi\b", header_blob, re.I) else ""
    country = "Pakistan" if re.search(r"\bpakistan\b", header_blob, re.I) else ""
    if not city:
        loc_match = re.search(r"\b([A-Z][a-zA-Z]+)\s*,\s*([A-Z][a-zA-Z]+)\b", header_blob)
        if loc_match:
            city = loc_match.group(1)
            country = country or loc_match.group(2)

    total_yoe = _calculate_experience_years_from_resume(text)

    text_lower = text.lower()
    extracted_keywords = [kw for kw in KNOWN_TECH_TERMS if kw in text_lower]

    dynamic_tokens = set(re.findall(r"\b[A-Za-z][A-Za-z0-9+#\./\-]{2,15}\b", text))
    for tok in dynamic_tokens:
        tok_low = tok.lower().strip("./-")
        if len(tok_low) >= 3 and tok_low not in STOPWORDS and (any(c.isupper() for c in tok[1:]) or "+" in tok or "#" in tok):
            if tok_low not in extracted_keywords:
                extracted_keywords.append(tok_low)

    return {
        "resume_text": text,
        "full_name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "github": github,
        "city": city or "Karachi",
        "country": country or "Pakistan",
        "total_yoe": total_yoe,
        "keywords": extracted_keywords if extracted_keywords else KNOWN_TECH_TERMS,
    }


def is_cgpa_question(question_text: str) -> bool:
    q_lower = (question_text or "").lower()
    return bool(re.search(r"\b(c\.?g\.?p\.?a\.?|g\.?p\.?a\.?|grade\s+point|cumulative\s+grade)\b", q_lower))


def get_deterministic_hr_answer(question_text: str, profile: dict) -> str:
    """
    Handles common HR / recruitment screening questions deterministically so they
    always get clean, relevant answers even if Gemini is rate-limited.
    """
    q = (question_text or "").lower()

    if any(w in q for w in ["reasonable adjustment", "accommodat", "disability", "special requirement", "accessibility"]):
        return "No, I do not require any reasonable adjustments."

    if any(w in q for w in ["availability", "start a new role", "when can you start", "earliest start", "start date", "available to start", "notice period"]):
        return "30 days notice period (1 month)"

    if any(w in q for w in ["country of residence", "current country", "country you reside", "based in which country"]):
        return profile.get("country") or "Pakistan"

    if any(w in q for w in ["current city", "city of residence", "which city"]):
        return profile.get("city") or "Karachi"

    if any(w in q for w in ["how did you hear", "where did you hear", "referral source", "source of application"]):
        return "LinkedIn"

    if any(w in q for w in ["comfortable working", "relocat", "commute", "travel", "work on-site", "hybrid", "shift"]):
        return "Yes"

    return ""


def analyze_job_against_resume(job_title: str, job_description: str, resume_text: str = "", min_keywords: int = 4) -> dict:
    profile = parse_resume_details(resume_text)
    candidate_yoe = profile["total_yoe"]
    resume_keywords = profile["keywords"]

    is_eligible, title_reason = check_role_eligibility(job_title)
    if not is_eligible:
        return {
            "is_match": False,
            "heuristic_score": 0.0,
            "matched_keywords": [],
            "matched_count": 0,
            "required_min_yoe": 0,
            "candidate_yoe": candidate_yoe,
            "experience_compatible": False,
            "reject_reason": title_reason,
        }

    required_min_yoe = extract_required_min_years(f"{job_title}\n{job_description}")
    if required_min_yoe > MAX_ALLOWED_EXPERIENCE_YEARS:
        return {
            "is_match": False,
            "heuristic_score": 25.0,
            "matched_keywords": [],
            "matched_count": 0,
            "required_min_yoe": required_min_yoe,
            "candidate_yoe": candidate_yoe,
            "experience_compatible": False,
            "reject_reason": f"Requires {required_min_yoe}+ years of experience (limit is {MAX_ALLOWED_EXPERIENCE_YEARS} yrs)",
        }

    combined_job = f"{job_title}\n{job_description}".lower()
    matched_keywords = []
    for kw in resume_keywords:
        pattern = r"\b" + re.escape(kw) + r"\b" if kw.replace(" ", "").isalnum() else re.escape(kw)
        if re.search(pattern, combined_job):
            matched_keywords.append(kw)

    normalized_matches = set()
    distinct_matches = []
    for kw in matched_keywords:
        norm = kw.rstrip("s")
        if norm not in normalized_matches:
            normalized_matches.add(norm)
            distinct_matches.append(kw)

    has_niche_banking_match = any(
        niche in combined_job for niche in ["temenos", "t24", "transact", "tafj", "iso 8583", "iso8583", "core banking"]
    )
    effective_min_keywords = 3 if has_niche_banking_match else min_keywords
    keywords_sufficient = len(distinct_matches) >= effective_min_keywords

    if not keywords_sufficient:
        heuristic_score = 40.0 + (len(distinct_matches) * 6.0)
        reject_reason = f"Only {len(distinct_matches)} resume keywords matched (need {effective_min_keywords}+)"
    else:
        heuristic_score = 54.0 + (len(distinct_matches) * 4.0) + (8.0 if has_niche_banking_match else 0.0)
        heuristic_score = min(heuristic_score, 96.0)
        reject_reason = ""

    return {
        "is_match": keywords_sufficient,
        "heuristic_score": round(heuristic_score, 1),
        "matched_keywords": distinct_matches,
        "matched_count": len(distinct_matches),
        "required_min_yoe": required_min_yoe,
        "candidate_yoe": candidate_yoe,
        "experience_compatible": True,
        "reject_reason": reject_reason,
    }


class GeminiEngine:
    # Active 2026 Flash models (avoid retired 1.5-flash and 2.0-flash)
    PREFERRED_MODELS = [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
        "gemini-2.5-flash",
    ]

    def __init__(self, api_key: str = GEMINI_API_KEY):
        if not api_key or api_key == "your_gemini_api_key_here":
            raise ValueError("GEMINI_API_KEY not configured. Please set a valid API key in .env file")
        genai.configure(api_key=api_key)
        self.available_models = self._discover_working_models()
        self.model_name = self.available_models[0]
        self.model = genai.GenerativeModel(self.model_name)
        logger.info(f"GeminiEngine initialized with active model: {self.model_name} (candidates: {self.available_models[:4]})")

    def _discover_working_models(self) -> list[str]:
        """
        Queries the Gemini API via list_models() at startup so we ONLY call
        models that are currently live and support generateContent for this API key.
        """
        excluded_tokens = ("tts", "image", "live", "audio", "transcribe", "omni", "embedding", "veo", "aqa", "imagen", "vision")
        discovered = []
        try:
            for m in genai.list_models():
                methods = getattr(m, "supported_generation_methods", []) or []
                if "generateContent" not in methods:
                    continue
                name = (getattr(m, "name", "") or "").replace("models/", "").strip()
                name_low = name.lower()
                if "gemini" in name_low and not any(bad in name_low for bad in excluded_tokens):
                    discovered.append(name)
        except Exception as e:
            logger.warning(f"Could not dynamically list Gemini models ({e}); using preferred list.")

        if discovered:
            ordered = []
            # 1. Add preferred models that actually exist for this API key
            for pref in self.PREFERRED_MODELS:
                if pref in discovered and pref not in ordered:
                    ordered.append(pref)
            # 2. Add any other live 'flash' text models
            for d in discovered:
                if "flash" in d.lower() and d not in ordered:
                    ordered.append(d)
            # 3. Add remaining live Gemini text models
            for d in discovered:
                if d not in ordered:
                    ordered.append(d)
            if ordered:
                return ordered

        return list(self.PREFERRED_MODELS)

    def _generate(self, prompt: str, temperature: float = 0.2, max_output_tokens: int = 1024) -> str:
        # Try current working model first, then fall back through discovered models
        order = [self.model_name] + [m for m in self.available_models if m != self.model_name]

        for candidate in order[:5]:
            try:
                if self.model_name != candidate:
                    self.model_name = candidate
                    self.model = genai.GenerativeModel(self.model_name)

                response = self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=max(max_output_tokens, 512),
                    ),
                )

                if response and getattr(response, "candidates", None):
                    for cand in response.candidates:
                        content = getattr(cand, "content", None)
                        parts = getattr(content, "parts", None) if content else None
                        if parts:
                            text_chunks = [getattr(p, "text", "") for p in parts if getattr(p, "text", "")]
                            combined = "".join(text_chunks).strip()
                            if combined:
                                return combined

                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                logger.warning(f"Gemini {candidate} error ({e}), trying next model...")
                continue
        return ""

    def generate_screening_questions(
        self, job_description: str, resume: str, count: int = 3
    ) -> list[str]:
        prompt = f"""
        Given the following job description and resume, generate {count} custom screening questions
        that would be most relevant for evaluating the candidate's fit for this role.

        Job Description:
        {job_description}

        Resume:
        {resume}

        Return only the questions, one per line, numbered 1-{count}.
        """
        text = self._generate(prompt, temperature=0.5, max_output_tokens=512)
        questions = [q.strip() for q in text.split("\n") if q.strip()]
        return questions[:count]

    def generate_cover_letter(
        self, job_description: str, company: str, position: str
    ) -> str:
        prompt = f"""
        Generate a professional, concise cover letter for the following job opportunity.
        Keep it to 2-3 paragraphs.

        Company: {company}
        Position: {position}
        Job Description:
        {job_description}
        """
        return self._generate(prompt, temperature=0.6, max_output_tokens=1024)

    def get_salary_expectation(
        self,
        question_text: str,
        job_location: str = "",
        numeric_only: bool = True,
        resume_text: str = "",
    ) -> str:
        q_lower = (question_text or "").lower()

        lacs_pkr = TARGET_SALARY_LACS_PKR
        live_resume = load_resume_text(resume_text)
        resume_lacs_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lacs?|lakhs?)\s*pkr", live_resume, re.I)
        if resume_lacs_match:
            try:
                lacs_pkr = float(resume_lacs_match.group(1))
            except Exception:
                pass

        base_pkr_amount = lacs_pkr * 100000.0

        currency = COUNTRY_CURRENCY_MAP.get(job_location, "USD")
        explicit_currencies = {
            r"\bsgd\b|\bsingapore\s+dollar": "SGD",
            r"\bchf\b|\bswiss\s+franc": "CHF",
            r"\bgbp\b|£|\bpound": "GBP",
            r"\beur\b|€|\beuro": "EUR",
            r"\baed\b|\bdirham": "AED",
            r"\bsar\b|\bsaudi\s+riyal": "SAR",
            r"\bqar\b|\bqatari\s+riyal": "QAR",
            r"\bomr\b|\bomani\s+rial": "OMR",
            r"\bkwd\b|\bkuwaiti\s+dinar": "KWD",
            r"\bbhd\b|\bbahraini\s+dinar": "BHD",
            r"\bpln\b|\bzloty": "PLN",
            r"\bhkd\b|\bhong\s+kong\s+dollar": "HKD",
            r"\bmyr\b|\bringgit": "MYR",
            r"\baud\b|\baustralian\s+dollar": "AUD",
            r"\bcad\b|\bcanadian\s+dollar": "CAD",
            r"\bpkr\b|\brupee": "PKR",
            r"\busd\b|\bus\s+dollar": "USD",
        }
        for pattern, curr_code in explicit_currencies.items():
            if re.search(pattern, q_lower):
                currency = curr_code
                break

        rate = PKR_PER_CURRENCY_UNIT.get(currency, 278.0)
        converted_monthly = base_pkr_amount / rate

        is_annual = any(w in q_lower for w in ["annual", "yearly", "per year", "/year", "per annum", "p.a."])
        raw_target = converted_monthly * 12.0 if is_annual else converted_monthly

        if raw_target >= 1000:
            target_amount = int(round(raw_target / 50.0) * 50)
        else:
            target_amount = int(round(raw_target / 10.0) * 10)

        if numeric_only:
            return str(target_amount)
        return f"{target_amount} {currency}"

    def evaluate_fit(
        self, job_description: str, resume: str = "", experience: str = ""
    ) -> dict:
        live_resume = load_resume_text(resume)
        pure_title = experience.split(" at ")[0].strip() if " at " in experience else experience

        analysis = analyze_job_against_resume(
            job_title=pure_title,
            job_description=job_description,
            resume_text=live_resume,
            min_keywords=4,
        )

        if not analysis["is_match"]:
            logger.info(f"Skipped job '{pure_title}': {analysis['reject_reason']}")
            return {
                "fit_score": analysis["heuristic_score"],
                "matched_keywords": analysis["matched_keywords"],
                "required_min_yoe": analysis["required_min_yoe"],
                "reject_reason": analysis["reject_reason"],
                "recommendation": "pass",
            }

        prompt = f"""
        Evaluate whether this job is a strong technical match for a candidate seeking ONLY:
        - Software Development / Backend Software Engineering
        - Implementation Engineering / Technical Integration
        - Application Support / Production Support (L2/L3)
        - Software / Technical Consulting (Temenos T24 / Core Banking / Payments)

        Pre-verified Analysis from resume.txt:
        - Candidate Total Experience: ~{analysis['candidate_yoe']} years
        - Job Required Minimum Experience Detected: {analysis['required_min_yoe'] or 'Compatible (<= 4)'} years
        - Matched Resume Keywords ({analysis['matched_count']}): {', '.join(analysis['matched_keywords'])}

        STRICT DISQUALIFICATION RULES (MUST OUTPUT 0):
        - If the role is Accounting, Finance, Bookkeeping, Audit, Tax, Pre-Sales, Sales, Business Development, Project Management, Program Management, Scrum Master, Business Analysis, HR, Recruiting, or Marketing -> OUTPUT 0.
        - If the role is Staff, Manager, Principal, Director, VP, or Head-level -> OUTPUT 0.
        - If the job description requires MORE than {MAX_ALLOWED_EXPERIENCE_YEARS} years of experience (e.g., 5+ years, 6+ years, 7+ years, "more than 4 years") -> OUTPUT 0.

        SCORING (when eligible):
        - 4-5 matching resume keywords and relevant role: score 70 to 82.
        - 6+ matching resume keywords or strong Temenos/Payments/Java/C++/Python fit: score 83 to 96.
        - Output ONLY a single number between 0 and 100. No words, no % sign.

        Job Context:
        {experience}

        Job Description:
        {job_description[:3500]}

        Candidate Resume (resume.txt):
        {live_resume}
        """
        try:
            text = self._generate(prompt, temperature=0.1, max_output_tokens=512)
            match = re.search(r"(\d+(\.\d+)?)", text)
            if match:
                llm_score = float(match.group(1))
                if llm_score <= 25.0:
                    return {
                        "fit_score": llm_score,
                        "matched_keywords": analysis["matched_keywords"],
                        "required_min_yoe": analysis["required_min_yoe"],
                        "reject_reason": "Gemini disqualified role (non-dev/accounting/presales/PM or >4 YoE)",
                        "recommendation": "pass",
                    }
                if 0.0 < llm_score <= 100.0:
                    final_score = round((llm_score * 0.65) + (analysis["heuristic_score"] * 0.35), 1)
                    return {
                        "fit_score": final_score,
                        "matched_keywords": analysis["matched_keywords"],
                        "required_min_yoe": analysis["required_min_yoe"],
                        "reject_reason": "",
                        "recommendation": "hire" if final_score >= 65.0 else "pass",
                    }
        except Exception as e:
            logger.warning(f"Gemini score refinement failed, using local score: {e}")

        return {
            "fit_score": analysis["heuristic_score"],
            "matched_keywords": analysis["matched_keywords"],
            "required_min_yoe": analysis["required_min_yoe"],
            "reject_reason": analysis["reject_reason"],
            "recommendation": "hire" if analysis["is_match"] else "pass",
        }

    def estimate_skill_years_from_resume(self, resume_text: str, question_text: str) -> str:
        live_resume = load_resume_text(resume_text)
        q_lower = (question_text or "").lower()
        profile = parse_resume_details(live_resume)
        # Never exceed MAX_ALLOWED_EXPERIENCE_YEARS if auto-parsed from a ~3-4 yr resume
        total_yoe_int = min(int(round(profile["total_yoe"])), MAX_ALLOWED_EXPERIENCE_YEARS)

        if is_cgpa_question(question_text):
            return ""

        if "notice" in q_lower:
            if "month" in q_lower:
                return "1"
            if "week" in q_lower:
                return "4"
            return "30"

        return str(total_yoe_int)

    def answer_screening_question(
        self,
        resume_text: str,
        question_text: str,
        job_description: str = "",
        is_numeric: bool = False,
        job_location: str = "",
    ) -> str:
        if not question_text:
            return ""

        if is_cgpa_question(question_text):
            logger.info(f"Skipping CGPA/GPA question in GeminiEngine: [{question_text}]")
            return ""

        live_resume = load_resume_text(resume_text)
        profile = parse_resume_details(live_resume)
        total_yoe_int = min(int(round(profile["total_yoe"])), MAX_ALLOWED_EXPERIENCE_YEARS)

        # 1. Salary / compensation questions
        if is_salary_question(question_text):
            return self.get_salary_expectation(
                question_text=question_text,
                job_location=job_location,
                numeric_only=is_numeric,
                resume_text=live_resume,
            )

        numeric_mode = is_numeric or is_numeric_question(question_text)

        # 2. Numeric experience & notice period questions
        if numeric_mode:
            q_lower = question_text.lower()
            if "notice" in q_lower:
                if "month" in q_lower:
                    return "1"
                if "week" in q_lower:
                    return "4"
                return "30"

            if any(
                w in q_lower
                for w in [
                    "year", "experience", "python", "java", "c++", "infobasic", "api",
                    "docker", "sql", "linux", "temenos", "t24", "transact", "tafj",
                    "programming", "coding", "software", "backend", "support",
                    "implementation", "banking", "payment", "git", "oracle", "rest",
                    "soap", "microservices", "cloud", "kubernetes", "devops", "agile",
                ]
            ):
                return str(total_yoe_int)

            prompt = f"""You are filling out a numeric form field on a job application based on resume.txt.
Candidate Total Experience: {total_yoe_int} years
Question / Field Label: {question_text}
Output ONLY a single integer number. No words, no units."""
            raw = self._generate(prompt, temperature=0.1, max_output_tokens=512)
            match = re.search(r"\b\d+(\.\d+)?\b", raw)
            return match.group(0) if match else str(total_yoe_int)

        # 3. Deterministic HR answers (Reasonable adjustments, availability, country, etc.)
        hr_ans = get_deterministic_hr_answer(question_text, profile)
        if hr_ans:
            return hr_ans

        # 4. Open-ended or custom text questions routed to Gemini
        salary_str = self.get_salary_expectation(
            question_text="Expected Salary",
            job_location=job_location,
            numeric_only=False,
            resume_text=live_resume,
        )
        prompt = f"""{HUMANIZED_SYSTEM_PROMPT}

Candidate Resume (resume.txt):
{live_resume}

Candidate Total Experience: {total_yoe_int} years (use {total_yoe_int} years consistently for technical/coding skills)
Target Job Country: {job_location or "International"}
Expected Salary: {salary_str}

Job Description Context:
{job_description[:1500] if job_description else "N/A"}

Application Question / Field Label:
{question_text}

Write ONLY the direct, accurate answer to this specific question:"""

        answer = self._generate(prompt, temperature=0.25, max_output_tokens=1024)
        cleaned = answer.strip().strip('"').strip("'")
        if cleaned:
            return cleaned

        # Safe context-aware fallback (never paste a skill bio into non-technical HR fields)
        q_lower = question_text.lower()
        if any(w in q_lower for w in ["experience", "describe", "tell us", "why", "project", "skill", "background"]):
            top_skills = ", ".join(profile["keywords"][:6])
            return f"I have {total_yoe_int} years of experience working with {top_skills}."
        return "N/A"

    def answer_multiple_choice_question(
        self,
        resume_text: str,
        question_text: str,
        options: list[str],
        job_description: str = "",
        job_location: str = "",
    ) -> str:
        if not options:
            return ""
        if len(options) == 1:
            return options[0]

        live_resume = load_resume_text(resume_text)
        profile = parse_resume_details(live_resume)
        total_yoe_int = min(int(round(profile["total_yoe"])), MAX_ALLOWED_EXPERIENCE_YEARS)
        resume_lower = live_resume.lower()
        q_lower = (question_text or "").lower()

        # 1. Deterministic Country of Residence / Nationality match
        if any(w in q_lower for w in ["country of residence", "current country", "country you live", "country you reside", "nationality", "citizenship", "where are you located"]):
            home_country = (profile.get("country") or "Pakistan").strip().lower()
            for opt in options:
                if opt.strip().lower() == home_country or home_country in opt.strip().lower():
                    return opt
            # If home country is not listed (e.g., EU-only list), prefer "Other" or "Outside" instead of "Bulgaria"
            for fallback_kw in ["other", "outside", "not listed", "international", "none of the above"]:
                for opt in options:
                    if fallback_kw in opt.strip().lower():
                        return opt

        # 2. Deterministic Language Proficiency match
        if any(w in q_lower for w in ["proficiency", "fluent", "fluency", "speak", "language"]):
            foreign_languages = [
                "chinese", "mandarin", "cantonese", "german", "deutsch", "french", "français",
                "dutch", "nederlands", "spanish", "español", "italian", "arabic", "japanese",
                "korean", "russian", "portuguese", "polish", "turkish", "malay", "tamil",
            ]
            for lang in foreign_languages:
                if lang in q_lower and lang not in resume_lower:
                    for none_kw in ["none", "no proficiency", "not applicable", "n/a", "beginner", "elementary", "basic", "a1"]:
                        for opt in options:
                            if none_kw in opt.strip().lower():
                                return opt

        # 3. Deterministic Visa Sponsorship match
        if any(w in q_lower for w in ["sponsorship", "employment visa", "work visa", "require visa"]):
            if job_location.lower() != (profile.get("country") or "pakistan").lower():
                yes_opt = next((o for o in options if o.strip().lower() == "yes"), None)
                if yes_opt:
                    return yes_opt

        # 4. Route to active Gemini model
        options_formatted = "\n".join(f"- {opt}" for opt in options)
        prompt = f"""You are completing a job application form for a candidate based strictly on their resume.txt.
Choose the single best option from the Available Options list to answer the question.

Candidate Resume (resume.txt):
{live_resume}

Candidate Country of Residence: {profile.get('country') or 'Pakistan'}
Candidate Total Technical Experience: {total_yoe_int} years
Target Job Country: {job_location or "International"}

Question:
{question_text}

Available Options:
{options_formatted}

STRICT RULES:
- Reply with ONLY the exact text of one option from the Available Options list above.
- COUNTRY OF RESIDENCE: Always pick {profile.get('country') or 'Pakistan'} (or "Other" if not listed).
- LANGUAGE PROFICIENCY: If a spoken language is NOT in resume.txt (other than English/Urdu/Hindi), choose "None" (or lowest level).
- VISA SPONSORSHIP: For international roles outside {profile.get('country') or 'Pakistan'}, choose "Yes".
- TECHNICAL EXPERIENCE: Use {total_yoe_int} years of experience for Python, Java, C++, InfoBasic, APIs, Docker, SQL, Core Banking, and software engineering questions.
- Output ONLY the exact option text.
"""
        raw_choice = self._generate(prompt, temperature=0.1, max_output_tokens=512)
        cleaned = raw_choice.strip().strip("-").strip('"').strip("'").strip()

        for opt in options:
            if opt.strip().lower() == cleaned.lower():
                return opt

        for opt in options:
            if opt.strip().lower() in cleaned.lower() or cleaned.lower() in opt.strip().lower():
                return opt

        return ""


def is_salary_question(question_text: str) -> bool:
    salary_patterns = [
        r"\bsalary\b",
        r"\bcompensation\b",
        r"\bremuneration\b",
        r"\bctc\b",
        r"\bcost\s+to\s+company\b",
        r"\bexpected\s+pay\b",
        r"\bpay\s+expectation\b",
        r"\bdesired\s+pay\b",
        r"\bpackage\b",
    ]
    q_lower = (question_text or "").lower()
    return any(re.search(p, q_lower) for p in salary_patterns)


def is_numeric_question(question_text: str) -> bool:
    if is_cgpa_question(question_text):
        return False
    numeric_keywords = [
        r"\byears?\s+of\s+(?:work\s+|working\s+|relevant\s+|professional\s+|hands[\-\s]?on\s+)?experience\b",
        r"\byears?\s+of\s+.*\s+experience\b",
        r"\bhow\s+many\s+years\b",
        r"\bnumber\s+of\s+years\b",
        r"\bexperience\s*\(?(?:in\s+)?years\)?\b",
        r"\bnotice\s+period\b",
        r"\bmonths?\s+of\s+notice\b",
        r"\bdays?\s+of\s+notice\b",
        r"\bsalary\b",
        r"\bctc\b",
        r"\bcompensation\b",
        r"\bremuneration\b",
        r"\bcost\s+to\s+company\b",
        r"\bexpected\s+pay\b",
        r"\bhourly\s+rate\b",
    ]
    question_lower = (question_text or "").lower()
    return any(re.search(pattern, question_lower) for pattern in numeric_keywords)


__all__ = [
    "GeminiEngine",
    "load_resume_text",
    "parse_resume_details",
    "analyze_job_against_resume",
    "check_role_eligibility",
    "is_blocked_seniority_title",
    "extract_required_min_years",
    "get_deterministic_hr_answer",
    "is_numeric_question",
    "is_salary_question",
    "is_cgpa_question",
    "TARGET_SALARY_LACS_PKR",
    "MAX_ALLOWED_EXPERIENCE_YEARS",
    "OVERRIDE_TOTAL_YOE",
    "HUMANIZED_SYSTEM_PROMPT",
]