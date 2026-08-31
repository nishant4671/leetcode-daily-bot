import os
import re
import sys
import time
import requests
from curl_cffi import requests as cf_requests

LEETCODE_SESSION = os.getenv("LEETCODE_SESSION")
CSRF_TOKEN = os.getenv("LEETCODE_CSRF_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not all([LEETCODE_SESSION, CSRF_TOKEN, GEMINI_API_KEY]):
    print("Error: Missing required environment variables.")
    sys.exit(1)

def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)

headers = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com/",
    "Origin": "https://leetcode.com",
    "x-csrftoken": CSRF_TOKEN,
    "Cookie": f"LEETCODE_SESSION={LEETCODE_SESSION}; csrftoken={CSRF_TOKEN};",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

graphql_url = "https://leetcode.com/graphql"

# 1. Load State and Slugs
try:
    with open("striver_slugs.txt", "r") as f:
        slugs = [line.strip() for line in f if line.strip()]
    with open("striver_progress.txt", "r") as f:
        current_idx = int(f.read().strip())
except Exception as e:
    print(f"Error reading state files: {e}")
    sys.exit(1)

if current_idx >= len(slugs):
    print("Striver sheet completed!")
    send_telegram("🎉 *Striver A2Z Sheet Completed!*")
    sys.exit(0)

# 2. Find the next Free Problem
q_data = None
while current_idx < len(slugs):
    target_slug = slugs[current_idx]
    print(f"Checking index {current_idx}: {target_slug}...")
    
    query = {
        "query": """
        query questionData($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                questionId titleSlug title isPaidOnly content codeSnippets { langSlug code }
            }
        }
        """,
        "variables": {"titleSlug": target_slug}
    }
    
    res = cf_requests.post(graphql_url, json=query, headers=headers, impersonate="chrome")
    data = res.json().get("data", {}).get("question")
    
    if not data:
        print(f"Error fetching {target_slug}. Exiting.")
        sys.exit(1)
        
    if data.get("isPaidOnly"):
        print(f"Skipping {target_slug} (Premium Locked).")
        current_idx += 1
        continue
        
    q_data = data
    break

if not q_data:
    sys.exit(1)

q_id = q_data["questionId"]
safe_title = re.sub(r'[*_`\[\]]', '', q_data["title"])
print(f"Target Acquired: #{q_id} - {safe_title}")

py_snippet = next((s["code"] for s in q_data["codeSnippets"] if s["langSlug"] == "python3"), None)
if not py_snippet:
    print("Skipped: Python 3 not supported.")
    current_idx += 1
    with open("striver_progress.txt", "w") as f: f.write(str(current_idx))
    sys.exit(0)

# 3. Generate Solution via Gemini
print("Generating solution...")
prompt = f"""
You are an expert algorithm problem solver. Solve this LeetCode problem in Python 3.
Ensure optimal time and space complexity.
Return ONLY raw, executable Python 3 code matching the method signature below.

Template:
{py_snippet}

Problem:
{q_data['content']}
"""

gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
ai_payload = {"contents": [{"parts": [{"text": prompt}]}]}

for _ in range(3):
    ai_res = requests.post(gemini_url, json=ai_payload)
    if ai_res.status_code == 200:
        raw_code = ai_res.json()["candidates"][0]["content"]["parts"][0]["text"]
        match = re.search(r"```(?:python|python3)?\n(.*?)```", raw_code, re.DOTALL | re.IGNORECASE)
        clean_code = match.group(1).strip() if match else raw_code.strip()
        break
    time.sleep(5)
else:
    send_telegram("❌ *Striver Bot Failed*\nGemini API timeout.")
    sys.exit(1)

# 4. Submit to LeetCode
print("Submitting to LeetCode...")
submit_payload = {"lang": "python3", "question_id": q_id, "typed_code": clean_code}
sub_res = cf_requests.post(f"https://leetcode.com/problems/{target_slug}/submit/", json=submit_payload, headers=headers, impersonate="chrome")

if sub_res.status_code != 200:
    send_telegram(f"❌ *Striver Submission Failed*\nHTTP `{sub_res.status_code}`")
    sys.exit(1)

submission_id = sub_res.json().get("submission_id")

# 5. Poll for Verdict
for _ in range(30):
    time.sleep(5)
    status_res = cf_requests.get(f"https://leetcode.com/submissions/detail/{submission_id}/check/", headers=headers, impersonate="chrome").json()
    state = status_res.get("state")
    
    if state == "SUCCESS":
        if status_res.get("status_msg") == "Accepted":
            send_telegram(f"✅ *Striver A2Z Solved!*\n📌 *Problem:* #{q_id} - {safe_title}\n🔗 [View Problem](https://leetcode.com/problems/{target_slug}/)")
            
            # Save code locally for git sync
            folder_name = f"Striver-{str(q_id).zfill(4)}-{target_slug}"
            os.makedirs(folder_name, exist_ok=True)
            with open(f"{folder_name}/{folder_name}.py", "w", encoding="utf-8") as f: f.write(clean_code)
            
            # Increment progress bookmark
            with open("striver_progress.txt", "w") as f: f.write(str(current_idx + 1))
            print("Progress saved.")
        else:
            send_telegram(f"❌ *Striver Not Accepted*\nVerdict: `{status_res.get('status_error') or status_res.get('status_msg')}`")
            sys.exit(1)
        break
