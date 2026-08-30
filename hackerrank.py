import os
import re
import sys
import time
import random
import requests
from curl_cffi import requests as cf_requests

HACKERRANK_COOKIE = os.getenv("HACKERRANK_COOKIE")
HACKERRANK_CSRF = os.getenv("HACKERRANK_CSRF")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not all([HACKERRANK_COOKIE, HACKERRANK_CSRF, GEMINI_API_KEY]):
    print("Error: Missing required environment variables.")
    sys.exit(1)

def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

headers = {
    "x-csrf-token": HACKERRANK_CSRF,
    "Cookie": HACKERRANK_COOKIE,
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 1. Discover a Random Unsolved Problem
print("Fetching unsolved HackerRank problems...")
discovery_url = "https://www.hackerrank.com/rest/contests/master/tracks/algorithms/challenges?offset=0&limit=50&filters%5Bstatus%5D%5B%5D=unsolved"
res = cf_requests.get(discovery_url, headers=headers, impersonate="chrome")

# Safeguard 1: Catch expired sessions immediately
if res.status_code == 401:
    print("Session expired (401).")
    send_telegram("⚠️ *HackerRank Session Expired*\nYour cookie died. Please update `HACKERRANK_COOKIE` in GitHub Secrets.")
    sys.exit(1)
elif res.status_code != 200:
    err = f"Failed to fetch problems: {res.status_code} - {res.text}"
    print(err)
    send_telegram(f"❌ *HackerRank Bot Failed*\n`{err}`")
    sys.exit(1)

models = res.json().get("models", [])
if not models:
    print("No unsolved problems found in this batch!")
    sys.exit(0)

problem = random.choice(models)
slug = problem.get("slug")
title = problem.get("name")
safe_title = re.sub(r'[*_`\[\]]', '', title)

print(f"Problem Found: {title} ({slug})")

# 2. Fetch Problem Description
detail_url = f"https://www.hackerrank.com/rest/contests/master/challenges/{slug}"
detail_res = cf_requests.get(detail_url, headers=headers, impersonate="chrome")
body_html = detail_res.json().get("model", {}).get("body_html", "")

# 3. Generate Solution via Gemini (With I/O Validator)
print("Generating solution via Gemini...")
prompt = f"""
You are an expert competitive programmer. Solve this HackerRank problem in Python 3.
CRITICAL INSTRUCTIONS:
1. Do NOT use HackerRank's os.environ['OUTPUT_PATH'] stub.
2. Read all input directly from standard input using sys.stdin.read().
3. Print all output directly to standard output.
4. Do NOT use interactive input strings like input("Enter a number: ").
5. Output ONLY the raw Python code, no markdown backticks, no explanations.

Problem Statement (HTML):
{body_html}
"""

gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
ai_payload = {"contents": [{"parts": [{"text": prompt}]}]}
clean_code = ""

for attempt in range(3):
    ai_res = requests.post(gemini_url, json=ai_payload)
    if ai_res.status_code == 200:
        try:
            raw_code = ai_res.json()["candidates"][0]["content"]["parts"][0]["text"]
            match = re.search(r"```(?:python|python3)?\n(.*?)```", raw_code, re.DOTALL | re.IGNORECASE)
            clean_code = match.group(1).strip() if match else raw_code.strip()
            
            # Safeguard 2: Catch AI hallucinations before submission
            if "OUTPUT_PATH" in clean_code or "os.environ" in clean_code:
                print(f"Attempt {attempt + 1}: AI hallucinated OUTPUT_PATH. Forcing retry...")
                ai_payload["contents"][0]["parts"][0]["text"] += "\n\nCRITICAL: YOU FAILED TO FOLLOW INSTRUCTIONS. DO NOT USE OUTPUT_PATH OR OS.ENVIRON. REWRITE USING SYS.STDIN AND PRINT()."
                continue
            
            break 
        except Exception as e:
            print(f"Extraction error on attempt {attempt + 1}: {e}")
            continue
            
    elif ai_res.status_code == 503:
        print("Gemini overloaded. Retrying in 10s...")
        time.sleep(10)
    else:
        err = f"Gemini API Error {ai_res.status_code}"
        print(err)
        send_telegram(f"❌ *HackerRank Bot Failed*\n`{err}`")
        sys.exit(1)
else:
    send_telegram("❌ *HackerRank Bot Failed*\nGemini API timed out or repeatedly failed I/O validation.")
    sys.exit(1)

# 4. Submit to HackerRank
print("Submitting solution...")
submit_url = f"https://www.hackerrank.com/rest/contests/master/challenges/{slug}/submissions"
payload = {"code": clean_code, "language": "python3", "contest_slug": "master"}

sub_res = cf_requests.post(submit_url, json=payload, headers=headers, impersonate="chrome")
if sub_res.status_code != 200:
    send_telegram(f"❌ *HackerRank Submission Failed*\nHTTP status: `{sub_res.status_code}`")
    sys.exit(1)

submission_id = sub_res.json().get("model", {}).get("id")

# 5. Poll for Verdict
print(f"Submission ID: {submission_id}. Polling for verdict...")
poll_url = f"https://www.hackerrank.com/rest/contests/master/challenges/{slug}/submissions/{submission_id}"

# Safeguard 3: Explicitly ignore non-terminal polling states
non_terminal_states = ["Working", "Queued", "Compiling", "In Progress", "Pending"]

for attempt in range(20):
    time.sleep(3)
    poll_res = cf_requests.get(poll_url, headers=headers, impersonate="chrome").json()
    status = poll_res.get("model", {}).get("status")
    
    if status not in non_terminal_states:
        if status == "Accepted":
            send_telegram(
                f"✅ *HackerRank Solved!*\n\n"
                f"📌 *Problem:* {safe_title}\n"
                f"🔗 [View Problem](https://www.hackerrank.com/challenges/{slug}/)"
            )
        else:
            send_telegram(f"❌ *HackerRank Not Accepted*\nProblem: {safe_title}\nVerdict: `{status}`")
            sys.exit(1)
        break
    else:
        print(f"Polling... State: {status}")
else:
    send_telegram("❌ *HackerRank Bot Timed Out*\nSubmission took over 60 seconds.")
    sys.exit(1)

# 6. Save locally for Git Sync
folder_name = f"HackerRank-{slug}"
os.makedirs(folder_name, exist_ok=True)
with open(f"{folder_name}/{slug}.py", "w", encoding="utf-8") as f:
    f.write(clean_code)

print("Success! HackerRank code saved locally.")
