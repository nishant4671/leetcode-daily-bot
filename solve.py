import os
import re
import sys
import time
import requests
from curl_cffi import requests as cf_requests

# 1. Load credentials from environment
LEETCODE_SESSION = os.getenv("LEETCODE_SESSION")
CSRF_TOKEN = os.getenv("LEETCODE_CSRF_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not all([LEETCODE_SESSION, CSRF_TOKEN, GEMINI_API_KEY]):
    print("Error: Missing required environment variables.")
    sys.exit(1)

def send_telegram(message: str):
    """Sends a markdown-formatted message to your Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not configured. Skipping notification.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("Telegram notification sent.")
        else:
            print(f"Failed to send Telegram message: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")

# 2. Fetch the Daily Coding Challenge
print("Fetching Daily Challenge from LeetCode...")
graphql_query = {
    "query": """
    query questionOfToday {
        activeDailyCodingChallengeQuestion {
            question {
                questionId
                titleSlug
                title
                content
                codeSnippets {
                    langSlug
                    code
                }
            }
        }
    }
    """
}

graphql_url = "https://leetcode.com/graphql"
headers = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com/",
    "Origin": "https://leetcode.com",
    "x-csrftoken": CSRF_TOKEN,
    "Cookie": f"LEETCODE_SESSION={LEETCODE_SESSION}; csrftoken={CSRF_TOKEN};",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

res = cf_requests.post(graphql_url, json=graphql_query, headers=headers, impersonate="chrome")

if res.status_code != 200:
    err_msg = f"❌ *LeetCode Daily Bot Failed*\nFailed to fetch daily challenge: `{res.status_code}`"
    send_telegram(err_msg)
    print(f"Failed to fetch daily challenge: {res.status_code} - {res.text}")
    sys.exit(1)

try:
    json_data = res.json()
    if "errors" in json_data:
        send_telegram(f"❌ *LeetCode Daily Bot Failed*\nGraphQL returned errors: `{json_data['errors']}`")
        sys.exit(1)
        
    if "data" not in json_data or not json_data["data"].get("activeDailyCodingChallengeQuestion"):
        send_telegram("❌ *LeetCode Daily Bot Failed*\nUnexpected API schema or no challenge found.")
        sys.exit(1)

    q_data = json_data["data"]["activeDailyCodingChallengeQuestion"]["question"]
    q_id = q_data["questionId"]
    slug = q_data["titleSlug"]
    title = q_data["title"]
    print(f"Problem Found: #{q_id} - {title} ({slug})")
except Exception as e:
    send_telegram(f"❌ *LeetCode Daily Bot Failed*\nParsing error: `{e}`")
    sys.exit(1)

if not q_data.get("codeSnippets"):
    send_telegram(f"⚠️ *LeetCode Daily Challenge Skipped*\nProblem: #{q_id} - *{title}*\nReason: No code snippets available (SQL/Shell).")
    sys.exit(0)

py_snippet = next((s["code"] for s in q_data["codeSnippets"] if s["langSlug"] == "python3"), None)
if not py_snippet:
    send_telegram(f"⚠️ *LeetCode Daily Challenge Skipped*\nProblem: #{q_id} - *{title}*\nReason: Python3 not supported for this problem.")
    sys.exit(0)

# 3. Request solution from Gemini API
print("Generating solution via Gemini...")
prompt = f"""
You are an expert algorithm problem solver. Solve this LeetCode problem in Python 3.
Ensure optimal time and space complexity.
Return ONLY raw, executable Python 3 code matching the method signature below.
Do not include explanations, comments, or extra markdown backticks.

Template:
{py_snippet}

Problem:
{q_data['content']}
"""

gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
ai_payload = {
    "contents": [{"parts": [{"text": prompt}]}]
}

max_retries = 3
for attempt in range(max_retries):
    ai_res = requests.post(gemini_url, json=ai_payload)
    if ai_res.status_code == 200:
        break
    elif ai_res.status_code == 503:
        print(f"Gemini API overloaded (503). Retrying in 10s... ({attempt + 1}/{max_retries})")
        time.sleep(10)
    else:
        send_telegram(f"❌ *LeetCode Daily Bot Failed*\nGemini API error: `{ai_res.status_code}`")
        sys.exit(1)
else:
    send_telegram("❌ *LeetCode Daily Bot Failed*\nGemini API timed out after 3 retries.")
    sys.exit(1)

try:
    raw_code = ai_res.json()["candidates"][0]["content"]["parts"][0]["text"]
    match = re.search(r"```(?:python|python3)?\n(.*?)```", raw_code, re.DOTALL | re.IGNORECASE)
    clean_code = match.group(1).strip() if match else raw_code.strip()
except Exception as e:
    send_telegram(f"❌ *LeetCode Daily Bot Failed*\nCode extraction error: `{e}`")
    sys.exit(1)

# 4. Submit solution to LeetCode
print("Submitting solution to LeetCode...")
submit_url = f"https://leetcode.com/problems/{slug}/submit/"
submit_payload = {
    "lang": "python3",
    "question_id": q_id,
    "typed_code": clean_code
}

sub_res = cf_requests.post(submit_url, json=submit_payload, headers=headers, impersonate="chrome")
if sub_res.status_code != 200:
    send_telegram(f"❌ *LeetCode Submission Failed*\nHTTP status: `{sub_res.status_code}`")
    sys.exit(1)

submission_id = sub_res.json().get("submission_id")
if not submission_id:
    send_telegram("❌ *LeetCode Submission Failed*\nNo submission ID returned.")
    sys.exit(1)

print(f"Submission ID: {submission_id}. Checking result status...")

# 5. Poll for the submission verdict
check_url = f"https://leetcode.com/submissions/detail/{submission_id}/check/"
for attempt in range(60):
    time.sleep(5)
    try:
        status_res = cf_requests.get(check_url, headers=headers, impersonate="chrome").json()
        state = status_res.get("state")
        
        if state == "SUCCESS":
            msg = status_res.get("status_msg")
            print(f"Verdict: {msg}")
            if msg == "Accepted":
                runtime = status_res.get("status_runtime", "N/A")
                memory = status_res.get("status_memory", "N/A")
                
                success_msg = (
                    f"✅ *LeetCode Daily Challenge Solved!*\n\n"
                    f"📌 *Problem:* #{q_id} - {title}\n"
                    f"⏱ *Runtime:* `{runtime}`\n"
                    f"💾 *Memory:* `{memory}`\n"
                    f"🔗 [View Problem](https://leetcode.com/problems/{slug}/)"
                )
                send_telegram(success_msg)
            else:
                fail_reason = status_res.get("status_error") or msg
                send_telegram(f"❌ *LeetCode Submission Not Accepted*\nProblem: #{q_id} - {title}\nVerdict: `{fail_reason}`")
                sys.exit(1)
            break
        else:
            print(f"Processing... ({state})")
    except Exception as e:
        print(f"Error checking status (attempt {attempt + 1}): {e}")
else:
    send_telegram(f"❌ *LeetCode Daily Bot Timed Out*\nSubmission ID: `{submission_id}` took over 5 minutes.")
    sys.exit(1)

# 6. Save locally for LeetHub sync
print("Saving code locally for LeetHub sync...")
folder_name = f"{str(q_id).zfill(4)}-{slug}"
os.makedirs(folder_name, exist_ok=True)

file_name = f"{folder_name}.py"
with open(f"{folder_name}/{file_name}", "w", encoding="utf-8") as f:
    f.write(clean_code)

with open(f"{folder_name}/README.md", "w", encoding="utf-8") as f:
    f.write(f"# {q_id}. {title}\n\n")
    f.write(q_data['content'])
    
print(f"Saved {file_name} and README.md to {folder_name}/")
