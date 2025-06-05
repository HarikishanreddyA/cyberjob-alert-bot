# -*- coding: utf-8 -*-
"""
Optimized Cybersecurity Job Alert System
- Two-stage filtering for speed
- Full LinkedIn description fetching via requests
- Filters: clearance, 3+ years experience, sponsorship requirements
- Parallel processing for maximum speed
- Designed for hourly execution
"""

from jobspy import scrape_jobs
import requests
import time
import os
import json
from datetime import datetime
import concurrent.futures
from functools import lru_cache
import re
from bs4 import BeautifulSoup
import random
from threading import Lock

# Configuration
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SEEN_JOBS_FILE = "seen_jobs.json"
MAX_JOBS_TO_KEEP = 1000
MAX_STAGE2_JOBS = 20  # Limit deep filtering for speed
DESCRIPTION_TIMEOUT = 10  # Timeout per description fetch

# Search configuration - optimized for entry-level positions
SEARCH_TERMS = [
    "junior security analyst",
    "entry level cybersecurity", 
    "SOC analyst entry level",
    "information security analyst",
    "cybersecurity analyst"
]

EXPERIENCE_LEVELS = ["entry level", "internship", "associate"]
PLATFORMS = ["linkedin"]

# Stage 1 Filters (Quick filtering - no API calls)
TITLE_KEYWORDS = re.compile(r'cyber|security|soc|grc|infosec|threat|incident response|vulnerability|detection|cloud security|security analyst|security engineer|malware|siem|log analysis|risk|appsec', re.I)
REJECT_TITLE = re.compile(r'senior|sr\.|manager|lead|director|principal|architect|vp|vice president|chief|head of|operations manager', re.I)
SOURCE_REJECT = re.compile(r'dice|lensa|jobs via dice|jobs via lensa|via dice|via lensa', re.I)
EASY_APPLY = re.compile(r'easy apply|quick apply|1-click apply|1 click apply|apply now|apply with your profile|apply with linkedin', re.I)

# Stage 2 Filters (Deep filtering - requires full description)
CLEARANCE_KEYWORDS = re.compile(r'security clearance|secret clearance|top secret|ts/sci|clearance required|government clearance|dod clearance|federal clearance|clearability|able to obtain clearance', re.I)
EXPERIENCE_REJECT = re.compile(r'(?:minimum|at least|requires?|must have)?\s*(?:3\+?|three|four|4\+?|five|5\+?|six|6\+?|seven|7\+?|eight|8\+?|nine|9\+?|ten|10\+?|1[0-9]|2[0-9])\s*(?:\+)?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:(?:non-internship\s+)?(?:professional\s+)?(?:software\s+)?(?:development\s+)?(?:design\s+)?(?:architecture\s+)?(?:experience|exp)|experience|exp)(?!\s+(?:preferred|desired|plus|a plus|helpful|nice to have))', re.I)
SPONSORSHIP_REJECT = re.compile(r'(?:no|not|does not|will not|cannot|unable to)\s+(?:provide|offer|sponsor)\s+(?:visa|sponsorship|work authorization)|us citizens only|must be (?:us citizen|authorized to work)|citizen.*required|no sponsorship|visa sponsorship not available|eligible to work (?:in|for) (?:us|usa)|must be legally authorized', re.I)

# Cache seen jobs in memory
SEEN_JOBS = set()
session_lock = Lock()

class OptimizedLinkedInFetcher:
    """Fast LinkedIn description fetcher using requests with proper headers"""
    
    def __init__(self):
        self.session = None
        self.initialized = False
        self.request_count = 0
        self.max_requests = 50  # Reset session after 50 requests to avoid blocks
        
    def _get_headers(self):
        """Browser-like headers to avoid detection"""
        return {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
        }
    
    def _initialize_session(self):
        """Initialize session with LinkedIn cookies"""
        try:
            if self.session:
                self.session.close()
                
            self.session = requests.Session()
            headers = self._get_headers()
            
            # Get cookies from LinkedIn homepage
            response = self.session.get('https://www.linkedin.com', 
                                     headers=headers, timeout=5)
            
            if response.status_code == 200:
                headers['Referer'] = 'https://www.linkedin.com/'
                self.session.headers.update(headers)
                self.initialized = True
                self.request_count = 0
                return True
            return False
                
        except Exception:
            return False
    
    def get_job_description(self, job_url):
        """Get full job description from LinkedIn job URL"""
        # Reset session if too many requests
        if self.request_count >= self.max_requests:
            self.initialized = False
            
        if not self.initialized:
            if not self._initialize_session():
                return None
        
        try:
            # Random delay to be respectful
            time.sleep(random.uniform(0.5, 1.5))
            
            response = self.session.get(job_url, timeout=DESCRIPTION_TIMEOUT)
            self.request_count += 1
            
            if response.status_code != 200:
                return None
            
            # Check if redirected to login
            if 'signin' in response.url or 'login' in response.url:
                return None
            
            # Parse HTML for job description
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Primary selector (most reliable)
            element = soup.select_one('div.show-more-less-html__markup')
            if element and element.get_text(strip=True):
                return element.get_text(strip=True)
            
            # Fallback selectors
            for selector in ['div.show-more-less-html', 'div.description__text']:
                element = soup.select_one(selector)
                if element and element.get_text(strip=True):
                    return element.get_text(strip=True)
            
            return None
            
        except Exception:
            return None

# Global fetcher instance
fetcher = OptimizedLinkedInFetcher()

@lru_cache(maxsize=1000)
def check_title_match(title):
    """Cache title matches for performance"""
    return bool(TITLE_KEYWORDS.search(title))

def load_seen_jobs():
    """Load previously seen jobs from file"""
    global SEEN_JOBS
    if os.path.exists(SEEN_JOBS_FILE):
        try:
            with open(SEEN_JOBS_FILE, "r") as f:
                jobs_data = json.load(f)
                SEEN_JOBS = set(jobs_data.get("seen_jobs", []))
        except json.JSONDecodeError:
            SEEN_JOBS = set()
    else:
        SEEN_JOBS = set()

def save_seen_jobs():
    """Save seen jobs to file (keep last 1000)"""
    jobs_list = list(SEEN_JOBS)[-MAX_JOBS_TO_KEEP:]
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump({"seen_jobs": jobs_list, "last_updated": datetime.now().isoformat()}, f, indent=2)

def stage1_filter(job):
    """Stage 1: Quick filtering without API calls"""
    url = str(job.get("job_url", ""))
    
    # Skip if already seen
    if url in SEEN_JOBS:
        return None, "seen"

    title = str(job.get("title", "")).lower()
    description = str(job.get("description", "")).lower() if job.get("description") else ""
    source = str(job.get("via", "")).lower()
    company = str(job.get("company", "")).lower()

    # Filter bad sources
    if SOURCE_REJECT.search(source) or SOURCE_REJECT.search(company):
        return None, "source"

    # Title keyword matching
    if not check_title_match(title):
        return None, "title_keywords"

    # Reject senior positions
    if REJECT_TITLE.search(title):
        return None, "title_reject"

    # Filter easy apply jobs
    if EASY_APPLY.search(f"{title} {description}"):
        return None, "easy_apply"

    return job, "stage1_passed"

def stage2_filter_single(job):
    """Stage 2: Deep filtering using full job description"""
    url = job.get("job_url", "")
    
    # Only process LinkedIn jobs for deep filtering
    if "linkedin.com" not in url:
        return job, "stage2_passed"
    
    try:
        # Get full job description
        description = fetcher.get_job_description(url)
        
        if not description:
            # If can't get description, don't filter (avoid false negatives)
            return job, "stage2_passed"
        
        description_lower = description.lower()
        
        # Check for security clearance requirement
        if CLEARANCE_KEYWORDS.search(description):
            return None, "clearance_required"
        
        # Check for 3+ years experience requirement
        if EXPERIENCE_REJECT.search(description):
            return None, "experience_required"
            
        # Check for sponsorship restrictions
        if SPONSORSHIP_REJECT.search(description):
            return None, "sponsorship_required"
        
        return job, "stage2_passed"
        
    except Exception:
        # On error, let job pass (don't lose jobs due to technical issues)
        return job, "stage2_passed"

def process_jobs_batch(jobs_batch):
    """Process jobs with optimized two-stage filtering"""
    final_jobs = []
    filter_counts = {
        "seen": 0, "source": 0, "title_keywords": 0, "title_reject": 0, 
        "easy_apply": 0, "stage1_passed": 0, "clearance_required": 0, 
        "experience_required": 0, "sponsorship_required": 0, "stage2_passed": 0
    }
    
    if jobs_batch.empty:
        return final_jobs, filter_counts

    # Stage 1: Quick filtering (fast, no API calls)
    stage1_jobs = []
    for job in jobs_batch.itertuples():
        job_dict = job._asdict()
        filtered_job, reason = stage1_filter(job_dict)
        filter_counts[reason] += 1
        
        if filtered_job:
            stage1_jobs.append(filtered_job)
            SEEN_JOBS.add(filtered_job["job_url"])

    print(f"📊 Stage 1: {len(stage1_jobs)} jobs passed initial filtering")

    # Stage 2: Deep filtering (parallel processing for speed)
    linkedin_jobs = [job for job in stage1_jobs if "linkedin.com" in job.get("job_url", "")]
    other_jobs = [job for job in stage1_jobs if "linkedin.com" not in job.get("job_url", "")]
    
    # Non-LinkedIn jobs skip deep filtering
    final_jobs.extend(other_jobs)
    
    if linkedin_jobs:
        # Limit jobs for speed (process first N jobs only)
        jobs_to_process = linkedin_jobs[:MAX_STAGE2_JOBS]
        if len(linkedin_jobs) > MAX_STAGE2_JOBS:
            print(f"⚡ Speed optimization: Processing only first {MAX_STAGE2_JOBS} LinkedIn jobs")
        
        print(f"🔍 Stage 2: Deep filtering {len(jobs_to_process)} LinkedIn jobs in parallel...")
        
        # Parallel description fetching and filtering
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_job = {executor.submit(stage2_filter_single, job): job for job in jobs_to_process}
            
            for future in concurrent.futures.as_completed(future_to_job, timeout=60):
                try:
                    filtered_job, reason = future.result()
                    filter_counts[reason] += 1
                    
                    if filtered_job:
                        final_jobs.append(filtered_job)
                except Exception:
                    # If individual job processing fails, add it anyway (don't lose jobs)
                    job = future_to_job[future]
                    final_jobs.append(job)
                    filter_counts["stage2_passed"] += 1
    
    print(f"✅ Final: {len(final_jobs)} jobs passed all filters")
    return final_jobs, filter_counts

def post_to_slack(message, max_retries=2):
    """Post message to Slack with retry logic"""
    if not SLACK_WEBHOOK_URL:
        print("⚠️ No Slack webhook URL configured")
        return False
        
    for attempt in range(max_retries):
        try:
            response = requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException:
            if attempt == max_retries - 1:
                print(f"❌ Failed to send to Slack after {max_retries} attempts")
                return False
            time.sleep(1)

def main():
    """Main execution function"""
    start_time = time.time()
    load_seen_jobs()
    all_new_jobs = []
    total_filter_counts = {
        "seen": 0, "source": 0, "title_keywords": 0, "title_reject": 0, 
        "easy_apply": 0, "stage1_passed": 0, "clearance_required": 0, 
        "experience_required": 0, "sponsorship_required": 0, "stage2_passed": 0
    }

    try:
        print(f"🚀 Starting optimized job search at {datetime.now()}")
        
        # Parallel job scraping across search terms
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_term = {
                executor.submit(
                    scrape_jobs,
                    site_name=PLATFORMS,
                    search_term=term,
                    location="United States",
                    results_wanted=10,  # Reduced for speed
                    hours_old=2,  # 2 hours to catch more jobs
                    experience_level=EXPERIENCE_LEVELS,
                    country_indeed="USA",
                    remote_only=False,
                    verbose=0
                ): term for term in SEARCH_TERMS
            }

            # Process results as they complete
            for future in concurrent.futures.as_completed(future_to_term, timeout=180):
                try:
                    jobs = future.result()
                    if not jobs.empty:
                        filtered, counts = process_jobs_batch(jobs)
                        all_new_jobs.extend(filtered)
                        for key in total_filter_counts:
                            total_filter_counts[key] += counts[key]
                except Exception as e:
                    print(f"❌ Error scraping: {e}")

        # Send results to Slack
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        if not all_new_jobs:
            message = f"🔍 No new entry-level cybersecurity jobs found (as of {timestamp})."
            post_to_slack(message)
        else:
            # Summary header
            header = (
                f"🔔 *New Entry-Level Cybersecurity Jobs ({timestamp}):*\n"
                f"📊 Found {len(all_new_jobs)} jobs | "
                f"Filtered: {total_filter_counts['clearance_required']} clearance, "
                f"{total_filter_counts['experience_required']} experience, "
                f"{total_filter_counts['sponsorship_required']} sponsorship\n"
                f"-------------------"
            )
            post_to_slack(header)

            # Individual job postings
            for job in all_new_jobs:
                message = (
                    f"*{job.get('title', 'No Title')}* at *{job.get('company', 'No Company')}*\n"
                    f"📍 {job.get('location', 'N/A')} | 🕐 {job.get('date_posted', 'N/A')}\n"
                    f"🔗 <{job.get('job_url', '')}>"
                )
                post_to_slack(message)
                time.sleep(0.5)  # Brief delay between messages

        # Save seen jobs
        save_seen_jobs()
        
        # Performance metrics
        elapsed = time.time() - start_time
        print(f"⚡ Completed in {elapsed:.1f} seconds")
        print(f"✅ {len(all_new_jobs)} jobs posted to Slack")
        print(f"📊 Deep filters: {total_filter_counts['clearance_required']} clearance, {total_filter_counts['experience_required']} experience, {total_filter_counts['sponsorship_required']} sponsorship")

        # Auto-commit to GitHub (if running in GitHub Actions)
        if os.getenv("GITHUB_ACTIONS") == "true":
            try:
                os.system('git config --global user.name "CyberJobBot"')
                os.system('git config --global user.email "github-actions@github.com"')
                os.system('git add seen_jobs.json')
                os.system('git commit -m "Update seen jobs [skip ci]"')
                repo_url = f"https://x-access-token:{os.getenv('GITHUB_TOKEN')}@github.com/{os.getenv('GITHUB_REPOSITORY')}.git"
                os.system(f'git remote set-url origin "{repo_url}"')
                os.system('git push')
            except Exception as e:
                print(f"❌ GitHub update error: {e}")
    
    except Exception as e:
        print(f"❌ Error in main execution: {e}")
        raise

if __name__ == "__main__":
    main()
