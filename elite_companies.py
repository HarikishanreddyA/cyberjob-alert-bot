from jobspy import scrape_jobs
import requests
import time
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict
import concurrent.futures
import itertools
from typing import List, Dict
import math

# 🔐 Set your Slack webhook URL here or use an environment variable
SLACK_WEBHOOK_URL = os.getenv("SLACK")

# Cache configuration
CACHE_FILE = "elite_jobs_cache.json"
CACHE_EXPIRY_HOURS = 24  # How long to keep jobs in cache

COMPANIES = ["Google", "Microsoft", "Amazon Web Services", "Cisco", "IBM", "Oracle", "Salesforce", "Apple",
    "Adobe", "TikTok", "Meta", "Snap Inc.", "Zoom Video Communications", "Dropbox", "Slack Technologies",
    "Built In", "Built In NYC", "Indeed", "Axios", "Nucamp", "Financial Times","Palo Alto Networks", "CrowdStrike", "Fortinet", "Check Point Software Technologies", "Trend Micro",
    "FireEye", "McAfee", "Sophos", "Darktrace", "SentinelOne", "Rapid7", "Proofpoint", "Tenable", "Imperva",
    "Varonis Systems", "CyberArk", "Okta", "Zscaler", "Qualys", "Ping Identity", "KnowBe4", "OneTrust",
    "SailPoint Technologies", "Illumio", "Lookout", "Red Canary", "Laika", "GuidePoint Security", "Fortra",
    "Druva", "Fingerprint", "Pretorian", "Deloitte", "PwC", "Ernst & Young", "KPMG", "Accenture", "Capgemini", "Booz Allen Hamilton", "CGI",
    "Leidos", "SAIC", "ManTech", "Peraton", "Cognizant", "Infosys", "Wipro", "HCL Technologies",
    "Tech Mahindra", "Tata Consultancy Services", "theservicedesk.net", "Coursera", "Business Insider", "JPMorgan Chase", "Bank of America", "Wells Fargo", "Citigroup", "Goldman Sachs", "Morgan Stanley",
    "Capital One", "American Express", "Barclays", "HSBC", "UBS", "Deutsche Bank", "BNP Paribas",
    "Credit Suisse", "TD Bank", "PNC Financial Services", "U.S. Bank", "State Street Corporation", "Lockheed Martin", "Northrop Grumman", "Raytheon Technologies", "General Dynamics", "BAE Systems",
    "Boeing", "L3Harris Technologies", "CACI International", "Kratos Defense & Security Solutions",
    "Parsons Corporation", "Amentum", "Dynetics", "Sierra Nevada Corporation", "Elbit Systems",
    "Mercury Systems", "Rheinmetall", "Leonardo DRS", "REVERB", "LinkedIn", "Reddit",
    "BMO Financial Group", "Fifth Third Bank", "UnitedHealth Group", "Anthem", "Cigna", "CVS Health", "Humana", "Kaiser Permanente",
    "Blue Cross Blue Shield", "Aetna", "Centene Corporation", "Magellan Health", "Molina Healthcare",
    "WellCare Health Plans", "Allscripts", "Cerner Corporation", "McKesson Corporation",
    "AmerisourceBergen", "Cardinal Health", "Express Scripts", "Optum", "Change Healthcare", "Walmart", "Target", "Best Buy", "Costco Wholesale", "The Home Depot", "Lowe's Companies",
    "CVS Pharmacy", "Walgreens Boots Alliance", "Kroger", "Albertsons Companies", "eBay", "Etsy",
    "Wayfair", "Shopify", "Chewy", "Zappos", "Overstock.com", "Rakuten", "Newegg", "ASOS", "Verizon Communications", "AT&T", "T-Mobile US", "Comcast", "Charter Communications",
    "Sprint Corporation", "CenturyLink", "Frontier Communications", "Windstream Holdings",
    "Cox Communications", "Altice USA", "Dish Network", "U.S. Cellular", "Shentel",
    "Mediacom Communications", "RCN Corporation", "WOW! Internet, Cable & Phone",
    "Atlantic Broadband", "Blue Ridge Communications"]


SECURITY_TERMS = ["cybersecurity", "security analyst", "security engineer", "network engineer"]
EXPERIENCE_LEVELS = ["entry level", "associate"]

# Compile rejection patterns for better performance
import re
REJECT_TITLE_PATTERN = re.compile(r'senior|sr|manager|lead|director|principal|architect|vp|chief|head|experienced|staff|distinguished', re.I)
REQUIRED_TITLE_PATTERN = re.compile(r'security|soc|cyber|infosec|incident|threat|siem|malware|detection|grc|cloud security|identity|risk|forensics|devsecops|appsec|vulnerability', re.I)
REJECT_DESCRIPTION_PATTERN = re.compile(r'us citizen|u\.s\. citizen|must be a us citizen|only us citizens|citizenship required|security clearance|ts/sci|ts / sci|polygraph|top secret|clearance required|iat level ii|public trust', re.I)

def load_cache() -> Dict:
    """Load the job cache from file"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {"jobs": {}, "last_updated": datetime.now().isoformat()}
    return {"jobs": {}, "last_updated": datetime.now().isoformat()}

def save_cache(cache: Dict):
    """Save the job cache to file"""
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def is_job_seen(job_url: str, cache: Dict) -> bool:
    """Check if job has been seen recently"""
    return job_url in cache["jobs"]

def filter_job(job, company: str, cache: Dict) -> tuple[bool, str]:
    """Filter a single job with all criteria"""
    title = job.get("title", "").lower()
    job_company = job.get("company", "").lower()
    job_via = (job.get("via") or "").lower()
    description = job.get("description", "").lower()
    job_url = job.get("job_url", "")

    if is_job_seen(job_url, cache):
        return False, "cached"

    if company.lower() not in job_company:
        return False, "company_mismatch"

    if "dice" in job_via or "lensa" in job_via:
        return False, "bad_source"

    if REJECT_TITLE_PATTERN.search(title):
        return False, "title_reject"

    if not REQUIRED_TITLE_PATTERN.search(title):
        return False, "title_missing_keywords"

    if REJECT_DESCRIPTION_PATTERN.search(description):
        return False, "description_reject"

    return True, "passed"

def process_company_batch(company_batch: List[str], search_term: str, cache: Dict) -> List[Dict]:
    """Process a batch of companies in parallel"""
    filtered_jobs = []
    stats = defaultdict(int)
    
    def process_single_company(company):
        try:
            jobs = scrape_jobs(
                site_name=["linkedin"],
                search_term=f"{search_term} {company}",
                location="United States",
                results_wanted=10,  # Reduced from 15 to improve speed
                hours_old=1,
                experience_level=EXPERIENCE_LEVELS,
                remote_only=False,
                easy_apply=False,
                linkedin_fetch_description=True,
                verbose=0
            )

            company_jobs = []
            for _, job in jobs.iterrows():
                passed, reason = filter_job(job, company, cache)
                stats[reason] += 1
                if passed:
                    job_dict = job.to_dict()
                    job_dict['company_searched'] = company
                    company_jobs.append(job_dict)
                    cache["jobs"][job.get("job_url")] = {
                        "first_seen": datetime.now().isoformat(),
                        "title": job.get("title")
                    }

            return company_jobs
        except Exception as e:
            print(f"❌ Error processing {company}: {e}")
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_company = {executor.submit(process_single_company, company): company 
                           for company in company_batch}
        
        for future in concurrent.futures.as_completed(future_to_company):
            company = future_to_company[future]
            try:
                company_jobs = future.result()
                filtered_jobs.extend(company_jobs)
            except Exception as e:
                print(f"❌ Error processing {company}: {e}")

    return filtered_jobs, dict(stats)

def post_to_slack(messages: List[str], max_retries=3):
    """Post messages to Slack in batches"""
    if not messages:
        return

    batch_size = 20
    for i in range(0, len(messages), batch_size):
        batch = messages[i:i + batch_size]
        combined_message = "\n".join(batch)
        
        for attempt in range(max_retries):
            try:
                response = requests.post(SLACK_WEBHOOK_URL, json={"text": combined_message})
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    print(f"❌ Failed to send batch to Slack: {e}")
                time.sleep(1 * (attempt + 1))
        
        time.sleep(1)  # Rate limiting between batches

def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n🔍 STARTING LINKEDIN SECURITY JOB SCAN as of {timestamp}\n")

    # Load and clean cache
    cache = load_cache()
    cache_expiry = datetime.now() - timedelta(hours=CACHE_EXPIRY_HOURS)
    cache["jobs"] = {url: data for url, data in cache["jobs"].items()
                    if datetime.fromisoformat(data["first_seen"]) > cache_expiry}

    all_jobs = []
    total_stats = defaultdict(int)

    # Process companies in batches
    batch_size = 10
    for term in SECURITY_TERMS:
        for i in range(0, len(COMPANIES), batch_size):
            company_batch = COMPANIES[i:i + batch_size]
            print(f"⏳ Processing batch of {len(company_batch)} companies for term: {term}")
            
            jobs, stats = process_company_batch(company_batch, term, cache)
            all_jobs.extend(jobs)
            
            for key, value in stats.items():
                total_stats[key] += value

            # Save cache after each batch
            save_cache(cache)

    # Prepare Slack messages
    messages = []
    
    if not all_jobs:
        messages.append(f"🔍 No elite jobs found (as of {timestamp}).")
    else:
        messages.append(f"📢 *New Elite Cybersecurity Jobs (as of {timestamp}):*")
        messages.append(
            f"📊 *Job Statistics:*\n"
            f"• Total jobs processed: {sum(total_stats.values())}\n"
            f"• Jobs posted: {len(all_jobs)}\n"
            f"• Jobs filtered out:\n"
            f"  - Already seen: {total_stats['cached']}\n"
            f"  - Company mismatch: {total_stats['company_mismatch']}\n"
            f"  - Bad source: {total_stats['bad_source']}\n"
            f"  - Title rejection: {total_stats['title_reject']}\n"
            f"  - Missing keywords: {total_stats['title_missing_keywords']}\n"
            f"  - Clearance required: {total_stats['description_reject']}\n"
            f"-------------------"
        )

        # Group jobs by company for better readability
        grouped_jobs = defaultdict(list)
        for job in all_jobs:
            grouped_jobs[job['company_searched']].append(job)

        for company, jobs in grouped_jobs.items():
            messages.append(f"\n🏢 *{company}*")
            for idx, job in enumerate(jobs, start=1):
                title = job.get("title", "No Title")
                location = job.get("location", "N/A")
                level = job.get("experience_level", "N/A").title()
                posted = job.get("date_posted", "N/A")
                url = job.get("job_url", "")
                min_amt = job.get("min_amount")
                max_amt = job.get("max_amount")
                interval = job.get("interval", "yearly")
                salary = f"${int(min_amt):,} – ${int(max_amt):,} / {interval}" if min_amt and max_amt else "Not listed"

                messages.append(
                    f"{idx}️⃣ *{title}*\n"
                    f"📍 Location: {location}\n"
                    f"🧠 Level: {level}\n"
                    f"💰 Salary: {salary}\n"
                    f"🕐 Posted: {posted}\n"
                    f"🔗 <{url}>"
                )

        messages.append(f"\n✅ *Total jobs listed: {len(all_jobs)}*")

    # Send messages to Slack
    post_to_slack(messages)

    print(f"✅ Scan complete! Found {len(all_jobs)} jobs.")
    print(f"📊 Stats: {dict(total_stats)}")

if __name__ == "__main__":
    main()
