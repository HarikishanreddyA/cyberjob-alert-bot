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

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SEEN_JOBS_FILE = "seen_jobs.json"
MAX_JOBS_TO_KEEP = 1000  # Keep last 1000 jobs to prevent file from growing too large

# Search configuration
SEARCH_TERMS = [
    "cybersecurity",
    "security engineer",
    "SOC analyst",
    "information security",
    "GRC analyst",
    "cloud security",
    "junior security analyst",
    "infosec"
]

EXPERIENCE_LEVELS = ["entry level", "internship", "associate", "mid-senior level"]
PLATFORMS = ["linkedin"]

# Compile regex patterns for faster matching
TITLE_KEYWORDS = re.compile(r'cyber|security|soc|grc|infosec|threat|incident response|vulnerability|detection|cloud security|security analyst|security engineer|malware|siem|log analysis|risk|appsec|devsecops', re.I)
REJECT_TITLE = re.compile(r'senior|manager|lead|director|principal|architect|vp|vice president|chief|head of|operations manager', re.I)
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
    """Filter a single job with all criteria"""
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

    # Check title requirements
    if not check_title_match(title):
        return None, "title_keywords"

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
    for attempt in range(max_retries):
        try:
            response = requests.post(SLACK_WEBHOOK_URL, json={"text": message})
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException:
            if attempt == max_retries - 1:
                print(f"❌ Failed to send message to Slack after {max_retries} attempts")
                return False
            time.sleep(1 * (attempt + 1))  # Exponential backoff

def main():
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
            message = f"🔍 No new cybersecurity jobs found in the last hour (as of {timestamp})."
            post_to_slack(message)
        else:
            header = (
                f"🔔 *New Cybersecurity Jobs (fetched at {timestamp}):*\n"
                f"📊 *Job Statistics:*\n"
                f"• Total jobs processed: {sum(total_filter_counts.values())}\n"
                f"• Jobs posted: {len(all_new_jobs)}\n"
                f"• Jobs filtered out:\n"
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
                    f"*{job.get('title', 'No Title')}* at *{job.get('company', 'No Company')}*\n"
                    f"📍 {job.get('location', 'N/A')} | 🕐 Posted: {posted_date if posted_date else 'N/A'}\n"
                    f"🔗 <{job.get('job_url', '')}> via {job.get('via', 'Unknown').capitalize()}"
                )
                post_to_slack(message)
                time.sleep(1)

        # Print console summary
        print(f"✅ {len(all_new_jobs)} jobs posted to Slack.")
        print(f"🚫 {sum(total_filter_counts.values()) - len(all_new_jobs)} jobs filtered out.")

        # Save all seen jobs at the end
        save_seen_jobs()

        # If we're running in GitHub Actions, commit the changes
        if os.getenv("GITHUB_ACTIONS") == "true":
            try:
                # Add git configuration
                os.system('git config --global user.name "CyberJobBot"')
                os.system('git config --global user.email "github-actions@github.com"')
                
                # Stage and commit changes
                os.system('git add seen_jobs.json')
                os.system('git commit -m "Update seen jobs list [skip ci]"')
                
                # Push using the GITHUB_TOKEN
                repo_url = f"https://x-access-token:{os.getenv('GITHUB_TOKEN')}@github.com/{os.getenv('GITHUB_REPOSITORY')}.git"
                os.system(f'git remote set-url origin "{repo_url}"')
                os.system('git push')
            except Exception as e:
                print(f"❌ Error updating GitHub: {e}")
                # Continue execution even if GitHub update fails
    
    except Exception as e:
        print(f"❌ Error in main execution: {e}")
        raise

if __name__ == "__main__":
    main()
