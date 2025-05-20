from jobspy import scrape_jobs
import requests
import time
import os
from datetime import datetime
from collections import defaultdict

# 🔐 Set your Slack webhook URL here or use an environment variable
SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"

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

SECURITY_TERMS = ["cybersecurity", "security analyst", "security engineer"]
EXPERIENCE_LEVELS = ["entry level", "internship", "associate"]
REJECT_IF_TITLE_CONTAINS = [
    "senior", "sr", "manager", "lead", "director", "principal", "architect",
    "vp", "chief", "head", "experienced", "staff", "distinguished"
]

grouped_jobs = defaultdict(list)
total_jobs = 0

print(f"\n🔍 STARTING ELITE JOB SCAN via LinkedIn...\n")

for company in COMPANIES:
    for term in SECURITY_TERMS:
        try:
            print(f"⏳ Searching: '{term}' at '{company}'")

            jobs = scrape_jobs(
                site_name=["linkedin"],
                search_term=f"{term} {company}",
                location="United States",
                results_wanted=5,
                hours_old=1,
                experience_level=EXPERIENCE_LEVELS,
                remote_only=False,
                verbose=0
            )

            for _, job in jobs.iterrows():
                title = job.get("title", "").lower()
                job_company = job.get("company", "").lower()
                job_via = (job.get("via") or "").lower()

                if company.lower() not in job_company:
                    continue
                if "dice" in job_via:
                    continue
                if any(term in title for term in REJECT_IF_TITLE_CONTAINS):
                    continue

                grouped_jobs[company].append(job)
                total_jobs += 1

            time.sleep(1)

        except Exception as e:
            print(f"❌ Error: {company} — {e}")

# ✅ Post to Slack
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

if total_jobs == 0:
    requests.post(SLACK_WEBHOOK_URL, json={"text": f"🔍 No elite jobs found (as of {timestamp})."})
else:
    requests.post(SLACK_WEBHOOK_URL, json={"text": f"📢 *New Elite Cybersecurity Jobs (as of {timestamp}):*"})
    time.sleep(1)

    for company, jobs in grouped_jobs.items():
        requests.post(SLACK_WEBHOOK_URL, json={"text": f"\n🏢 *{company}*"})
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

            message = (
                f"{idx}️⃣ *{title}*\n"
                f"📍 Location: {location}\n"
                f"🧠 Level: {level}\n"
                f"💰 Salary: {salary}\n"
                f"🕐 Posted: {posted}\n"
                f"🔗 <{url}>"
            )

            requests.post(SLACK_WEBHOOK_URL, json={"text": message})
            time.sleep(1)

    requests.post(SLACK_WEBHOOK_URL, json={"text": f"📊 *Total: {total_jobs} elite jobs listed.*"})
