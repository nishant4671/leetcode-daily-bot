import os
import re
import sys
import time
import random
import requests
import ast
from curl_cffi import requests as cf_requests

# ============================================================================
# 1. ENVIRONMENT VARIABLES HARD CHECK (FAIL FAST)
# ============================================================================
def verify_environment():
    """
    Verify all required environment variables are present before any execution.
    Raises ValueError immediately if any are missing.
    """
    required_vars = {
        "GEMINI_API_KEY": "Google Gemini API Key",
        "GROQ_API_KEY": "Groq API Key",
        "LEETCODE_SESSION": "LeetCode session cookie",
        "LEETCODE_CSRF_TOKEN": "LeetCode CSRF token",
    }
    
    missing = []
    for var_name, description in required_vars.items():
        if not os.environ.get(var_name):
            missing.append(f"{var_name} ({description})")
    
    if missing:
        error_msg = "Error: Missing required environment variables:\n" + "\n".join(f"  - {m}" for m in missing)
        print(error_msg)
        raise ValueError(error_msg)


# ============================================================================
# 2. LEETCODE SESSION PRE-FLIGHT VALIDATION
# ============================================================================
def verify_leetcode_session():
    """
    Verify LeetCode session is active by making a lightweight GraphQL request.
    Raises EnvironmentError if session is invalid or expired.
    """
    leetcode_session = os.environ.get("LEETCODE_SESSION")
    csrf_token = os.environ.get("LEETCODE_CSRF_TOKEN")
    
    headers = {
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com/",
        "Origin": "https://leetcode.com",
        "x-csrftoken": csrf_token,
        "Cookie": f"LEETCODE_SESSION={leetcode_session}; csrftoken={csrf_token};",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # Lightweight query to check session validity (query user profile)
    test_query = {
        "query": """
        query me {
            me {
                username
            }
        }
        """
    }
    
    try:
        response = requests.post("https://leetcode.com/graphql", json=test_query, headers=headers, timeout=10)
        
        if response.status_code == 403:
            raise EnvironmentError("LeetCode session cookie has expired. Please refresh Secrets.")
        
        if response.status_code != 200:
            raise EnvironmentError(f"LeetCode session validation failed with status {response.status_code}. Please refresh Secrets.")
        
        data = response.json()
        if data.get("errors") or not data.get("data", {}).get("me"):
            raise EnvironmentError("LeetCode session is invalid or user not authenticated. Please refresh Secrets.")
        
        print("✓ LeetCode session verified successfully.")
        
    except requests.exceptions.RequestException as e:
        raise EnvironmentError(f"Failed to validate LeetCode session: {str(e)}. Please check your network connection.")


# ============================================================================
# 3. CODE SYNTAX PRE-FLIGHT VALIDATION (AST VALIDATION)
# ============================================================================
def validate_code_syntax(code: str) -> bool:
    """
    Validate generated Python code before submission using AST parsing.
    Returns True if code is syntactically valid, False otherwise.
    """
    try:
        ast.parse(code)
        return True
    except SyntaxError as e:
        print(f"SyntaxError detected in LLM output: {e}")
        return False


# ============================================================================
# 4. SAFE ERROR LOGGING (PREVENT SECRET LEAKS)
# ============================================================================
def log_http_error(url: str, status_code: int, error_detail: str = ""):
    """
    Log HTTP errors safely without exposing headers or sensitive data.
    """
    print(f"Failed to connect to {url}: HTTP {status_code}")
    if error_detail:
        print(f"Details: {error_detail}")


# ============================================================================
# MAIN EXECUTION STARTS HERE
# ============================================================================

# Verify environment and session BEFORE any other operations
try:
    verify_environment()
    verify_leetcode_session()
except (ValueError, EnvironmentError) as e:
    print(str(e))
    sys.exit(1)

LEETCODE_SESSION = os.getenv("LEETCODE_SESSION")
CSRF_TOKEN = os.getenv("LEETCODE_CSRF_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")

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
    
    try:
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
    except Exception as e:
        print(f"Exception while fetching {target_slug}: {e}")
        sys.exit(1)

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

models = ["gemini-2.5-flash", "gemini-1.5-flash"]
clean_code = None

for model in models:
    if clean_code:
        break
    print(f"Trying Gemini model: {model}...")
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
    ai_payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    for attempt in range(3):
        try:
            ai_res = requests.post(gemini_url, json=ai_payload, timeout=120)
            if ai_res.status_code == 200:
                try:
                    raw_code = ai_res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    match = re.search(r"```(?:python|python3)?\n(.*?)```", raw_code, re.DOTALL | re.IGNORECASE)
                    clean_code = match.group(1).strip() if match else raw_code.strip()
                    
                    # Validate syntax before accepting
                    if clean_code and validate_code_syntax(clean_code):
                        break
                    elif clean_code:
                        print(f"Code generated but contains syntax errors. Retrying with {model}...")
                        clean_code = None
                        break
                    else:
                        break
                except Exception as e:
                    print(f"Code extraction error with {model}: {e}")
                    break
            elif ai_res.status_code in [429, 503]:
                sleep_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                print(f"Gemini API rate limited/overloaded. Retrying in {sleep_time:.2f}s...")
                time.sleep(sleep_time)
            else:
                log_http_error(gemini_url, ai_res.status_code)
                break
        except Exception as e:
            print(f"Exception while querying {model}: {e}")
            break

if not clean_code:
    print("Gemini models failed. Failing over to Groq API...")
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        send_telegram("❌ *Striver Bot Failed*\nGROQ_API_KEY not found.")
        sys.exit(1)
        
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    groq_headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }
    groq_payload = {
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "You are an elite competitive programmer. Return only clean, runnable code."},
            {"role": "user", "content": prompt}
        ]
    }
    
    for attempt in range(3):
        try:
            groq_res = requests.post(groq_url, json=groq_payload, headers=groq_headers, timeout=120)
            if groq_res.status_code == 200:
                try:
                    raw_code = groq_res.json()["choices"][0]["message"]["content"]
                    match = re.search(r"```(?:python|python3)?\n(.*?)```", raw_code, re.DOTALL | re.IGNORECASE)
                    clean_code = match.group(1).strip() if match else raw_code.strip()
                    
                    # Validate syntax before accepting
                    if clean_code and validate_code_syntax(clean_code):
                        break
                    elif clean_code:
                        print("Code generated but contains syntax errors. Retrying...")
                        clean_code = None
                        break
                    else:
                        break
                except Exception as e:
                    print(f"Code extraction error with Groq: {e}")
                    break
            elif groq_res.status_code in [429, 503]:
                sleep_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                print(f"Groq API rate limited/overloaded. Retrying in {sleep_time:.2f}s...")
                time.sleep(sleep_time)
            else:
                log_http_error(groq_url, groq_res.status_code)
                break
        except Exception as e:
            print(f"Exception while querying Groq: {e}")
            break

if not clean_code:
    send_telegram("❌ *Striver Bot Failed*\nAll AI models failed to generate valid code.")
    sys.exit(1)

# 4. Submit to LeetCode
print("Submitting to LeetCode...")
submit_payload = {"lang": "python3", "question_id": q_id, "typed_code": clean_code}

try:
    sub_res = cf_requests.post(f"https://leetcode.com/problems/{target_slug}/submit/", json=submit_payload, headers=headers, impersonate="chrome")

    if sub_res.status_code != 200:
        log_http_error(f"https://leetcode.com/problems/{target_slug}/submit/", sub_res.status_code)
        send_telegram(f"❌ *Striver Submission Failed*\nHTTP {sub_res.status_code}")
        sys.exit(1)

    submission_id = sub_res.json().get("submission_id")
except Exception as e:
    print(f"Exception during submission: {e}")
    send_telegram(f"❌ *Striver Submission Failed*\n`{str(e)}`")
    sys.exit(1)

# 5. Poll for Verdict
for _ in range(30):
    time.sleep(5)
    try:
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
    except Exception as e:
        print(f"Error checking status: {e}")
