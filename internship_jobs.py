# -*- coding: utf-8 -*-
from jobspy import scrape_jobs
import requests
import time
import os
import json
from datetime import datetime
import concurrent.futures
from functools import lru_cache
import re

SLACK_INTERN_URL = os.getenv("SLACK_INTERN")  # Matches env var name
SEEN_JOBS_FILE = "seen_internship_jobs.json"  # Separate file for internships
MAX_JOBS_TO_KEEP = 1000  # Keep last 1000 jobs to prevent file from growing too large

# Internship and Co-op specific search configuration
SEARCH_TERMS = [
    "cybersecurity intern",
    "security intern", 
    "SOC intern",
    "information security intern",
    "GRC intern",
    "cloud security intern",
    "security analyst intern",
    "infosec intern",
    "cybersecurity internship",
    "security internship",
    "SOC internship",
    "information security internship",
    "cyber intern",
    "security engineering intern",
    "cybersecurity coop",
    "security coop",
    "cybersecurity co-op",
    "security co-op",
    "SOC coop",
    "SOC co-op",
    "information security coop",
    "information security co-op",
    "cyber coop",
    "cyber co-op"
]

EXPERIENCE_LEVELS = ["internship"]  # JobSpy doesn't have separate "coop" level
PLATFORMS = ["linkedin"]

# Compile regex patterns for faster matching - internship and co-op optimized
TITLE_KEYWORDS = re.compile(r'intern|internship|coop|co-op|cyber|security|soc|grc|infosec|threat|incident response|vulnerability|detection|cloud security|security analyst|security engineer|malware|siem|log analysis|risk|appsec|devsecops', re.I)
# More lenient for internships - don't reject senior titles as harshly since some are "Senior Intern" positions
REJECT_TITLE = re.compile(r'manager|lead|director|principal|architect|vp|vice president|chief|head of', re.I)
SOURCE_REJECT = re.compile(r'dice|lensa|jobs via dice|jobs via lensa|via dice|via lensa', re.I)
EASY_APPLY = re.compile(r'easy apply|quick apply|1-click apply|1 click apply|apply now|apply with your profile|apply with linkedin', re.I)

# Cache seen jobs in memory
SEEN_JOBS = set()

@lru_cache(maxsize=1000)
def check_title_match(title):
    """Cache and check title matches for better performance"""
    return bool(TITLE_KEYWORDS.search(title))

def load_seen_jobs():
    """Load seen jobs from JSON file into memory"""
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
    """Save seen jobs to JSON file"""
    # Convert set to list and keep only the most recent jobs
    jobs_list = list(SEEN_JOBS)[-MAX_JOBS_TO_KEEP:]
    
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump({"seen_jobs": jobs_list, "last_updated": datetime.now().isoformat()}, f, indent=2)

def save_seen_job(url):
    """Add single job to tracking set"""
    SEEN_JOBS.add(url)

def filter_job(job):
    """Filter a single job with internship-specific criteria"""
    url = str(job.get("job_url", ""))
    
    # Skip if already seen
    if url in SEEN_JOBS:
        return None, "seen"

    title = str(job.get("title", "")).lower()
    description = str(job.get("description", "")).lower() if job.get("description") else ""
    source = str(job.get("via", "")).lower()
    apply_text = str(job.get("apply_text", "")).lower()
    company = str(job.get("company", "")).lower()

    # Check source and description for Lensa/Dice mentions
    if SOURCE_REJECT.search(source) or SOURCE_REJECT.search(description) or SOURCE_REJECT.search(company):
        return None, "source"

    # For internships and co-ops, we want to be more inclusive with keywords
    # Check if it's explicitly an internship/co-op AND has security keywords
    is_internship_or_coop = bool(re.search(r'intern|internship|coop|co-op', title, re.I))
    has_security_keywords = check_title_match(title)
    
    if not (is_internship_or_coop and has_security_keywords):
        return None, "title_keywords"

    # More lenient title rejection for internships
    if REJECT_TITLE.search(title):
        return None, "title_reject"

    # Check for easy apply
    full_text = f"{title} {description} {apply_text}"
    if EASY_APPLY.search(full_text):
        return None, "easy_apply"

    # If passed all filters, return the job
    return job, "passed"

def process_jobs_batch(jobs_batch):
    """Process a batch of jobs in parallel"""
    filtered_jobs = []
    filter_counts = {"seen": 0, "source": 0, "title_keywords": 0, "title_reject": 0, "easy_apply": 0, "passed": 0}
    
    if jobs_batch.empty:
        return filtered_jobs, filter_counts

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_job = {executor.submit(filter_job, job._asdict()): job for job in jobs_batch.itertuples()}
        for future in concurrent.futures.as_completed(future_to_job):
            job, reason = future.result()
            filter_counts[reason] += 1
            if job:
                filtered_jobs.append(job)
                SEEN_JOBS.add(job["job_url"])
                save_seen_job(job["job_url"])
    
    return filtered_jobs, filter_counts

def post_to_slack(message, max_retries=3):
    """Post to Slack with retry mechanism"""
    if not SLACK_INTERN_URL:
        print("❌ SLACK_INTERN environment variable not set")
        return False
    
    for attempt in range(max_retries):
        try:
            response = requests.post(SLACK_INTERN_URL, json={"text": message})
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"❌ Slack API error (attempt {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                print(f"❌ Failed to send message to Slack after {max_retries} attempts")
                return False
            time.sleep(1 * (attempt + 1))  # Exponential backoff

def main():
    # Debug: Check if Slack webhook is configured
    if SLACK_INTERN_URL:
        print(f"✅ Slack webhook configured (ends with: ...{SLACK_INTERN_URL[-10:]})")
    else:
        print("❌ SLACK_INTERN environment variable not found!")
        return
    
    load_seen_jobs()
    all_new_jobs = []
    total_filter_counts = {"seen": 0, "source": 0, "title_keywords": 0, "title_reject": 0, "easy_apply": 0, "passed": 0}

    try:
        # Scrape jobs in parallel for each search term
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_term = {
                executor.submit(
                    scrape_jobs,
                    site_name=PLATFORMS,
                    search_term=term,
                    location="United States",
                    results_wanted=15,
                    hours_old=1,
                    experience_level=EXPERIENCE_LEVELS,
                    country_indeed="USA",
                    remote_only=False,
                    verbose=0
                ): term for term in SEARCH_TERMS
            }

            for future in concurrent.futures.as_completed(future_to_term):
                try:
                    jobs = future.result()
                    if not jobs.empty:
                        filtered, counts = process_jobs_batch(jobs)
                        all_new_jobs.extend(filtered)
                        for key in total_filter_counts:
                            total_filter_counts[key] += counts[key]
                except Exception as e:
                    print(f"❌ Error scraping jobs: {e}")

        # Send results to Slack
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        if not all_new_jobs:
            message = f"🔍 No new cybersecurity internships/co-ops found in the last hour (as of {timestamp})."
            post_to_slack(message)
        else:
            header = (
                f"🎓 *New Cybersecurity Internships & Co-ops (fetched at {timestamp}):*\n"
                f"📊 *Job Statistics:*\n"
                f"• Total positions processed: {sum(total_filter_counts.values())}\n"
                f"• Positions posted: {len(all_new_jobs)}\n"
                f"• Positions filtered out:\n"
                f"  - Already seen: {total_filter_counts['seen']}\n"
                f"  - Source (Dice/Lensa): {total_filter_counts['source']}\n"
                f"  - Title mismatch: {total_filter_counts['title_keywords']}\n"
                f"  - Senior/Manager: {total_filter_counts['title_reject']}\n"
                f"  - Easy Apply: {total_filter_counts['easy_apply']}\n"
                f"-------------------"
            )
            post_to_slack(header)
            time.sleep(1)

            for job in all_new_jobs:
                posted_date = job.get("date_posted", "Unknown")
                message = (
                    f"🎓 *{job.get('title', 'No Title')}* at *{job.get('company', 'No Company')}*\n"
                    f"📍 {job.get('location', 'N/A')} | 🕐 Posted: {posted_date if posted_date else 'N/A'}\n"
                    f"🔗 <{job.get('job_url', '')}> via {job.get('via', 'Unknown').capitalize()}"
                )
                post_to_slack(message)
                time.sleep(1)

        # Print console summary
        print(f"✅ {len(all_new_jobs)} internships/co-ops posted to Slack.")
        print(f"🚫 {sum(total_filter_counts.values()) - len(all_new_jobs)} positions filtered out.")

        # Save all seen jobs at the end
        save_seen_jobs()
    
    except Exception as e:
        print(f"❌ Error in main execution: {e}")
        raise

if __name__ == "__main__":
    main() 

