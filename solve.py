import os
import re
import sys
import time
import random
import argparse
import requests
from curl_cffi import requests as cf_requests

# 1. Parse execution mode
parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["daily", "random"], default="daily")
args = parser.parse_args()

LEETCODE_SESSION = os.getenv("LEETCODE_SESSION")
CSRF_TOKEN = os.getenv("LEETCODE_CSRF_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not all([LEETCODE_SESSION, CSRF_TOKEN, GEMINI_API_KEY]):
    print("Error: Missing required environment variables.")
    sys.exit(1)

mode_title = args.mode.capitalize()

def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")

headers = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com/",
    "Origin": "https://leetcode.com",
    "x-csrftoken": CSRF_TOKEN,
    "Cookie": f"LEETCODE_SESSION={LEETCODE_SESSION}; csrftoken={CSRF_TOKEN};",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

graphql_url = "https://leetcode.com/graphql"
q_data = None

# 2. Fetch Problem Data based on Mode
if args.mode == "daily":
    print("Fetching Daily Challenge from LeetCode...")
    query = {
        "query": """
        query questionOfToday {
            activeDailyCodingChallengeQuestion {
                question { questionId titleSlug title content codeSnippets { langSlug code } }
            }
        }
        """
    }
    res = cf_requests.post(graphql_url, json=query, headers=headers, impersonate="chrome")
    if res.status_code != 200:
        err = f"HTTP Error {res.status_code}: {res.text}"
        print(err)
        send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\n`{err}`")
        sys.exit(1)
    try:
        q_data = res.json()["data"]["activeDailyCodingChallengeQuestion"]["question"]
    except Exception as e:
        err = f"Parsing error (Daily): {e} | JSON: {res.text}"
        print(err)
        send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\n`{e}`")
        sys.exit(1)

elif args.mode == "random":
    print("Fetching a random unsolved free problem...")
    # Safe offset to guarantee we hit a page with problems
    skip_offset = random.randint(0, 2000)
    list_query = {
        "query": """
        query problemsetQuestionList($limit: Int, $skip: Int) {
            problemsetQuestionList(limit: $limit, skip: $skip) {
                questions: data { titleSlug isPaidOnly status }
            }
        }
        """,
        "variables": {"skip": skip_offset, "limit": 50}
    }
    res = cf_requests.post(graphql_url, json=list_query, headers=headers, impersonate="chrome")
    
    try:
        data_block = res.json().get("data", {})
        if not data_block:
            raise ValueError(f"No data returned from LeetCode: {res.text}")
            
        questions = data_block.get("problemsetQuestionList", {}).get("questions", [])
        
        # Filter locally in Python instead of trusting LeetCode's GraphQL filters
        free_questions = [q["titleSlug"] for q in questions if not q.get("isPaidOnly") and q.get("status") not in ("ac", "AC")]
        
        if not free_questions:
            print("No free unsolved problems in this batch. Exiting gracefully.")
            sys.exit(0)
            
        random_slug = random.choice(free_questions)
        
        detail_query = {
            "query": """
            query questionData($titleSlug: String!) {
                question(titleSlug: $titleSlug) {
                    questionId titleSlug title content codeSnippets { langSlug code }
                }
            }
            """,
            "variables": {"titleSlug": random_slug}
        }
        res2 = cf_requests.post(graphql_url, json=detail_query, headers=headers, impersonate="chrome")
        q_data = res2.json()["data"]["question"]
    except Exception as e:
        err = f"Random fetch error: {e}"
        print(err)
        send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\n`{err}`")
        sys.exit(1)

if not q_data:
    print("Error: q_data is empty.")
    sys.exit(1)

q_id = q_data["questionId"]
slug = q_data["titleSlug"]
safe_title = re.sub(r'[*_`\[\]]', '', q_data["title"])
print(f"Problem Found: #{q_id} - {safe_title} ({slug})")

if not q_data.get("codeSnippets"):
    print("Skipped: No code snippets available.")
    send_telegram(f"⚠️ *LeetCode {mode_title} Skipped*\nProblem: #{q_id} - *{safe_title}*\nReason: No code snippets available.")
    sys.exit(0)

py_snippet = next((s["code"] for s in q_data["codeSnippets"] if s["langSlug"] == "python3"), None)
if not py_snippet:
    print("Skipped: Python 3 not supported.")
    send_telegram(f"⚠️ *LeetCode {mode_title} Skipped*\nProblem: #{q_id} - *{safe_title}*\nReason: Python3 not supported.")
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

gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
ai_payload = {"contents": [{"parts": [{"text": prompt}]}]}

for attempt in range(3):
    ai_res = requests.post(gemini_url, json=ai_payload)
    if ai_res.status_code == 200:
        break
    elif ai_res.status_code == 503:
        print("Gemini API overloaded. Retrying in 10s...")
        time.sleep(10)
    else:
        err = f"Gemini HTTP Error {ai_res.status_code}: {ai_res.text}"
        print(err)
        send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\n`{err}`")
        sys.exit(1)
else:
    print("Gemini API timed out after 3 retries.")
    send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\nGemini API timed out.")
    sys.exit(1)

try:
    ai_json = ai_res.json()
    if "candidates" not in ai_json:
        raise ValueError(f"Unexpected Gemini response format: {ai_json}")
        
    raw_code = ai_json["candidates"][0]["content"]["parts"][0]["text"]
    match = re.search(r"```(?:python|python3)?\n(.*?)```", raw_code, re.DOTALL | re.IGNORECASE)
    clean_code = match.group(1).strip() if match else raw_code.strip()
except Exception as e:
    err = f"Code extraction error: {e}"
    print(err)
    send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\n`{err}`")
    sys.exit(1)

# 4. Submit solution to LeetCode
print("Submitting solution to LeetCode...")
submit_url = f"https://leetcode.com/problems/{slug}/submit/"
submit_payload = {"lang": "python3", "question_id": q_id, "typed_code": clean_code}

sub_res = cf_requests.post(submit_url, json=submit_payload, headers=headers, impersonate="chrome")
if sub_res.status_code != 200:
    err = f"Submission HTTP status: {sub_res.status_code} | {sub_res.text}"
    print(err)
    send_telegram(f"❌ *LeetCode {mode_title} Submission Failed*\n`{err}`")
    sys.exit(1)

submission_id = sub_res.json().get("submission_id")

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
                send_telegram(
                    f"✅ *LeetCode {mode_title} Solved!*\n\n"
                    f"📌 *Problem:* #{q_id} - {safe_title}\n"
                    f"⏱ *Runtime:* `{runtime}`\n"
                    f"💾 *Memory:* `{memory}`\n"
                    f"🔗 [View Problem](https://leetcode.com/problems/{slug}/)"
                )
            else:
                fail_reason = status_res.get("status_error") or msg
                send_telegram(f"❌ *LeetCode {mode_title} Not Accepted*\nProblem: #{q_id} - {safe_title}\nVerdict: `{fail_reason}`")
                sys.exit(1)
            break
        else:
            print(f"Polling... State: {state}")
    except Exception as e:
        print(f"Error checking status: {e}")
else:
    print("Submission timed out.")
    send_telegram(f"❌ *LeetCode {mode_title} Bot Timed Out*\nSubmission took over 5 minutes.")
    sys.exit(1)

# 6. Save locally for LeetHub sync
folder_name = f"{str(q_id).zfill(4)}-{slug}"
os.makedirs(folder_name, exist_ok=True)
with open(f"{folder_name}/{folder_name}.py", "w", encoding="utf-8") as f:
    f.write(clean_code)
with open(f"{folder_name}/README.md", "w", encoding="utf-8") as f:
    f.write(f"# {q_id}. {q_data['title']}\n\n{q_data['content']}")

print("Success! Code saved locally.")
