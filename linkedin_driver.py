import random
import logging
import re
import time
import urllib.parse
from datetime import datetime
from typing import Optional
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from config import CHROME_USER_DATA, MATCH_THRESHOLD, DAILY_LIMIT, JOB_TITLES
from db import is_job_applied, log_job_application, get_applied_jobs_count
from resume_matcher import ResumeMatcher
from gemini_engine import (
    GeminiEngine,
    load_resume_text,
    parse_resume_details,
    analyze_job_against_resume,
    is_blocked_seniority_title,
    is_numeric_question,
    is_salary_question,
    is_cgpa_question,
    MAX_ALLOWED_EXPERIENCE_YEARS,
)
from hitl_engine import HITLEngine

logger = logging.getLogger(__name__)

LINKEDIN_BASE_URL = "https://www.linkedin.com/jobs/search/"


class LinkedInDriver:
    def __init__(self, headless: bool = False, hitl_engine: Optional[HITLEngine] = None):
        self.headless = headless
        self.user_data_dir = str(CHROME_USER_DATA)
        self.matcher = ResumeMatcher()
        try:
            self.gemini = GeminiEngine()
        except Exception as e:
            self.gemini = None
            logger.warning(f"GeminiEngine not initialized: {e}")
        self.hitl = hitl_engine or HITLEngine()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.current_country = "Saudi Arabia"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def start(self) -> None:
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=False,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        self.page = self.browser.pages[0] if self.browser.pages else self.browser.new_page()

    def close(self) -> None:
        if self.page:
            try:
                self.page.close()
            except Exception:
                pass
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass

    def search_and_apply_jobs(
        self, keywords: Optional[list[str]] = None, max_limit: Optional[int] = None
    ) -> dict:
        if not self.page:
            self.start()

        keywords = keywords or JOB_TITLES
        max_limit = max_limit or DAILY_LIMIT
        threshold = float(MATCH_THRESHOLD) if MATCH_THRESHOLD is not None else 65.0

        results = {
            "applied": 0,
            "skipped": 0,
            "external": 0,
            "failed": 0,
            "total_checked": 0,
        }

        today = datetime.now().strftime("%Y-%m-%d")
        daily_count = get_applied_jobs_count(today)
        seen_job_ids = set()

        for keyword in keywords:
            if daily_count >= max_limit:
                logger.info(f"Daily limit ({max_limit}) reached")
                break

            logger.info(f"Searching for: {keyword}")
            self._search_keyword(keyword)
            time.sleep(random.uniform(2.5, 4.0))

            job_cards = self._get_job_cards()
            logger.info(f"Found {len(job_cards)} raw job card elements")

            for idx, card in enumerate(job_cards):
                if daily_count >= max_limit:
                    logger.info(f"Daily limit reached after {results['applied']} applications")
                    break

                try:
                    self._dismiss_stuck_modal()

                    job_data = self._extract_job_data(card)
                    if not job_data:
                        continue

                    job_id = job_data["id"]

                    if job_id in seen_job_ids:
                        continue
                    seen_job_ids.add(job_id)

                    results["total_checked"] += 1

                    if is_job_applied(job_id):
                        logger.debug(f"Job {job_id} already applied")
                        results["skipped"] += 1
                        continue

                    # Fast pre-filter: skip Staff / Manager / Principal / Director / VP titles before clicking
                    is_blocked, blocked_term = is_blocked_seniority_title(job_data["title"])
                    if is_blocked:
                        logger.info(
                            f"Skipping Job [{job_id}] '{job_data['title']}' — blocked title keyword ('{blocked_term}')"
                        )
                        results["skipped"] += 1
                        continue

                    if not self._select_job_card(job_id):
                        results["failed"] += 1
                        continue

                    job_description = self._get_job_description()

                    is_feasible, match_score = self._is_job_feasible(job_data, job_description, threshold)

                    if not is_feasible:
                        results["skipped"] += 1
                        continue

                    applied = self._try_apply_job(card, job_data, job_description, match_score)
                    if applied:
                        results["applied"] += 1
                        daily_count += 1
                    else:
                        results["failed"] += 1

                    time.sleep(random.uniform(3.0, 6.0))

                except Exception as e:
                    logger.error(f"Error processing job card {idx}: {e}")
                    results["failed"] += 1

        return results

    def _search_keyword(self, keyword: str) -> None:
        locations = {
            # Gulf Cooperation Council (GCC)
            "Saudi Arabia": "100459316",
            "United Arab Emirates": "104305776",
            "Dubai": "104621935",
            "Qatar": "104116203",
            "Oman": "103619019",
            "Kuwait": "103239229",
            "Bahrain": "100495666",
            # Europe Core Banking & Temenos Hubs
            "Switzerland": "106693272",
            "United Kingdom": "101165590",
            "Luxembourg": "104042105",
            "Germany": "101282230",
            "Netherlands": "102890719",
            "Ireland": "104738515",
            "Austria": "103825863",
            "France": "105015875",
            "Belgium": "100565514",
            "Spain": "105646813",
            "Poland": "105072130",
            # Asia-Pacific & North America Temenos / Financial Hubs
            "Singapore": "102454443",
            "Hong Kong": "103291313",
            "Malaysia": "106808692",
            "Australia": "101452733",
            "Canada": "101174742",
        }

        country_name, geo_id = random.choice(list(locations.items()))
        self.current_country = country_name
        safe_keyword = urllib.parse.quote(keyword)

        # f_TPR=r604800 filters for Past Week (7 days); f_AL=true filters for Easy Apply
        url = f"{LINKEDIN_BASE_URL}?keywords={safe_keyword}&geoId={geo_id}&f_TPR=r604800&f_AL=true"

        logger.info(f"Navigating to {country_name} (Past Week | Easy Apply Only)")
        self.page.goto(url, wait_until="domcontentloaded")

    def _get_job_cards(self) -> list:
        card_selector = (
            "div[componentkey^='job-card-component-ref-'], "
            "div[data-job-id], "
            "li[data-occludable-job-id]"
        )
        try:
            self.page.wait_for_selector(card_selector, timeout=10000)
            return self.page.query_selector_all(card_selector)
        except Exception as e:
            logger.warning(f"Failed to get job cards: {e}")
            return []

    def _extract_job_data(self, card) -> Optional[dict]:
        try:
            raw_key = (
                card.get_attribute("componentkey")
                or card.get_attribute("data-job-id")
                or card.get_attribute("data-occludable-job-id")
                or ""
            )
            match = re.search(r"(\d{8,})", raw_key)
            job_id = match.group(1) if match else raw_key.replace("job-card-component-ref-", "").strip()

            if not job_id:
                return None

            card_text = card.inner_text() or card.text_content() or ""
            text_lines = [line.strip() for line in card_text.split("\n") if line.strip()]

            title = text_lines[0] if len(text_lines) > 0 else f"Job {job_id}"
            company = text_lines[1] if len(text_lines) > 1 else "Unknown Company"

            return {
                "id": job_id,
                "title": title,
                "company": company,
                "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
                "platform": "LinkedIn",
            }
        except Exception as e:
            logger.error(f"Error extracting job data: {e}")
            return None

    def _select_job_card(self, job_id: str) -> bool:
        try:
            fresh_card = self.page.locator(
                f"div[componentkey*='{job_id}'], div[data-job-id='{job_id}'], li[data-occludable-job-id='{job_id}']"
            ).first
            if fresh_card.count() == 0:
                return False

            fresh_card.scroll_into_view_if_needed()
            time.sleep(0.3)

            link_inside = fresh_card.locator("a").first
            if link_inside.count() > 0:
                link_inside.click(force=True)
            else:
                fresh_card.click(force=True)

            time.sleep(1.8)
            return True
        except Exception as e:
            logger.warning(f"Could not select job card {job_id}: {e}")
            return False

    def _get_job_description(self) -> str:
        selectors = [
            "div#job-details",
            "div[class*='jobs-description-content']",
            "article[class*='jobs-description']",
            "div[class*='jobs-box__html-content']",
            "[data-testid*='job-details']",
            ".jobs-search__job-details--container",
        ]
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    text = loc.inner_text().strip()
                    if len(text) > 50:
                        return text
            except Exception:
                continue

        try:
            desc_text = self.page.evaluate(
                """() => {
                    const headings = Array.from(document.querySelectorAll('h2, h3, h4, span, div'));
                    const aboutHeading = headings.find(el =>
                        el.childElementCount === 0 &&
                        /^(about the job|job description|stellenbeschreibung)$/i.test(el.innerText.trim())
                    );
                    if (aboutHeading) {
                        const section = aboutHeading.closest('section, article') || aboutHeading.parentElement?.parentElement;
                        if (section && section.innerText.trim().length > 50) {
                            return section.innerText.trim();
                        }
                    }
                    const main = document.querySelector('main');
                    return main ? main.innerText.slice(0, 4000) : '';
                }"""
            )
            return (desc_text or "").strip()
        except Exception as e:
            logger.debug(f"Fallback job description extraction failed: {e}")
            return ""

    def _is_job_feasible(self, job_data: dict, job_description: str, threshold: float = 65.0) -> tuple[bool, float]:
        resume_text = self._get_resume_text()
        job_title = job_data.get("title", "")
        job_id = job_data.get("id", "")

        if self.gemini and resume_text:
            eval_res = self.gemini.evaluate_fit(
                job_description=job_description,
                resume=resume_text,
                experience=f"{job_title} at {job_data.get('company', '')}",
            )
            score = float(eval_res.get("fit_score", 0.0))
            matched_kws = eval_res.get("matched_keywords", [])
            req_yoe = eval_res.get("required_min_yoe", 0)
            reject_reason = eval_res.get("reject_reason", "")
            is_feasible = (
                score >= threshold
                and eval_res.get("recommendation") == "hire"
                and req_yoe <= MAX_ALLOWED_EXPERIENCE_YEARS
            )

            logger.info(
                f"Job [{job_id}] '{job_title}' ({self.current_country}) | "
                f"Score: {score:.1f}% | Matched Keywords ({len(matched_kws)}): {matched_kws[:8]} | "
                f"Detected Min YoE: {req_yoe if req_yoe else '<=4/Unspecified'} | "
                f"Apply: {is_feasible}" + (f" | Reason: {reject_reason}" if reject_reason else "")
            )
            return is_feasible, score

        analysis = analyze_job_against_resume(
            job_title=job_title,
            job_description=job_description,
            resume_text=resume_text,
            min_keywords=4,
        )
        score = analysis["heuristic_score"]
        is_feasible = (
            analysis["is_match"]
            and score >= threshold
            and analysis["required_min_yoe"] <= MAX_ALLOWED_EXPERIENCE_YEARS
        )
        logger.info(
            f"Job [{job_id}] '{job_title}' | Score: {score:.1f}% | "
            f"Matched Keywords ({analysis['matched_count']}): {analysis['matched_keywords'][:8]} | "
            f"Detected Min YoE: {analysis['required_min_yoe']} | Apply: {is_feasible}"
            + (f" | Reason: {analysis['reject_reason']}" if analysis["reject_reason"] else "")
        )
        return is_feasible, score

    def _find_visible_easy_apply_button(self):
        selectors = [
            "button.jobs-apply-button:visible",
            "button[aria-label*='Easy Apply']:visible",
            "button:has-text('Easy Apply'):visible",
            "[role='button'][aria-label*='Easy Apply']:visible",
            "a[aria-label*='Easy Apply']:visible",
        ]
        for selector in selectors:
            loc = self.page.locator(selector).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    def _try_apply_job(self, card, job_data: dict, job_description: str, match_score: float) -> bool:
        try:
            job_id = job_data["id"]

            easy_apply_btn = None
            for _ in range(8):
                easy_apply_btn = self._find_visible_easy_apply_button()
                if easy_apply_btn:
                    break
                time.sleep(0.5)

            if easy_apply_btn:
                return self._apply_easy_apply(easy_apply_btn, job_data, job_description, match_score)

            applied_badge = self.page.locator("span:has-text('Applied'), .artdeco-inline-feedback--success:visible")
            if applied_badge.count() > 0:
                logger.info(f"Job {job_id} already shows as Applied on LinkedIn")
                return False

            external_link = self._get_external_apply_link(card)
            if external_link:
                return self._log_external_job(job_data, external_link, match_score)

            logger.info(f"No apply button found for job {job_id}")
            return False

        except Exception as e:
            logger.error(f"Error applying to job: {e}")
            return False

    def _apply_easy_apply(self, easy_apply_btn, job_data: dict, job_description: str, match_score: float) -> bool:
        try:
            easy_apply_btn.scroll_into_view_if_needed()
            easy_apply_btn.click(force=True)

            time.sleep(2.0)

            success = self._handle_easy_apply_modal(job_description)
            if success:
                job_data["match_score"] = match_score
                job_data["status"] = "applied"
                job_data["applied_at"] = datetime.now().isoformat()
                log_job_application(job_data)
                logger.info(f"Successfully applied to {job_data['id']} (Match Score: {match_score:.1f}%)")
                return True

            self._dismiss_stuck_modal()
            return False
        except Exception as e:
            logger.error(f"Error in easy apply click: {e}")
            self._dismiss_stuck_modal()
            return False

    def _get_active_modal(self):
        selectors = [
            "dialog[open][data-testid='dialog']:visible",
            "dialog[open]:visible",
            "div.jobs-easy-apply-modal:visible",
            "div.artdeco-modal--layer-default:visible",
            "div.artdeco-modal:visible",
            "div[role='dialog']:has(button[aria-label='Dismiss']):visible",
            "div[role='dialog']:visible",
        ]
        for sel in selectors:
            loc = self.page.locator(sel).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    def _scroll_modal(self, modal_loc, position: str = "bottom") -> None:
        try:
            modal_loc.evaluate(
                """(modal, pos) => {
                    const candidates = [modal, ...Array.from(modal.querySelectorAll('div, section, form'))];
                    for (const el of candidates) {
                        if (el.scrollHeight > el.clientHeight + 5) {
                            const style = window.getComputedStyle(el);
                            if (['auto', 'scroll', 'overlay'].includes(style.overflowY) || el.tagName === 'DIALOG') {
                                if (pos === 'top') {
                                    el.scrollTop = 0;
                                } else if (pos === 'middle') {
                                    el.scrollTop = Math.floor(el.scrollHeight / 2);
                                } else {
                                    el.scrollTop = el.scrollHeight;
                                }
                            }
                        }
                    }
                }""",
                position,
            )
            time.sleep(0.3)
        except Exception:
            pass

    def _click_primary_modal_button(self, modal_loc, button_type: str) -> bool:
        if button_type == "submit":
            selectors = [
                "button[aria-label*='Submit application']:visible",
                "button:has-text('Submit application'):visible",
                "button:has-text('Submit Application'):visible",
                "footer button.artdeco-button--primary:has-text('Submit'):visible",
            ]
        elif button_type == "review":
            selectors = [
                "button[aria-label*='Review your application']:visible",
                "button[aria-label*='Review']:visible",
                "button:has-text('Review'):visible",
                "footer button.artdeco-button--primary:has-text('Review'):visible",
            ]
        else:  # "next"
            selectors = [
                "button[aria-label*='Continue to next step']:visible",
                "button[data-easy-apply-next-button]:visible",
                "button[aria-label*='Next']:visible",
                "button:has-text('Next'):visible",
                "button:has-text('Continue'):visible",
                "footer button.artdeco-button--primary:visible",
            ]

        for scope in (modal_loc, self.page):
            for sel in selectors:
                try:
                    btn = scope.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn_text = (btn.inner_text() or btn.get_attribute("aria-label") or "").strip().lower()
                        if button_type == "next" and ("submit" in btn_text or "review" in btn_text or "back" in btn_text):
                            continue
                        btn.scroll_into_view_if_needed()
                        time.sleep(0.2)
                        btn.click(force=True)
                        return True
                except Exception:
                    continue
        return False

    def _handle_easy_apply_modal(self, job_description: str) -> bool:
        try:
            modal_loc = None
            for _ in range(10):
                modal_loc = self._get_active_modal()
                if modal_loc:
                    break
                time.sleep(0.5)

            if not modal_loc:
                logger.warning("Easy Apply modal did not appear.")
                return False

            max_steps = 15
            same_step_retries = 0
            last_step_signature = ""

            for step in range(1, max_steps + 1):
                time.sleep(1.0)

                modal_loc = self._get_active_modal()
                if not modal_loc:
                    logger.info("Modal is no longer open.")
                    break

                step_signature = modal_loc.evaluate(
                    """modal => {
                        const heading = modal.querySelector('h3, h2, .jobs-easy-apply-content h4, #dialog-header');
                        const hText = heading ? heading.innerText.trim() : '';
                        const pageIndicator = Array.from(modal.querySelectorAll('span, div'))
                            .map(el => el.innerText.trim())
                            .find(t => /^\\d+\\/\\d+\\s*pages?$/i.test(t)) || '';
                        const ctrlIds = Array.from(modal.querySelectorAll('input, select, textarea'))
                            .map(el => el.id || el.name || el.type)
                            .join('|');
                        return `${hText}::${pageIndicator}::${ctrlIds.slice(0, 120)}`;
                    }"""
                )
                heading_name = step_signature.split("::")[0] or f"Step {step}"
                page_ind = step_signature.split("::")[1]
                if page_ind:
                    heading_name = f"{heading_name} ({page_ind})"

                if step_signature == last_step_signature and step > 1:
                    same_step_retries += 1
                    logger.warning(f"Still on '{heading_name}' (retry {same_step_retries}/3) — checking required/error fields")
                else:
                    same_step_retries = 0
                    last_step_signature = step_signature
                    logger.info(f"Easy Apply Step {step}: {heading_name}")

                if same_step_retries >= 3:
                    logger.error(f"Stuck on '{heading_name}' after 3 retries. Aborting this job.")
                    return False

                # 1. Check if Submit button is available
                self._scroll_modal(modal_loc, "bottom")
                if self._click_primary_modal_button(modal_loc, "submit"):
                    logger.info("Clicked 'Submit application'! Waiting for confirmation...")
                    time.sleep(2.5)
                    done_btn = self.page.locator(
                        "button:has-text('Done'):visible, "
                        "button[aria-label='Dismiss']:visible"
                    ).first
                    if done_btn.count() > 0 and done_btn.is_visible():
                        done_btn.click(force=True)
                    else:
                        self.page.keyboard.press("Escape")
                    time.sleep(1.0)
                    return True

                # 2. Scroll to top, fill visible fields, then scroll to bottom and fill any newly revealed fields
                force_refill = same_step_retries > 0
                self._scroll_modal(modal_loc, "top")
                self._fill_modal_fields(modal_loc, job_description=job_description, force_refill=force_refill)

                self._scroll_modal(modal_loc, "bottom")
                self._fill_modal_fields(modal_loc, job_description=job_description, force_refill=False)

                # 3. Ensure resume selected if on Resume step
                self._ensure_resume_selected(modal_loc)

                self._scroll_modal(modal_loc, "bottom")

                # 4. Click Review
                if self._click_primary_modal_button(modal_loc, "review"):
                    logger.info("Clicked 'Review' button")
                    continue

                # 5. Click Next / Continue
                if self._click_primary_modal_button(modal_loc, "next"):
                    logger.info("Clicked 'Next' button")
                    continue

                logger.warning(f"Could not find Next, Review, or Submit button on '{heading_name}'")
                return False

            return False

        except Exception as e:
            logger.error(f"Error handling easy apply modal: {e}")
            return False

    def _ensure_resume_selected(self, modal_loc) -> None:
        try:
            resume_radios = modal_loc.locator("input[type='radio'][name*='resume'], input[type='radio'][id*='resume']")
            if resume_radios.count() > 0:
                checked = modal_loc.locator("input[type='radio'][name*='resume']:checked, input[type='radio'][id*='resume']:checked")
                if checked.count() == 0:
                    resume_radios.first.check(force=True)
                    logger.info("Selected first available resume radio")
                    return
        except Exception:
            pass

    def _resolve_personal_field(
        self, label: str, name_attr: str, id_attr: str, autocomplete_attr: str, placeholder_attr: str
    ) -> Optional[str]:
        combined = f"{label} {name_attr} {id_attr} {autocomplete_attr} {placeholder_attr}".lower()
        profile = parse_resume_details(self._get_resume_text())

        if autocomplete_attr == "given-name" or re.search(r"\b(first\s*name|given\s*name|vorname|prénom|fname|first_name)\b", combined):
            return profile["first_name"] or None
        if autocomplete_attr == "family-name" or re.search(r"\b(last\s*name|family\s*name|surname|nachname|lname|last_name)\b", combined):
            return profile["last_name"] or None
        if autocomplete_attr == "additional-name" or re.search(r"\b(middle\s*name|mname)\b", combined):
            return ""
        if autocomplete_attr == "name" or re.search(r"\b(full\s*name|your\s*name|candidate\s*name|legal\s*name)\b", combined):
            return profile["full_name"] or None
        if autocomplete_attr == "email" or re.search(r"\b(e-?mail)\b", combined):
            return profile["email"] or None
        if autocomplete_attr in ("tel", "tel-national") or re.search(r"\b(phone|mobile|cell|telephone|contact\s*number|whatsapp)\b", combined):
            return profile["phone"] or None
        if re.search(r"\b(linkedin)\b", combined):
            return profile["linkedin"] or None
        if re.search(r"\b(github|portfolio|personal\s*website|website|blog)\b", combined):
            return profile["github"] or None
        if autocomplete_attr in ("address-level2", "city") or re.search(r"\b(city|town|current\s*location|municipality)\b", combined):
            return profile["city"]
        if autocomplete_attr == "country-name" or re.search(r"\b(country\s*of\s*residence|country|nationality|citizenship)\b", combined):
            return profile["country"]

        return None

    def _fill_modal_fields(self, modal_loc, job_description: str = "", force_refill: bool = False) -> None:
        # A. Radio Button Groups FIRST
        self._fill_radio_groups(modal_loc, job_description=job_description, force_refill=force_refill)

        # B. Select Dropdowns
        selects = modal_loc.locator("select").all()
        for select_loc in selects:
            try:
                if not select_loc.is_visible():
                    continue
                handle = select_loc.element_handle()
                if not handle:
                    continue

                label = self._get_field_label(handle)
                if is_cgpa_question(label):
                    logger.info(f"Skipping CGPA/GPA dropdown: [{label}]")
                    continue

                has_error = bool(self._get_field_validation_error_text(handle))

                if any(k in label.lower() for k in ["phone country code", "email address", "country code"]) and not has_error:
                    continue

                options = handle.evaluate(
                    """el => Array.from(el.options)
                        .map(o => ({ text: o.text.trim(), value: o.value }))
                        .filter(o => o.text && !/^(select an option|select|choose|bitte auswählen|--)/i.test(o.text.trim()) && o.value !== '')"""
                )
                if not options:
                    continue

                selected_text = handle.evaluate(
                    "el => el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : ''"
                )
                if (
                    selected_text
                    and not re.match(r"^(select an option|select|choose|bitte auswählen|--)", selected_text.strip(), re.I)
                    and not has_error
                    and not force_refill
                ):
                    continue

                option_names = [o["text"] for o in options]
                chosen_option = self._ask_gemini_choice(label, option_names, job_description=job_description)
                select_loc.scroll_into_view_if_needed()
                select_loc.select_option(label=chosen_option)
                logger.info(f"Selected Dropdown [{label}] -> '{chosen_option}'")
            except Exception as e:
                logger.debug(f"Select dropdown fill error: {e}")

        # C. Text, Number, Tel, Email, and Textarea Inputs
        inputs = modal_loc.locator(
            "input:not([type='radio']):not([type='checkbox']):not([type='file']):not([type='hidden']):not([type='submit']):not([type='button']), "
            "textarea"
        ).all()

        for field_loc in inputs:
            try:
                if not field_loc.is_visible():
                    continue
                handle = field_loc.element_handle()
                if not handle:
                    continue

                field_type = (field_loc.get_attribute("type") or "text").lower()
                if field_type in ("radio", "checkbox", "file", "hidden", "submit", "button"):
                    continue

                label = self._get_field_label(handle)
                name_attr = field_loc.get_attribute("name") or ""
                id_attr = field_loc.get_attribute("id") or ""
                autocomplete_attr = (field_loc.get_attribute("autocomplete") or "").lower()
                placeholder_attr = field_loc.get_attribute("placeholder") or ""

                # Skip CGPA / GPA fields completely
                combined_meta = f"{label} {name_attr} {id_attr} {placeholder_attr}"
                if is_cgpa_question(combined_meta):
                    logger.info(f"Skipping CGPA/GPA field: [{label or name_attr}]")
                    continue

                current_val = (field_loc.input_value() or "").strip()
                err_text = self._get_field_validation_error_text(handle)
                has_error = bool(err_text)

                personal_val = self._resolve_personal_field(
                    label, name_attr, id_attr, autocomplete_attr, placeholder_attr
                )

                if personal_val is not None:
                    if current_val and current_val.lower() not in ("yes", "no", "3") and not has_error:
                        continue
                    if personal_val:
                        field_loc.scroll_into_view_if_needed()
                        field_loc.click(force=True)
                        field_loc.fill(personal_val)
                        if field_loc.get_attribute("role") == "combobox" or "city" in label.lower() or "location" in label.lower():
                            time.sleep(0.5)
                            self.page.keyboard.press("ArrowDown")
                            self.page.keyboard.press("Enter")
                        logger.info(f"Filled Personal Field [{label or name_attr}] -> '{personal_val}'")
                    continue

                if current_val and not has_error:
                    if not (force_refill and current_val.lower() == "yes"):
                        continue

                input_mode = (field_loc.get_attribute("inputmode") or "").lower()
                is_numeric = (
                    field_type == "number"
                    or input_mode in ("numeric", "decimal")
                    or is_numeric_question(label)
                    or any(w in err_text.lower() for w in ["number", "numeric", "decimal", "integer", "whole", "digit"])
                )

                answer = self._ask_gemini(label, job_description=job_description, is_numeric=is_numeric)
                if answer:
                    field_loc.scroll_into_view_if_needed()
                    field_loc.click(force=True)
                    field_loc.fill(str(answer))

                    if field_loc.get_attribute("role") == "combobox" or "city" in label.lower() or "location" in label.lower():
                        time.sleep(0.5)
                        self.page.keyboard.press("ArrowDown")
                        self.page.keyboard.press("Enter")

                    logger.info(f"Filled Input [{label}] (numeric={is_numeric}) -> '{answer}'")
            except Exception as e:
                logger.debug(f"Text input fill error: {e}")

        # D. Required Checkboxes
        checkboxes = modal_loc.locator("input[type='checkbox']").all()
        for cb_loc in checkboxes:
            try:
                handle = cb_loc.element_handle()
                if not handle:
                    continue
                label = self._get_field_label(handle)
                if "follow" in label.lower():
                    continue
                if not cb_loc.is_checked():
                    has_error = bool(self._get_field_validation_error_text(handle))
                    is_req = (
                        cb_loc.get_attribute("required") is not None
                        or has_error
                        or any(w in label.lower() for w in ["agree", "acknowledge", "confirm", "consent", "privacy", "terms", "certify"])
                    )
                    if is_req:
                        self._check_input_reliably(cb_loc, handle)
                        logger.info(f"Checked required checkbox [{label}]")
            except Exception as e:
                logger.debug(f"Checkbox fill error: {e}")

    def _fill_radio_groups(self, modal_loc, job_description: str = "", force_refill: bool = False) -> None:
        try:
            radio_groups = modal_loc.evaluate(
                """modal => {
                    const allRadios = Array.from(modal.querySelectorAll('input[type="radio"], [role="radio"]'))
                        .filter(r => {
                            const n = (r.name || r.id || '').toLowerCase();
                            return !n.includes('resume');
                        });

                    if (allRadios.length === 0) return [];

                    function getOptionRow(r) {
                        if (r.id) {
                            const explicitLbl = modal.querySelector(`label[for="${CSS.escape(r.id)}"]`);
                            if (explicitLbl && explicitLbl.innerText.trim()) {
                                return explicitLbl;
                            }
                        }
                        let curr = r;
                        let bestRow = r.parentElement || r;
                        for (let d = 0; d < 5 && curr && curr !== modal; d++) {
                            const parent = curr.parentElement;
                            if (!parent || parent === modal) break;
                            const radiosInParent = parent.querySelectorAll('input[type="radio"], [role="radio"]').length;
                            if (radiosInParent === 1) {
                                bestRow = parent;
                                if (bestRow.innerText && bestRow.innerText.trim().length > 0) {
                                    break;
                                }
                                curr = parent;
                            } else {
                                break;
                            }
                        }
                        return bestRow;
                    }

                    const visited = new Set();
                    const rawGroups = [];

                    for (const r of allRadios) {
                        if (visited.has(r)) continue;

                        let group = [];
                        if (r.name) {
                            const sameName = allRadios.filter(x => x.name === r.name);
                            if (sameName.length >= 2) {
                                group = sameName;
                            }
                        }

                        if (group.length === 0) {
                            const row = getOptionRow(r);
                            const listContainer = r.closest('fieldset, [role="radiogroup"]') || row.parentElement;
                            if (listContainer && listContainer !== modal) {
                                const inContainer = allRadios.filter(x => listContainer.contains(x));
                                if (inContainer.length >= 2 && inContainer.length <= 10) {
                                    group = inContainer;
                                }
                            }
                        }

                        if (group.length === 0) {
                            group = [r];
                        }

                        group.forEach(x => visited.add(x));
                        rawGroups.push(group);
                    }

                    const result = [];
                    rawGroups.forEach((groupRadios, gIdx) => {
                        const isChecked = groupRadios.some(
                            r => r.checked === true || r.getAttribute('aria-checked') === 'true'
                        );

                        const optionRows = [];
                        const options = groupRadios.map((r, i) => {
                            const uid = `gemini_rg_${gIdx}_${i}`;
                            r.setAttribute('data-gemini-radio-uid', uid);

                            const row = getOptionRow(r);
                            optionRows.push(row);
                            if (row) {
                                row.setAttribute('data-gemini-label-uid', uid);
                            }

                            let text = row ? row.innerText.trim() : '';
                            if (!text) {
                                text = r.getAttribute('aria-label') || r.value || '';
                            }
                            text = text.replace(/\\s+/g, ' ').trim();
                            return { uid, text };
                        }).filter(o => o.text);

                        if (options.length === 0) return;

                        let lca = groupRadios[0].parentElement;
                        while (lca && lca !== modal && !groupRadios.every(r => lca.contains(r))) {
                            lca = lca.parentElement;
                        }
                        if (!lca) lca = modal;

                        let question = '';
                        const cleanQ = (str) => (str || '')
                            .replace(/\\*/g, '')
                            .split('\\n')
                            .map(s => s.trim())
                            .filter(s => s && s.toLowerCase() !== 'required' && !/^\\d+\\s*\\/\\s*\\d+$/.test(s))
                            .join(' ')
                            .trim();

                        const legend = lca.querySelector('legend, .fb-dash-form-element__label');
                        if (legend && cleanQ(legend.innerText)) {
                            question = cleanQ(legend.innerText);
                        }

                        if (!question && lca !== modal) {
                            const clone = lca.cloneNode(true);
                            clone.querySelectorAll('[data-gemini-label-uid], [data-gemini-radio-uid], input, select, textarea, button, [id*="-error"], [id*="-info"]').forEach(n => n.remove());
                            const cand = cleanQ(clone.innerText);
                            if (cand && !options.some(o => o.text.toLowerCase() === cand.toLowerCase())) {
                                question = cand;
                            }
                        }

                        if (!question && lca.previousElementSibling) {
                            const prev = lca.previousElementSibling;
                            const hasControls = prev.querySelectorAll('input:not([type="hidden"]), select, textarea, [role="radio"]').length > 0;
                            if (!hasControls && cleanQ(prev.innerText)) {
                                question = cleanQ(prev.innerText);
                            }
                        }

                        if (!question && lca.parentElement && lca.parentElement !== modal) {
                            const parent = lca.parentElement;
                            const otherControls = Array.from(
                                parent.querySelectorAll('input:not([type="hidden"]), select, textarea, [role="radio"]')
                            ).filter(c => !groupRadios.includes(c));
                            if (otherControls.length === 0) {
                                const clone = parent.cloneNode(true);
                                clone.querySelectorAll('[data-gemini-label-uid], [data-gemini-radio-uid], input, select, textarea, button, [id*="-error"], [id*="-info"]').forEach(n => n.remove());
                                options.forEach(o => {
                                    Array.from(clone.querySelectorAll('div, span, label')).forEach(el => {
                                        if (el.innerText && el.innerText.trim() === o.text) el.remove();
                                    });
                                });
                                const cand = cleanQ(clone.innerText);
                                if (cand) question = cand;
                            }
                        }

                        let hasError = false;
                        const qContainer = lca.parentElement || lca;
                        if (qContainer && qContainer !== modal) {
                            const errNode = qContainer.querySelector('.artdeco-inline-feedback--error, [id*="-error"]');
                            if (errNode && errNode.innerText.trim()) hasError = true;
                        }

                        result.push({
                            question: question || 'Radio Question',
                            isChecked,
                            hasError,
                            options,
                        });
                    });

                    return result;
                }"""
            )

            for group in radio_groups:
                if group["isChecked"] and not group["hasError"] and not force_refill:
                    continue

                options = group["options"]
                if not options:
                    continue

                question = group["question"]
                if is_cgpa_question(question):
                    continue

                option_texts = [o["text"] for o in options]
                chosen_text = self._ask_gemini_choice(question, option_texts, job_description=job_description)

                target_opt = next(
                    (o for o in options if o["text"].strip().lower() == chosen_text.strip().lower()),
                    options[0],
                )
                uid = target_opt["uid"]

                selected = self._select_radio_by_uid(modal_loc, uid)
                logger.info(
                    f"Selected Radio [{question[:80]}] -> '{target_opt['text']}' (verified={selected})"
                )

        except Exception as e:
            logger.debug(f"Radio group processing error: {e}")

    def _select_radio_by_uid(self, modal_loc, uid: str) -> bool:
        try:
            label_loc = modal_loc.locator(f"[data-gemini-label-uid='{uid}']").first
            radio_loc = modal_loc.locator(f"input[data-gemini-radio-uid='{uid}']").first

            def is_radio_selected() -> bool:
                if radio_loc.count() == 0:
                    return False
                return bool(
                    radio_loc.evaluate(
                        "el => el.checked === true || el.getAttribute('aria-checked') === 'true'"
                    )
                )

            if label_loc.count() > 0 and label_loc.is_visible():
                label_loc.scroll_into_view_if_needed()
                time.sleep(0.15)
                try:
                    label_loc.click(timeout=1500)
                except Exception:
                    label_loc.click(force=True)
                time.sleep(0.15)
                if is_radio_selected():
                    return True

            if radio_loc.count() > 0:
                try:
                    radio_loc.scroll_into_view_if_needed()
                    radio_loc.click(force=True)
                    time.sleep(0.15)
                    if is_radio_selected():
                        return True
                except Exception:
                    pass

                try:
                    radio_loc.check(force=True)
                    time.sleep(0.15)
                    if is_radio_selected():
                        return True
                except Exception:
                    pass

                radio_loc.evaluate(
                    """el => {
                        const row = document.querySelector(`[data-gemini-label-uid="${el.getAttribute('data-gemini-radio-uid')}"]`);
                        if (row) row.click();
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set;
                        if (setter) {
                            setter.call(el, true);
                        } else {
                            el.checked = true;
                        }
                        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }"""
                )
                return is_radio_selected()

        except Exception as e:
            logger.debug(f"Radio selection fallback error for {uid}: {e}")
        return False

    def _check_input_reliably(self, cb_loc, handle) -> None:
        try:
            label_el = handle.evaluate_handle(
                "el => (el.id && document.querySelector(`label[for=\"${CSS.escape(el.id)}\"]`)) || el.closest('label')"
            )
            if label_el and label_el.as_element():
                label_el.as_element().click(force=True)
            if not cb_loc.is_checked():
                cb_loc.check(force=True)
        except Exception:
            try:
                cb_loc.click(force=True)
            except Exception:
                pass

    def _ask_gemini(self, question: str, job_description: str = "", is_numeric: bool = False) -> str:
        if is_cgpa_question(question):
            return ""

        resume_text = self._get_resume_text()
        profile = parse_resume_details(resume_text)

        # Handle common HR questions cleanly (reasonable adjustments, start availability, etc.)
        if not is_numeric:
            from gemini_engine import get_deterministic_hr_answer
            hr_ans = get_deterministic_hr_answer(question, profile)
            if hr_ans:
                return hr_ans

        if self.gemini and question:
            try:
                ans = self.gemini.answer_screening_question(
                    resume_text=resume_text,
                    question_text=question,
                    job_description=job_description,
                    is_numeric=is_numeric,
                    job_location=self.current_country,
                )
                if ans and str(ans).strip():
                    return str(ans).strip()
            except Exception as e:
                logger.warning(f"Gemini question query failed for '{question}': {e}")

        if is_salary_question(question) and self.gemini:
            return self.gemini.get_salary_expectation(
                question_text=question,
                job_location=self.current_country,
                numeric_only=is_numeric,
                resume_text=resume_text,
            )

        if is_numeric and self.gemini:
            return self.gemini.estimate_skill_years_from_resume(resume_text, question)

        total_yoe_int = min(int(round(profile["total_yoe"])), MAX_ALLOWED_EXPERIENCE_YEARS)
        if is_numeric:
            return str(total_yoe_int)

        q_lower = (question or "").lower()
        if any(w in q_lower for w in ["experience", "describe", "tell us", "why", "project", "skill", "background"]):
            top_skills = ", ".join(profile["keywords"][:6])
            return f"I have {total_yoe_int} years of experience working with {top_skills}."
        return "N/A"

    def _ask_gemini_choice(self, question: str, options: list[str], job_description: str = "") -> str:
        if not options:
            return ""
        if len(options) == 1:
            return options[0]

        q_lower = (question or "").lower()
        profile = parse_resume_details(self._get_resume_text())

        # Deterministic Country of Residence / Nationality match before calling Gemini
        if any(w in q_lower for w in ["country of residence", "current country", "country you live", "country you reside", "nationality", "citizenship", "where are you located"]):
            home_country = (profile.get("country") or "Pakistan").strip().lower()
            for opt in options:
                if opt.strip().lower() == home_country or home_country in opt.strip().lower():
                    return opt
            for fallback_kw in ["other", "outside", "not listed", "international", "none of the above"]:
                for opt in options:
                    if fallback_kw in opt.strip().lower():
                        return opt

        if self.gemini:
            try:
                choice = self.gemini.answer_multiple_choice_question(
                    resume_text=self._get_resume_text(),
                    question_text=question,
                    options=options,
                    job_description=job_description,
                    job_location=self.current_country,
                )
                if choice and choice in options:
                    return choice
            except Exception as e:
                logger.warning(f"Gemini multiple-choice query failed for '{question}': {e}")

        yes_opt = next((o for o in options if o.strip().lower() == "yes"), None)
        if yes_opt:
            return yes_opt
        return options[0]
    
    def _ask_gemini(self, question: str, job_description: str = "", is_numeric: bool = False) -> str:
        if is_cgpa_question(question):
            return ""

        resume_text = self._get_resume_text()
        profile = parse_resume_details(resume_text)

        # Handle common HR questions cleanly (reasonable adjustments, start availability, etc.)
        if not is_numeric:
            from gemini_engine import get_deterministic_hr_answer
            hr_ans = get_deterministic_hr_answer(question, profile)
            if hr_ans:
                return hr_ans

        if self.gemini and question:
            try:
                ans = self.gemini.answer_screening_question(
                    resume_text=resume_text,
                    question_text=question,
                    job_description=job_description,
                    is_numeric=is_numeric,
                    job_location=self.current_country,
                )
                if ans and str(ans).strip():
                    return str(ans).strip()
            except Exception as e:
                logger.warning(f"Gemini question query failed for '{question}': {e}")

        if is_salary_question(question) and self.gemini:
            return self.gemini.get_salary_expectation(
                question_text=question,
                job_location=self.current_country,
                numeric_only=is_numeric,
                resume_text=resume_text,
            )

        if is_numeric and self.gemini:
            return self.gemini.estimate_skill_years_from_resume(resume_text, question)

        total_yoe_int = min(int(round(profile["total_yoe"])), MAX_ALLOWED_EXPERIENCE_YEARS)
        if is_numeric:
            return str(total_yoe_int)

        q_lower = (question or "").lower()
        if any(w in q_lower for w in ["experience", "describe", "tell us", "why", "project", "skill", "background"]):
            top_skills = ", ".join(profile["keywords"][:6])
            return f"I have {total_yoe_int} years of experience working with {top_skills}."
        return "N/A"

    def _ask_gemini_choice(self, question: str, options: list[str], job_description: str = "") -> str:
        if not options:
            return ""
        if len(options) == 1:
            return options[0]

        q_lower = (question or "").lower()
        profile = parse_resume_details(self._get_resume_text())

        # Deterministic Country of Residence / Nationality match before calling Gemini
        if any(w in q_lower for w in ["country of residence", "current country", "country you live", "country you reside", "nationality", "citizenship", "where are you located"]):
            home_country = (profile.get("country") or "Pakistan").strip().lower()
            for opt in options:
                if opt.strip().lower() == home_country or home_country in opt.strip().lower():
                    return opt
            for fallback_kw in ["other", "outside", "not listed", "international", "none of the above"]:
                for opt in options:
                    if fallback_kw in opt.strip().lower():
                        return opt

        if self.gemini:
            try:
                choice = self.gemini.answer_multiple_choice_question(
                    resume_text=self._get_resume_text(),
                    question_text=question,
                    options=options,
                    job_description=job_description,
                    job_location=self.current_country,
                )
                if choice and choice in options:
                    return choice
            except Exception as e:
                logger.warning(f"Gemini multiple-choice query failed for '{question}': {e}")

        yes_opt = next((o for o in options if o.strip().lower() == "yes"), None)
        if yes_opt:
            return yes_opt
        return options[0]

    def _get_field_validation_error_text(self, field) -> str:
        try:
            return field.evaluate(
                """el => {
                    const isCounter = (txt) => /^\\d+\\s*\\/\\s*\\d+$/.test((txt || '').trim());
                    const ariaDesc = el.getAttribute('aria-describedby');
                    if (ariaDesc) {
                        for (const id of ariaDesc.split(/\\s+/)) {
                            const node = document.getElementById(id);
                            if (node && node.innerText.trim() && !isCounter(node.innerText)) {
                                return node.innerText.trim();
                            }
                        }
                    }
                    let curr = el.parentElement;
                    for (let i = 0; i < 4 && curr; i++) {
                        const err = curr.querySelector('.artdeco-inline-feedback--error, [id*="-error"]');
                        if (err && err.innerText.trim() && !isCounter(err.innerText)) {
                            return err.innerText.trim();
                        }
                        curr = curr.parentElement;
                    }
                    return '';
                }"""
            ) or ""
        except Exception:
            return ""

    def _get_field_label(self, field) -> str:
        try:
            label_text = field.evaluate(
                """el => {
                    const cleanText = (raw) => {
                        if (!raw) return '';
                        const lines = raw
                            .replace(/\\*/g, '')
                            .split('\\n')
                            .map(s => s.trim())
                            .filter(s =>
                                s &&
                                s.toLowerCase() !== 'required' &&
                                !/^\\d+\\s*\\/\\s*\\d+$/.test(s) &&
                                !/^(please enter a valid|this field is required|enter a whole number)/i.test(s)
                            );
                        return Array.from(new Set(lines)).join(' ').trim();
                    };

                    if (el.id) {
                        const explicit = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                        const txt = cleanText(explicit?.innerText);
                        if (txt) return txt;
                    }

                    const labelledBy = el.getAttribute('aria-labelledby');
                    if (labelledBy) {
                        const texts = labelledBy
                            .split(/\\s+/)
                            .map(id => cleanText(document.getElementById(id)?.innerText))
                            .filter(Boolean);
                        if (texts.length > 0) return texts.join(' ');
                    }

                    const aria = cleanText(el.getAttribute('aria-label'));
                    if (aria) return aria;

                    let curr = el;
                    for (let depth = 0; depth < 6 && curr; depth++) {
                        const parent = curr.parentElement;
                        if (!parent) break;
                        const tag = parent.tagName.toLowerCase();
                        if (tag === 'form' || tag === 'dialog' || parent.getAttribute('role') === 'dialog') break;

                        if (curr.previousElementSibling) {
                            const prev = curr.previousElementSibling;
                            const prevControls = prev.querySelectorAll(
                                'input:not([type="hidden"]), select, textarea, [role="radio"]'
                            );
                            if (prevControls.length === 0) {
                                const prevTxt = cleanText(prev.innerText);
                                if (prevTxt) return prevTxt;
                            }
                        }

                        const allControls = parent.querySelectorAll(
                            'input:not([type="hidden"]), select, textarea, [role="radio"]'
                        );
                        if (allControls.length === 1) {
                            const lbl = parent.querySelector('label, legend, .fb-dash-form-element__label');
                            if (lbl && cleanText(lbl.innerText)) {
                                return cleanText(lbl.innerText);
                            }

                            const clone = parent.cloneNode(true);
                            clone.querySelectorAll(
                                'input, select, textarea, button, option, svg, [id*="-error"], [id*="-info"], .artdeco-inline-feedback--error'
                            ).forEach(n => n.remove());
                            const cand = cleanText(clone.innerText);
                            if (cand) return cand;

                            curr = parent;
                        } else {
                            break;
                        }
                    }

                    return cleanText(el.getAttribute('placeholder')) || '';
                }"""
            )
            return (label_text or "").strip()
        except Exception:
            return ""

    def _dismiss_stuck_modal(self) -> None:
        try:
            dismiss_btn = self.page.locator(
                "dialog button[aria-label='Dismiss']:visible, "
                "div.artdeco-modal button[aria-label='Dismiss']:visible, "
                "button.artdeco-modal__dismiss:visible"
            ).first
            if dismiss_btn.count() > 0 and dismiss_btn.is_visible():
                dismiss_btn.click(force=True)
                time.sleep(0.5)
                discard_btn = self.page.locator(
                    "button[data-control-name='discard_application_confirm_btn']:visible, "
                    "button:has-text('Discard'):visible"
                ).first
                if discard_btn.count() > 0 and discard_btn.is_visible():
                    discard_btn.click(force=True)
                    time.sleep(0.5)
        except Exception:
            pass

    def _get_resume_text(self) -> str:
        """Reads resume.txt dynamically from disk on every call (with matcher fallback)."""
        return load_resume_text(getattr(self.matcher, "resume_text", "") or "")

    def _get_external_apply_link(self, card) -> Optional[str]:
        try:
            external_link = card.query_selector(
                "a[href*='apply'], a[aria-label*='Apply on company website']"
            )
            if external_link:
                return external_link.get_attribute("href")
        except Exception:
            pass
        return None

    def _log_external_job(self, job_data: dict, external_url: str, match_score: float) -> bool:
        try:
            job_data["url"] = external_url
            job_data["match_score"] = match_score
            job_data["status"] = "EXTERNAL_PENDING"
            job_data["applied_at"] = datetime.now().isoformat()
            log_job_application(job_data)
            logger.info(f"Logged external job: {job_data['id']} {external_url}")
            return True
        except Exception as e:
            logger.error(f"Error logging external job: {e}")
            return False


__all__ = ["LinkedInDriver"]