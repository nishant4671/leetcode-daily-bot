import os
import re
import sys
import time
import random
import argparse
import requests
from curl_cffi import requests as cf_requests

# 1. Parse execution mode (daily or random)
parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["daily", "random"], default="daily")
args = parser.parse_args()

# 2. Load credentials from environment
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
    """Sends a markdown-formatted message to your Telegram chat."""
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

# 3. Fetch Problem Data based on Mode
q_data = None

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
        send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\nHTTP Error: `{res.status_code}`")
        sys.exit(1)
        
    try:
        q_data = res.json()["data"]["activeDailyCodingChallengeQuestion"]["question"]
    except Exception as e:
        send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\nParsing error: `{e}`")
        sys.exit(1)

elif args.mode == "random":
    print("Fetching a random unsolved free problem...")
    list_query = {
        "query": """
        query problemsetQuestionList($limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
            problemsetQuestionList(limit: $limit, skip: $skip, filters: $filters) {
                questions: data { titleSlug isPaidOnly }
            }
        }
        """,
        "variables": {"skip": 0, "limit": 50, "filters": {"status": "NOT_STARTED"}}
    }
    res = cf_requests.post(graphql_url, json=list_query, headers=headers, impersonate="chrome")
    
    try:
        questions = res.json()["data"]["problemsetQuestionList"]["questions"]
        free_questions = [q["titleSlug"] for q in questions if not q.get("isPaidOnly")]
        
        if not free_questions:
            send_telegram("⚠️ *LeetCode Random Bot*\nNo free unsolved problems found in the current batch.")
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
        send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\nRandom fetch error: `{e}`")
        sys.exit(1)

# Ensure data was found
if not q_data:
    sys.exit(1)

q_id = q_data["questionId"]
slug = q_data["titleSlug"]
title = q_data["title"]
print(f"Problem Found: #{q_id} - {title} ({slug})")

if not q_data.get("codeSnippets"):
    send_telegram(f"⚠️ *LeetCode {mode_title} Skipped*\nProblem: #{q_id} - *{title}*\nReason: No code snippets available (SQL/Shell).")
    sys.exit(0)

py_snippet = next((s["code"] for s in q_data["codeSnippets"] if s["langSlug"] == "python3"), None)
if not py_snippet:
    send_telegram(f"⚠️ *LeetCode {mode_title} Skipped*\nProblem: #{q_id} - *{title}*\nReason: Python3 not supported.")
    sys.exit(0)

# 4. Request solution from Gemini API
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
ai_payload = {"contents": [{"parts": [{"text": prompt}]}]}

for attempt in range(3):
    ai_res = requests.post(gemini_url, json=ai_payload)
    if ai_res.status_code == 200:
        break
    elif ai_res.status_code == 503:
        time.sleep(10)
    else:
        send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\nGemini API error: `{ai_res.status_code}`")
        sys.exit(1)
else:
    send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\nGemini API timed out after 3 retries.")
    sys.exit(1)

try:
    raw_code = ai_res.json()["candidates"][0]["content"]["parts"][0]["text"]
    match = re.search(r"```(?:python|python3)?\n(.*?)```", raw_code, re.DOTALL | re.IGNORECASE)
    clean_code = match.group(1).strip() if match else raw_code.strip()
except Exception as e:
    send_telegram(f"❌ *LeetCode {mode_title} Bot Failed*\nCode extraction error: `{e}`")
    sys.exit(1)

# 5. Submit solution to LeetCode
print("Submitting solution to LeetCode...")
submit_url = f"https://leetcode.com/problems/{slug}/submit/"
submit_payload = {"lang": "python3", "question_id": q_id, "typed_code": clean_code}

sub_res = cf_requests.post(submit_url, json=submit_payload, headers=headers, impersonate="chrome")
if sub_res.status_code != 200:
    send_telegram(f"❌ *LeetCode {mode_title} Submission Failed*\nHTTP status: `{sub_res.status_code}`")
    sys.exit(1)

submission_id = sub_res.json().get("submission_id")

# 6. Poll for the submission verdict
check_url = f"https://leetcode.com/submissions/detail/{submission_id}/check/"
for attempt in range(60):
    time.sleep(5)
    try:
        status_res = cf_requests.get(check_url, headers=headers, impersonate="chrome").json()
        state = status_res.get("state")
        
        if state == "SUCCESS":
            msg = status_res.get("status_msg")
            if msg == "Accepted":
                runtime = status_res.get("status_runtime", "N/A")
                memory = status_res.get("status_memory", "N/A")
                send_telegram(
                    f"✅ *LeetCode {mode_title} Solved!*\n\n"
                    f"📌 *Problem:* #{q_id} - {title}\n"
                    f"⏱ *Runtime:* `{runtime}`\n"
                    f"💾 *Memory:* `{memory}`\n"
                    f"🔗 [View Problem](https://leetcode.com/problems/{slug}/)"
                )
            else:
                fail_reason = status_res.get("status_error") or msg
                send_telegram(f"❌ *LeetCode {mode_title} Not Accepted*\nProblem: #{q_id} - {title}\nVerdict: `{fail_reason}`")
                sys.exit(1)
            break
    except Exception:
        pass
else:
    send_telegram(f"❌ *LeetCode {mode_title} Bot Timed Out*\nSubmission took over 5 minutes.")
    sys.exit(1)

# 7. Save locally for LeetHub sync
folder_name = f"{str(q_id).zfill(4)}-{slug}"
os.makedirs(folder_name, exist_ok=True)
with open(f"{folder_name}/{folder_name}.py", "w", encoding="utf-8") as f:
    f.write(clean_code)
with open(f"{folder_name}/README.md", "w", encoding="utf-8") as f:
    f.write(f"# {q_id}. {title}\n\n{q_data['content']}")
