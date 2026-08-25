import os
import re
import sys
import time
import requests

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

res = requests.post("https://leetcode.com/graphql", json=graphql_query, headers=headers)
if res.status_code != 200:
    print(f"Failed to fetch daily challenge: {res.status_code} - {res.text}")
    sys.exit(1)

q_data = res.json()["data"]["activeDailyCodingChallengeQuestion"]["question"]
q_id = q_data["questionId"]
slug = q_data["titleSlug"]
print(f"Problem Found: #{q_id} - {q_data['title']} ({slug})")

# 3. Extract Python 3 starter snippet
py_snippet = next((s["code"] for s in q_data["codeSnippets"] if s["langSlug"] == "python3"), None)
if not py_snippet:
    print("Error: Python3 code snippet not found for this problem.")
    sys.exit(1)

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

ai_res = requests.post(gemini_url, json=ai_payload)
if ai_res.status_code != 200:
    print(f"Gemini API Error: {ai_res.status_code} - {ai_res.text}")
    sys.exit(1)

raw_code = ai_res.json()["candidates"][0]["content"]["parts"][0]["text"]
# Strip code fences if the model included them
clean_code = re.sub(r"^```python\s*|^```\s*|```$", "", raw_code, flags=re.MULTILINE).strip()

# 5. Submit solution to LeetCode
print("Submitting solution to LeetCode...")
submit_url = f"https://leetcode.com/problems/{slug}/submit/"
submit_payload = {
    "lang": "python3",
    "question_id": q_id,
    "typed_code": clean_code
}

sub_res = requests.post(submit_url, json=submit_payload, headers=headers)
if sub_res.status_code != 200:
    print(f"Submission request failed: {sub_res.status_code} - {sub_res.text}")
    sys.exit(1)

submission_id = sub_res.json().get("submission_id")
if not submission_id:
    print(f"No submission ID returned: {sub_res.json()}")
    sys.exit(1)

print(f"Submission ID: {submission_id}. Checking result status...")

# 6. Poll for the submission verdict
check_url = f"[https://leetcode.com/submissions/detail/](https://leetcode.com/submissions/detail/){submission_id}/check/"
for attempt in range(12):
    time.sleep(3)
    status_res = requests.get(check_url, headers=headers).json()
    state = status_res.get("state")
    
    if state == "SUCCESS":
        msg = status_res.get("status_msg")
        print(f"Verdict: {msg}")
        if msg == "Accepted":
            print(f"Runtime: {status_res.get('status_runtime')} | Memory: {status_res.get('status_memory')}")
        else:
            print(f"Failed reason: {status_res.get('status_error') or msg}")
        break
    else:
        print(f"Processing... ({state})")
else:
    print("Timed out waiting for submission result.")
