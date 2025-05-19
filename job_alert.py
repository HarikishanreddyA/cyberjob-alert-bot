from jobspy import scrape_jobs
import requests
import time
import os
from datetime import datetime

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SEEN_JOBS_FILE = "seen_jobs.txt"
FILTERED_LOG_FILE = "filtered_jobs.log"

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

REQUIRED_TITLE_KEYWORDS = [
    "cyber", "security", "soc", "grc", "infosec", "threat", "incident response",
    "vulnerability", "detection", "cloud security", "security analyst", "security engineer",
    "malware", "siem", "log analysis", "risk", "appsec", "devsecops"
]

REJECT_IF_TITLE_CONTAINS = [
    "senior", "manager", "lead", "director", "principal", "architect",
    "vp", "vice president", "chief", "head of", "operations manager"
]

REJECT_IF_DESCRIPTION_CONTAINS = [
    "us citizen", "u.s. citizen", "must be a us citizen", "must be a U.S. citizen", "only us citizens",
    "citizenship required", "security clearance", "ts/sci", "ts / sci", "polygraph", "top secret", "clearance required",
    "iat level ii", "t1 public trust", "public trust",
    "3+ years", "4+ years", "5+ years", "6+ years", "7+ years", "8+ years", "9+ years", "10+ years",
    "three years", "four years", "five years", "six years", "seven years", "eight years", "nine years", "ten years",
    "3 years of experience", "4 years of experience", "5 years of experience", "8 years of experience",
    "experience: 3 years", "experience: 4 years", "experience: 5 years", "experience: 8 years",
    "at least 3 years", "at least 4 years", "at least 5 years", "minimum of 3 years", "minimum of 4 years",
    "minimum of 6 years", "minimum of 7 years", "minimum of 8 years",
    "6 years of professional experience", "7 years of professional experience", "8 years of professional experience",
    "2-4 years", "2 - 4 years", "2–4 years", "2 – 4 years",
    "3-5 years", "3 - 5 years", "3–5 years", "3 – 5 years",
    "4-6 years", "4 - 6 years", "4–6 years", "4 – 6 years",
    "5-8 years", "5 - 8 years", "5–8 years", "5 – 8 years",
    "2 to 4 years", "3 to 5 years", "4 to 6 years", "5 to 8 years",
    "2-7 years", "2 – 7 years", "2 to 7 years",
    "years of experience required", "years’ experience required",
    "senior level", "senior-level", "experienced professional"
]

# Load seen jobs
if os.path.exists(SEEN_JOBS_FILE):
    with open(SEEN_JOBS_FILE, "r") as f:
        seen_jobs = set(line.strip() for line in f)
else:
    seen_jobs = set()

all_new_jobs = []
filtered_out_count = 0
filtered_log_entries = []

# 🔍 Scrape loop
for term in SEARCH_TERMS:
    for site in PLATFORMS:
        try:
            limit = 15
            jobs = scrape_jobs(
                site_name=[site],
                search_term=term,
                location="United States",
                results_wanted=limit,
                hours_old=1,
                experience_level=EXPERIENCE_LEVELS,
                country_indeed="USA",
                remote_only=False,
                verbose=0
            )

            for _, job in jobs.iterrows():
                url = job.get("job_url", "")
                if url in seen_jobs:
                    continue

                title = job.get("title", "").lower()
                description_raw = job.get("description")
                description = description_raw.lower() if isinstance(description_raw, str) else ""
                job_info = f"{job.get('title', 'No Title')} at {job.get('company', 'No Company')} ({url})"

                if not any(kw in title for kw in REQUIRED_TITLE_KEYWORDS):
                    filtered_log_entries.append(f"[TITLE-WHITELIST] ❌ {job_info}")
                    filtered_out_count += 1
                    continue

                if any(bad in title for bad in REJECT_IF_TITLE_CONTAINS):
                    filtered_log_entries.append(f"[TITLE-BLACKLIST] ❌ {job_info}")
                    filtered_out_count += 1
                    continue

                if any(bad in description for bad in REJECT_IF_DESCRIPTION_CONTAINS):
                    filtered_log_entries.append(f"[DESC-BLACKLIST] ❌ {job_info}")
                    filtered_out_count += 1
                    continue

                all_new_jobs.append(job)
                seen_jobs.add(url)

            time.sleep(2)

        except Exception as e:
            print(f"❌ Error scraping site '{site}' for term '{term}': {e}")
            continue

# 📤 Send to Slack
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

if not all_new_jobs:
    message = f"🔍 No new cybersecurity jobs found in the last hour (as of {timestamp})."
    requests.post(SLACK_WEBHOOK_URL, json={"text": message})
else:
    header = f"🔔 *New Cybersecurity Jobs (fetched at {timestamp}):*"
    requests.post(SLACK_WEBHOOK_URL, json={"text": header})
    time.sleep(1)

    for job in all_new_jobs:
        posted_date = job.get("date_posted", "Unknown")
        message = (
            f"*{job.get('title', 'No Title')}* at *{job.get('company', 'No Company')}*\n"
            f"📍 {job.get('location', 'N/A')} | 🕐 Posted: {posted_date if posted_date else 'N/A'}\n"
            f"🔗 <{job.get('job_url', '')}> via {job.get('via', 'Unknown').capitalize()}"
        )
        requests.post(SLACK_WEBHOOK_URL, json={"text": message})
        time.sleep(1)

# 💾 Save seen jobs
with open(SEEN_JOBS_FILE, "a") as f:
    for job in all_new_jobs:
        f.write(job["job_url"] + "\n")

# 📁 Save filtered job log
if filtered_log_entries:
    with open(FILTERED_LOG_FILE, "a") as log_file:
        log_file.write(f"\n🕐 Run at {timestamp} — {len(filtered_log_entries)} jobs filtered:\n")
        for entry in filtered_log_entries:
            log_file.write(entry + "\n")

# ✅ Console summary
print(f"✅ {len(all_new_jobs)} jobs posted to Slack.")
print(f"🚫 {filtered_out_count} jobs skipped due to filtering rules.")
