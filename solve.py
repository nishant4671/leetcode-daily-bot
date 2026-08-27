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

if not all([LEETCODE_SESSION, CSRF_TOKEN, GEMINI_API_KEY]):
    print("Error: Missing required environment variables.")
    sys.exit(1)

headers = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com/",
    "Origin": "https://leetcode.com",
    "x-csrftoken": CSRF_TOKEN,
    "Cookie": f"LEETCODE_SESSION={LEETCODE_SESSION}; csrftoken={CSRF_TOKEN};",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

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
res = cf_requests.post(graphql_url, json=graphql_query, headers=headers, impersonate="chrome")

if res.status_code != 200:
    print(f"Failed to fetch daily challenge: {res.status_code} - {res.text}")
    sys.exit(1)

# PHASE 2 FIX: Strict GraphQL Schema Validation
try:
    json_data = res.json()
    if "errors" in json_data:
        print(f"LeetCode GraphQL returned errors: {json_data['errors']}")
        sys.exit(1)
        
    if "data" not in json_data or not json_data["data"].get("activeDailyCodingChallengeQuestion"):
        print(f"Unexpected API schema or no active challenge found: {json_data}")
        sys.exit(1)

    q_data = json_data["data"]["activeDailyCodingChallengeQuestion"]["question"]
    q_id = q_data["questionId"]
    slug = q_data["titleSlug"]
    print(f"Problem Found: #{q_id} - {q_data['title']} ({slug})")
except Exception as e:
    print(f"Error parsing daily challenge data: {e} - Response: {res.text}")
    sys.exit(1)

# PHASE 2 FIX: Graceful handling of missing Python stubs (e.g., SQL/Bash problems)
if not q_data.get("codeSnippets"):
    print("Notice: No code snippets available for this problem. Skipping submission.")
    sys.exit(0) # Exit 0 means success so the Action doesn't show a red 'X'

py_snippet = next((s["code"] for s in q_data["codeSnippets"] if s["langSlug"] == "python3"), None)
if not py_snippet:
    print("Notice: Python3 code snippet not found for this problem. Skipping submission.")
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
ai_payload = {
    "contents": [{"parts": [{"text": prompt}]}]
}

# Retry logic for Gemini API overload
max_retries = 3
for attempt in range(max_retries):
    ai_res = requests.post(gemini_url, json=ai_payload)
    if ai_res.status_code == 200:
        break
    elif ai_res.status_code == 503:
        print(f"Gemini API overloaded (503). Retrying in 10 seconds... (Attempt {attempt + 1} of {max_retries})")
        time.sleep(10)
    else:
        print(f"Gemini API Error: {ai_res.status_code} - {ai_res.text}")
        sys.exit(1)
else:
    print("Gemini API failed after multiple retries. Exiting.")
    sys.exit(1)

try:
    raw_code = ai_res.json()["candidates"][0]["content"]["parts"][0]["text"]
    match = re.search(r"```(?:python|python3)?\n(.*?)```", raw_code, re.DOTALL | re.IGNORECASE)
    clean_code = match.group(1).strip() if match else raw_code.strip()
except Exception as e:
    print(f"Error parsing Gemini response: {e} - Response: {ai_res.text}")
    sys.exit(1)

# 5. Submit solution to LeetCode
print("Submitting solution to LeetCode...")
submit_url = f"https://leetcode.com/problems/{slug}/submit/"
submit_payload = {
    "lang": "python3",
    "question_id": q_id,
    "typed_code": clean_code
}

sub_res = cf_requests.post(submit_url, json=submit_payload, headers=headers, impersonate="chrome")
if sub_res.status_code != 200:
    print(f"Submission request failed: {sub_res.status_code} - {sub_res.text}")
    sys.exit(1)

submission_id = sub_res.json().get("submission_id")
if not submission_id:
    print(f"No submission ID returned: {sub_res.json()}")
    sys.exit(1)

print(f"Submission ID: {submission_id}. Checking result status...")

# 6. Poll for the submission verdict
# PHASE 2 FIX: Hard timeout (60 attempts * 5 seconds = 5 minutes max)
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
                print(f"Runtime: {status_res.get('status_runtime')} | Memory: {status_res.get('status_memory')}")
            else:
                print(f"Failed reason: {status_res.get('status_error') or msg}")
                # If it's a Wrong Answer/Compile Error, exit 1 so we get notified
                sys.exit(1) 
            break
        else:
            print(f"Processing... ({state})")
    except Exception as e:
        print(f"Error checking status (attempt {attempt + 1}): {e}")
else:
    print("Timed out waiting for submission result after 5 minutes.")
    sys.exit(1)

# 7. Save locally for LeetHub sync
print("Saving code locally for LeetHub sync...")
folder_name = f"{str(q_id).zfill(4)}-{slug}"
os.makedirs(folder_name, exist_ok=True)

file_name = f"{folder_name}.py"
with open(f"{folder_name}/{file_name}", "w", encoding="utf-8") as f:
    f.write(clean_code)

with open(f"{folder_name}/README.md", "w", encoding="utf-8") as f:
    f.write(f"# {q_id}. {q_data['title']}\n\n")
    f.write(q_data['content'])
    
print(f"Saved {file_name} and README.md to {folder_name}/")
