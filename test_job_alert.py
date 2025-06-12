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
SLACK_TEST_URL = os.getenv("SLACK_TEST")  # Matches env var name
SEEN_JOBS_FILE = "seen_main_jobs.json"  # Separate file from internships
MAX_JOBS_TO_KEEP = 1000
MAX_STAGE2_JOBS = 50  # Increased for comprehensive filtering (was 20)
DESCRIPTION_TIMEOUT = 10  # Timeout per description fetch

# Search configuration - comprehensive entry-level cybersecurity positions
SEARCH_TERMS = [
    # Core Security Analyst Roles
    "junior security analyst",
    "entry level cybersecurity", 
    "SOC analyst entry level",
    "information security analyst",
    "cybersecurity analyst",
    
    # Security Engineering
    "junior security engineer",
    "entry level security engineer",
    "cybersecurity engineer",
    
    # DevSecOps & Application Security
    "junior devsecops",
    "entry level devsecops",
    "junior application security",
    "appsec analyst",
    
    # Penetration Testing & Red Team
    "junior penetration tester",
    "entry level pentester",
    "junior ethical hacker",
    
    # GRC & Compliance
    "junior GRC analyst", 
    "entry level compliance analyst",
    "junior risk analyst",
    "cybersecurity compliance",
    
    # Cloud Security
    "junior cloud security",
    "entry level cloud security analyst",
    "cloud security engineer junior",
    
    # Incident Response & Threat Analysis
    "junior incident response",
    "entry level threat analyst",
    "junior malware analyst",
    "cybersecurity incident response",
    "junior threat detection",
    "entry level threat detection",
    "threat detection analyst",
    
    # Vulnerability Management
    "junior vulnerability analyst",
    "vulnerability management analyst",
    "security assessment analyst",
    
    # Network Security
    "junior network security",
    "network security analyst entry level",
    
    # Digital Forensics
    "junior digital forensics",
    "entry level cyber forensics",
    
    # General Entry Level Terms
    "cybersecurity intern",
    "security intern",
    "entry level infosec"
]

EXPERIENCE_LEVELS = ["entry level", "internship", "associate"]
PLATFORMS = ["linkedin"]

# Stage 1 Filters (Quick filtering - no API calls)
TITLE_KEYWORDS = re.compile(r'cyber|security|soc|grc|infosec|threat|incident response|vulnerability|detection|cloud security|security analyst|security engineer|malware|siem|log analysis|risk|appsec', re.I)
REJECT_TITLE = re.compile(r'senior|sr\.|manager|lead|director|principal|architect|vp|vice president|chief|head of|operations manager', re.I)
SOURCE_REJECT = re.compile(r'dice|lensa|jobs via dice|jobs via lensa|via dice|via lensa', re.I)
# Note: Easy Apply filtering removed - not available in scraped data

# Stage 2 Filters (Deep filtering - requires full description)
CLEARANCE_KEYWORDS = re.compile(r'security clearance|secret clearance|top secret|ts/sci|clearance required|government clearance|dod clearance|federal clearance|clearability|able to obtain clearance', re.I)

# Comprehensive experience regex to catch ALL edge cases
EXPERIENCE_REJECT = re.compile(r'''
    (?:
        # Direct experience requirements
        (?:minimum|min|at\s+least|requires?|must\s+have|need|needs?|looking\s+for|seeking|should\s+have|candidate\s+should|we\s+require|requires|prefer|preferably)\s+
        (?:
            # Patterns like "3+", "5-7", "4 to 12", "minimum 5", etc.
            (?:3\+?|4\+?|5\+?|6\+?|7\+?|8\+?|9\+?|10\+?|1[1-9]|[2-9]\d)\s*(?:\+|plus)?\s*(?:years?|yrs?|y)
            |
            (?:3|4|5|6|7|8|9|10|1[1-9]|[2-9]\d)\s*(?:-|to|or\s+more|\s+to\s+)\s*(?:5|6|7|8|9|10|1[1-9]|[2-9]\d|more)\s*(?:years?|yrs?|y)
            |
            (?:three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen)\s+(?:years?|yrs?)
            |
            (?:3|4|5|6|7|8|9|10|1[1-9]|[2-9]\d)\s*(?:\+|plus)?\s*(?:years?|yrs?|y)\s+(?:of\s+)?(?:experience|exp|background|work)
        )
        |
        # Patterns with experience first
        (?:
            (?:3\+?|4\+?|5\+?|6\+?|7\+?|8\+?|9\+?|10\+?|1[1-9]|[2-9]\d)\s*(?:\+|plus)?\s*(?:years?|yrs?|y)\s+
            (?:of\s+)?(?:experience|exp|background)\s+(?:in|with|of|working)
            |
            (?:3|4|5|6|7|8|9|10|1[1-9]|[2-9]\d)\s*(?:-|to)\s*(?:5|6|7|8|9|10|1[1-9]|[2-9]\d)\s*(?:years?|yrs?|y)\s+
            (?:of\s+)?(?:experience|exp|background)\s+(?:in|with|of|working)
        )
        |
        # Alternative patterns
        (?:
            (?:experience|background|expertise)\s+(?:of\s+)?(?:at\s+least\s+)?(?:3\+?|4\+?|5\+?|6\+?|7\+?|8\+?|9\+?|10\+?|1[1-9]|[2-9]\d)\s*(?:\+|plus)?\s*(?:years?|yrs?)
            |
            (?:3\+?|4\+?|5\+?|6\+?|7\+?|8\+?|9\+?|10\+?|1[1-9]|[2-9]\d)\s*(?:\+|plus)?\s*(?:years?|yrs?)\s+(?:minimum|min|or\s+more)
            |
            (?:minimum|min)\s+of\s+(?:3|4|5|6|7|8|9|10|1[1-9]|[2-9]\d)\s*(?:\+)?\s*(?:years?|yrs?)
        )
    )
    (?!\s*(?:preferred|desired|plus|a\s+plus|helpful|nice\s+to\s+have|would\s+be\s+nice|would\s+be\s+great|bonus|advantageous|ideal|good\s+to\s+have))
''', re.I | re.VERBOSE)

SPONSORSHIP_REJECT = re.compile(r'(?:no|not|does not|will not|cannot|unable to)\s+(?:provide|offer|sponsor)\s+(?:visa|sponsorship|work authorization)|us citizens only|must be (?:us citizen|authorized to work)|citizen.*required|no sponsorship|visa sponsorship not available|eligible to work (?:in|for) (?:us|usa)|must be legally authorized', re.I)

# Easy Apply detection (add back to Stage 1 for faster filtering)
EASY_APPLY_REJECT = re.compile(r'easy apply|quick apply|1-click apply|1 click apply|apply now|apply with your profile|apply with linkedin|one click|instant apply', re.I)

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
    
    # Check for Easy Apply in basic description (faster filtering)
    full_text = f"{title} {description}"
    if EASY_APPLY_REJECT.search(full_text):
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
        "seen": 0, "source": 0, "title_keywords": 0, "title_reject": 0, "easy_apply": 0,
        "stage1_passed": 0, "clearance_required": 0, 
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
    if not SLACK_TEST_URL:
        print("⚠️ SLACK_TEST environment variable not set")
        return False
        
    # Slack webhook payload with CyberJobs Notifier branding
    payload = {
        "text": message,
        "username": "CyberJobs Notifier",
        "icon_emoji": ":bell:"
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.post(SLACK_TEST_URL, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"❌ Slack API error (attempt {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                print(f"❌ Failed to send to Slack after {max_retries} attempts")
                return False
            time.sleep(1)

def main():
    """Main execution function"""
    # Debug: Check if Slack webhook is configured
    if SLACK_TEST_URL:
        print(f"✅ Slack webhook configured (ends with: ...{SLACK_TEST_URL[-10:]})")
    else:
        print("❌ SLACK_TEST environment variable not found!")
        return
        
    start_time = time.time()
    load_seen_jobs()
    all_new_jobs = []
    total_filter_counts = {
        "seen": 0, "source": 0, "title_keywords": 0, "title_reject": 0, "easy_apply": 0,
        "stage1_passed": 0, "clearance_required": 0, 
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
                    results_wanted=30,  # Reduced for quality over quantity
                    hours_old=1,  # Only last hour for fresh jobs
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

                # Send results to Slack as one grouped message
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Calculate total jobs processed
        total_processed = sum(total_filter_counts.values())
        
        # Build complete message with statistics and all jobs
        if not all_new_jobs:
            message = f"🔍 No new cybersecurity jobs found in the last hour (as of {timestamp})."
        else:
            # Start with header and statistics
            message_parts = [
                f":bell: *New Cybersecurity Jobs (fetched at {timestamp}):*",
                f":bar_chart: *Job Statistics:*",
                f"• Total jobs processed: {total_processed}",
                f"• Jobs posted: {len(all_new_jobs)}",
                f"• Jobs filtered out:",
                f"  - Already seen: {total_filter_counts['seen']}",
                f"  - Source (Dice/Lensa): {total_filter_counts['source']}",
                f"  - Title mismatch: {total_filter_counts['title_keywords']}",
                f"  - Senior/Manager: {total_filter_counts['title_reject']}",
                f"  - Easy Apply: {total_filter_counts['easy_apply']}",
                f"  - Security clearance: {total_filter_counts['clearance_required']}",
                f"  - 3+ years experience: {total_filter_counts['experience_required']}",
                f"  - Sponsorship restrictions: {total_filter_counts['sponsorship_required']}",
                f"-------------------",
                f"*📋 Job Listings:*"
            ]
            
            # Add all job listings
            for i, job in enumerate(all_new_jobs, 1):
                job_entry = (
                    f"\n{i}. *{job.get('title', 'No Title')}* at *{job.get('company', 'No Company')}*\n"
                    f"   📍 {job.get('location', 'N/A')} | 🕐 {job.get('date_posted', 'N/A')}\n"
                    f"   🔗 <{job.get('job_url', '')}|Apply Here>"
                )
                message_parts.append(job_entry)
            
            # Join all parts into one message
            message = "\n".join(message_parts)
        
        # Send the complete message at once
        post_to_slack(message)

        # Save seen jobs
        save_seen_jobs()
        
        # Performance metrics
        elapsed = time.time() - start_time
        print(f"⚡ Completed in {elapsed:.1f} seconds")
        print(f"✅ {len(all_new_jobs)} jobs posted to Slack")
        print(f"📊 Deep filters: {total_filter_counts['clearance_required']} clearance, {total_filter_counts['experience_required']} experience, {total_filter_counts['sponsorship_required']} sponsorship")


    
    except Exception as e:
        print(f"❌ Error in main execution: {e}")
        raise

if __name__ == "__main__":
    main()
