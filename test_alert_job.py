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

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"
SEEN_JOBS_FILE = "test_seen_jobs.json"
FILTERED_JOBS_FILE = "test_filtered_jobs.json"
MAX_JOBS_TO_KEEP = 500  # Reduced for testing

# Test configuration with fewer search terms and stricter filters
SEARCH_TERMS = [
    "junior security analyst",
    "entry level cybersecurity",
    "information security analyst"
]

EXPERIENCE_LEVELS = ["entry level", "internship", "associate"]
PLATFORMS = ["linkedin"]  # Start with just LinkedIn for testing

# Stricter regex patterns
TITLE_KEYWORDS = re.compile(r'security analyst|cyber security|information security|soc analyst|security operations|junior security', re.I)
REJECT_TITLE = re.compile(r'senior|sr\.|lead|manager|director|principal|architect|head|chief|vp|vice president|staff|expert|consultant', re.I)
SOURCE_REJECT = re.compile(r'dice|lensa|jobs via dice|jobs via lensa|via dice|via lensa', re.I)
EASY_APPLY = re.compile(r'easy apply|quick apply|1-click apply|1 click apply|apply now|apply with your profile|apply with linkedin', re.I)
EXPERIENCE_PATTERN = re.compile(r'(\d+)[\+]?\s*(?:to|\-|\–)\s*(\d+)\s+years?|(\d+)[\+]?\s+years?|(\d+)[\+]?\s+years?\s+experience', re.I)

# Cache seen jobs in memory
SEEN_JOBS = set()
FILTERED_JOBS = []

def extract_experience_years(text):
    """Extract years of experience from text"""
    matches = EXPERIENCE_PATTERN.finditer(text)
    min_years = float('inf')
    
    for match in matches:
        if match.group(1) and match.group(2):  # Range format: "2-4 years"
            min_years = min(min_years, int(match.group(1)))
        elif match.group(3):  # Single number format: "3 years"
            min_years = min(min_years, int(match.group(3)))
        elif match.group(4):  # Plus format: "3+ years"
            min_years = min(min_years, int(match.group(4)))
    
    return min_years if min_years != float('inf') else None

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
    jobs_list = list(SEEN_JOBS)[-MAX_JOBS_TO_KEEP:]
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump({
            "seen_jobs": jobs_list,
            "last_updated": datetime.now().isoformat()
        }, f, indent=2)

def save_filtered_jobs():
    """Save filtered jobs with reasons to JSON file"""
    with open(FILTERED_JOBS_FILE, "w") as f:
        json.dump({
            "filtered_jobs": FILTERED_JOBS[-MAX_JOBS_TO_KEEP:],
            "last_updated": datetime.now().isoformat()
        }, f, indent=2)

def save_seen_job(url):
    """Add single job to tracking set"""
    SEEN_JOBS.add(url)

def add_filtered_job(job, reason, details=""):
    """Add job to filtered list with reason"""
    FILTERED_JOBS.append({
        "title": job.get("title"),
        "company": job.get("company"),
        "url": job.get("job_url"),
        "filter_reason": reason,
        "filter_details": details,
        "date_filtered": datetime.now().isoformat()
    })

def filter_job(job):
    """Filter a single job with stricter criteria"""
    url = str(job.get("job_url", ""))
    
    # Skip if already seen
    if url in SEEN_JOBS:
        add_filtered_job(job, "seen")
        return None, "seen"

    title = str(job.get("title", "")).lower()
    description = str(job.get("description", "")).lower() if job.get("description") else ""
    source = str(job.get("via", "")).lower()
    apply_text = str(job.get("apply_text", "")).lower()
    company = str(job.get("company", "")).lower()

    # Check source first
    if SOURCE_REJECT.search(source):
        add_filtered_job(job, "source", f"Rejected source: {source}")
        return None, "source"

    # Check title requirements
    if not check_title_match(title):
        add_filtered_job(job, "title_keywords", f"Title doesn't match required keywords: {title}")
        return None, "title_keywords"

    if REJECT_TITLE.search(title):
        add_filtered_job(job, "title_reject", f"Title contains rejected terms: {title}")
        return None, "title_reject"

    # Check experience requirements in description
    years = extract_experience_years(description)
    if years and years > 3:
        add_filtered_job(job, "experience", f"Required {years} years of experience")
        return None, "experience"

    # Check for easy apply
    full_text = f"{title} {description} {apply_text}"
    if EASY_APPLY.search(full_text):
        add_filtered_job(job, "easy_apply", "Easy Apply job posting")
        return None, "easy_apply"

    # Return job with all details for better tracking
    return {
        "title": job.get("title"),
        "company": company,
        "location": job.get("location"),
        "job_url": url,
        "date_posted": job.get("date_posted"),
        "via": job.get("via"),
        "description": description  # Including description in output
    }, "passed"

def process_jobs_batch(jobs_batch):
    """Process a batch of jobs in parallel"""
    filtered_jobs = []
    filter_counts = {
        "seen": 0, 
        "source": 0, 
        "title_keywords": 0, 
        "title_reject": 0, 
        "experience": 0,
        "easy_apply": 0, 
        "passed": 0
    }
    
    if jobs_batch.empty:
        return filtered_jobs, filter_counts

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_job = {executor.submit(filter_job, job._asdict()): job for job in jobs_batch.itertuples()}
        for future in concurrent.futures.as_completed(future_to_job):
            job, reason = future.result()
            filter_counts[reason] += 1
            if job:
                filtered_jobs.append(job)
                SEEN_JOBS.add(job["job_url"])
                save_seen_job(job["job_url"])
    
    return filtered_jobs, filter_counts

def post_to_slack(message):
    """Post to Slack with retry mechanism"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(SLACK_WEBHOOK_URL, json={"text": message})
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"❌ Slack error (attempt {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                return False
            time.sleep(1 * (attempt + 1))

def main():
    print("🔄 Starting test job alert script...")
    load_seen_jobs()
    all_new_jobs = []
    total_filter_counts = {
        "seen": 0, 
        "source": 0, 
        "title_keywords": 0, 
        "title_reject": 0, 
        "experience": 0,
        "easy_apply": 0, 
        "passed": 0
    }

    try:
        for term in SEARCH_TERMS:
            print(f"🔍 Searching for: {term}")
            try:
                jobs = scrape_jobs(
                    site_name=PLATFORMS,
                    search_term=term,
                    location="United States",
                    results_wanted=10,  # Reduced for testing
                    hours_old=24,  # Increased time range for testing
                    experience_level=EXPERIENCE_LEVELS,
                    country_indeed="USA",
                    remote_only=False,
                    verbose=0
                )
                
                if not jobs.empty:
                    filtered, counts = process_jobs_batch(jobs)
                    all_new_jobs.extend(filtered)
                    for key in total_filter_counts:
                        total_filter_counts[key] += counts[key]
                    print(f"✅ Found {len(filtered)} matching jobs for '{term}'")
                else:
                    print(f"ℹ️ No jobs found for '{term}'")
                    
            except Exception as e:
                print(f"❌ Error searching '{term}': {e}")
                continue

        # Save jobs data
        save_seen_jobs()
        save_filtered_jobs()

        # Send results to Slack
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        if not all_new_jobs:
            message = f"🔍 No new matching jobs found in test run (as of {timestamp})."
            post_to_slack(message)
        else:
            header = (
                f"🧪 *Test Run Results ({timestamp})*\n"
                f"📊 *Statistics:*\n"
                f"• Total jobs processed: {sum(total_filter_counts.values())}\n"
                f"• Jobs passed filters: {len(all_new_jobs)}\n"
                f"• Jobs filtered out:\n"
                f"  - Already seen: {total_filter_counts['seen']}\n"
                f"  - Source (Dice/Lensa): {total_filter_counts['source']}\n"
                f"  - Title mismatch: {total_filter_counts['title_keywords']}\n"
                f"  - Senior/Manager: {total_filter_counts['title_reject']}\n"
                f"  - Experience > 3 years: {total_filter_counts['experience']}\n"
                f"  - Easy Apply: {total_filter_counts['easy_apply']}\n"
                f"-------------------"
            )
            post_to_slack(header)
            time.sleep(1)

            for job in all_new_jobs:
                message = (
                    f"*{job['title']}* at *{job['company']}*\n"
                    f"📍 {job['location']} | 🕐 Posted: {job['date_posted'] if job['date_posted'] else 'N/A'}\n"
                    f"🔗 <{job['job_url']}> via {job['via'].capitalize()}\n"
                    f"📝 Description Preview: {job['description'][:200]}..." if job['description'] else ""
                )
                post_to_slack(message)
                time.sleep(1)

        print(f"\n✅ Test Results:")
        print(f"• {len(all_new_jobs)} jobs posted to Slack")
        print(f"• {sum(total_filter_counts.values()) - len(all_new_jobs)} jobs filtered out")
        print("\n📊 Filter Breakdown:")
        for reason, count in total_filter_counts.items():
            if count > 0:
                print(f"• {reason}: {count}")
        
    except Exception as e:
        print(f"❌ Error in main execution: {e}")
        raise

if __name__ == "__main__":
    main() 
