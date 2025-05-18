from jobspy import scrape_jobs
import requests
import time

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"

# Step 1: Scrape jobs
try:
    jobs = scrape_jobs(
        site_name=["linkedin", "indeed"],
        search_term="cybersecurity",
        location="United States",
        results_wanted=10,
        date_posted="week",
        experience_level=["entry level", "internship"]
    )
except Exception as e:
    print(f"❌ Error while scraping: {e}")
    exit()

# Step 2: Send to Slack
for _, job in jobs.iterrows():
    title = job.get("title", "No title")
    company = job.get("company", "No company")
    location = job.get("location", "N/A")
    posted = job.get("date_posted", "N/A")
    url = job.get("job_url", "")
    source = job.get("via", "Unknown").capitalize()

    message = (
        f"*{title}* at *{company}*\n"
        f"📍 {location} | 🕐 Posted: {posted}\n"
        f"🔗 <{url}> via {source}"
    )

    response = requests.post(SLACK_WEBHOOK_URL, json={"text": message})
    if response.status_code != 200:
        print(f"⚠️ Slack error: {response.text}")

    # Optional: Delay between messages
    time.sleep(1)
