#!/usr/bin/env python3

import argparse
import logging
import signal
import sys
from datetime import datetime
from typing import Optional

from config import (
    RESUME_PATH,
    DB_PATH,
    CHROME_USER_DATA,
    DAILY_LIMIT,
    GEMINI_API_KEY,
)
from db import init_db, get_applied_jobs_count
from resume_matcher import ResumeMatcher
from gemini_engine import GeminiEngine
from linkedin_driver import LinkedInDriver
from naukri_driver import NaukriDriver
from hitl_engine import HITLEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

active_drivers: list = []
hitl_engine: Optional[HITLEngine] = None


def setup_signal_handlers() -> None:
    """Setup graceful shutdown handlers for SIGINT (Ctrl+C)."""

    def signal_handler(sig, frame):
        logger.warning("Received interrupt signal, shutting down gracefully...")
        cleanup_and_exit(0)

    signal.signal(signal.SIGINT, signal_handler)


def cleanup_and_exit(exit_code: int = 0) -> None:
    """Clean up active resources and exit."""
    logger.info("Cleaning up resources...")

    for driver in active_drivers:
        try:
            driver.close()
            logger.debug(f"Closed driver: {driver.__class__.__name__}")
        except Exception as e:
            logger.warning(f"Error closing driver: {e}")

    active_drivers.clear()
    logger.info("Shutdown complete")
    sys.exit(exit_code)


def run_diagnostic_check() -> bool:
    """Run system health check and return True if all checks pass."""
    checks = {}

    # Check 1: Resume file
    try:
        if not RESUME_PATH.exists():
            checks["resume.txt"] = ("[-] Missing", False)
        elif RESUME_PATH.stat().st_size == 0:
            checks["resume.txt"] = ("[-] Empty", False)
        else:
            size = RESUME_PATH.stat().st_size
            checks["resume.txt"] = (f"[+] Found ({size} bytes)", True)
    except Exception as e:
        checks["resume.txt"] = (f"[-] Error: {e}", False)

    # Check 2: Database
    try:
        init_db()
        checks["Database"] = ("[+] Connected & Initialized", True)
    except Exception as e:
        checks["Database"] = (f"[-] Error: {str(e)[:50]}", False)

    # Check 3: Gemini API Key
    try:
        if not GEMINI_API_KEY:
            checks["GEMINI_API_KEY"] = ("[-] Not set in .env", False)
        else:
            try:
                gemini = GeminiEngine()
                prompt = "Say 'OK' in one word."
                response = gemini.model.generate_content(prompt)
                if response and response.text:
                    checks["GEMINI_API_KEY"] = ("[+] Valid & Responding", True)
                else:
                    checks["GEMINI_API_KEY"] = ("[-] Invalid response", False)
            except Exception as e:
                error_msg = str(e)[:40]
                checks["GEMINI_API_KEY"] = (f"[-] {error_msg}", False)
    except Exception as e:
        checks["GEMINI_API_KEY"] = (f"[-] Error: {str(e)[:40]}", False)

    # Check 4: Chrome User Data Directory
    try:
        CHROME_USER_DATA.mkdir(parents=True, exist_ok=True)
        checks["Chromium User Data"] = (f"[+] {CHROME_USER_DATA}", True)
    except Exception as e:
        checks["Chromium User Data"] = (f"[-] Error: {e}", False)

    # Check 5: Resume Matcher (model initialization)
    try:
        matcher = ResumeMatcher()
        text_len = len(matcher.resume_text or "")
        if text_len > 0:
            checks["Resume Matcher"] = (f"[+] Loaded ({text_len} chars)", True)
        else:
            checks["Resume Matcher"] = ("[*] Loaded (empty resume)", True)
    except Exception as e:
        checks["Resume Matcher"] = (f"[-] Error: {str(e)[:40]}", False)

    # Check 6: Chrome Extension Files
    try:
        from pathlib import Path

        # Look for extension in current directory first, then parent
        base_dir = Path(__file__).parent
        extension_dir = base_dir / "extension"

        if not extension_dir.exists():
            extension_dir = base_dir.parent / "extension"

        manifest_path = extension_dir / "manifest.json"

        if not extension_dir.exists():
            checks["Chrome Extension"] = (
                "[*] Optional - Not found (web dashboard will work without it)",
                True,
            )
        elif not manifest_path.exists():
            checks["Chrome Extension"] = (
                f"[*] Directory exists but manifest.json missing",
                True,
            )
        else:
            required_files = [
                "manifest.json",
                "popup.html",
                "popup.js",
                "content.js",
                "gemini.js",
                "background.js",
            ]
            missing_files = [f for f in required_files if not (extension_dir / f).exists()]

            if missing_files:
                checks["Chrome Extension"] = (
                    f"[*] Optional - Some files missing: {', '.join(missing_files)}",
                    True,
                )
            else:
                abs_path = extension_dir.absolute()
                checks["Chrome Extension"] = (
                    f"[+] Ready. Load: {abs_path}",
                    True,
                )
    except Exception as e:
        checks["Chrome Extension"] = (f"[*] Optional - Error: {str(e)[:40]}", True)

    # Print results
    print("\n" + "=" * 70)
    print("[*] SYSTEM DIAGNOSTIC CHECK")
    print("=" * 70)

    all_passed = True
    for check_name, (status, passed) in checks.items():
        symbol = "[+]" if passed else "[-]"
        padded_name = check_name.ljust(30)
        print(f"{symbol} {padded_name} {status}")
        if not passed:
            all_passed = False

    print("=" * 70)
    if all_passed:
        print("[+] All checks passed! Ready to run.")
    else:
        print("[-] Some checks failed. Please review the errors above.")
    print("=" * 70 + "\n")

    return all_passed


def run_automation(
    platform: str,
    headless: bool,
    limit: Optional[int],
) -> None:
    """Run job application automation."""
    global active_drivers, hitl_engine

    hitl_engine = HITLEngine()
    daily_limit = limit or DAILY_LIMIT

    logger.info("=" * 70)
    logger.info(
        f"Starting Automation | Platform: {platform} | Headless: {headless} | Limit: {daily_limit}"
    )
    logger.info("=" * 70)

    try:
        if platform in ["all", "linkedin"]:
            logger.info("Initializing LinkedIn Driver...")
            linkedin = LinkedInDriver(headless=headless, hitl_engine=hitl_engine)
            active_drivers.append(linkedin)

            result = linkedin.search_and_apply_jobs(max_limit=daily_limit)
            logger.info(f"LinkedIn Results: {result}")

            linkedin.close()
            active_drivers.remove(linkedin)

        if platform in ["all", "naukri"]:
            logger.info("Initializing Naukri Driver...")
            naukri = NaukriDriver(headless=headless, hitl_engine=hitl_engine)
            active_drivers.append(naukri)

            result = naukri.search_and_apply_jobs(max_limit=daily_limit)
            logger.info(f"Naukri Results: {result}")

            naukri.close()
            active_drivers.remove(naukri)

        logger.info("=" * 70)
        logger.info("Automation Completed Successfully")
        logger.info("=" * 70)

    except KeyboardInterrupt:
        logger.warning("Automation interrupted by user")
        cleanup_and_exit(1)
    except Exception as e:
        logger.error(f"Automation error: {e}", exc_info=True)
        cleanup_and_exit(1)


def run_web_server() -> None:
    """Start Flask web dashboard."""
    logger.info("=" * 70)
    logger.info("[WEB] Starting Flask Dashboard Server")
    logger.info("=" * 70)
    logger.info("[>] Dashboard: http://localhost:5000")
    logger.info("[>] Press Ctrl+C to stop the server")
    logger.info("=" * 70)

    try:
        from app import app

        app.run(debug=False, port=5000, threaded=True)
    except KeyboardInterrupt:
        logger.info("Web server stopped by user")
        cleanup_and_exit(0)
    except Exception as e:
        logger.error(f"Web server error: {e}", exc_info=True)
        cleanup_and_exit(1)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Job Application Automation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --mode web                          # Start web dashboard
  python main.py --mode cli --platform all           # Run automation in CLI
  python main.py --mode test                         # Run system diagnostics
  python main.py --mode cli --platform linkedin      # LinkedIn only
  python main.py --mode cli --headless --limit 10   # Headless mode with limit
        """,
    )

    parser.add_argument(
        "--mode",
        choices=["web", "cli", "test"],
        default="web",
        help="Execution mode: web (Flask dashboard), cli (terminal), test (diagnostics)",
    )

    parser.add_argument(
        "--platform",
        choices=["all", "linkedin", "naukri"],
        default="all",
        help="Job platforms to target (default: all)",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Playwright in headless mode (default: headed for manual login)",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"Override daily application limit (default: {DAILY_LIMIT})",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()

    logger.info("=" * 70)
    logger.info("[*] Job Application Automation Engine")
    logger.info("=" * 70)

    # Route to appropriate execution mode
    if args.mode == "test":
        logger.info("Running System Diagnostic Check...")
        all_passed = run_diagnostic_check()
        cleanup_and_exit(0 if all_passed else 1)

    elif args.mode == "web":
        run_web_server()

    elif args.mode == "cli":
        run_automation(
            platform=args.platform,
            headless=args.headless,
            limit=args.limit,
        )
        cleanup_and_exit(0)


if __name__ == "__main__":
    main()
