# import os
# import re
# import sys
# import time
# import random
# import ast
# import requests
# from bs4 import BeautifulSoup
# from curl_cffi import requests as cf_requests

# # ============================================================================
# # 1. ENVIRONMENT VARIABLES HARD CHECK (FAIL FAST)
# # ============================================================================
# def verify_environment():
#     """
#     Verify all required environment variables are present before any execution.
#     Raises ValueError immediately if any are missing.
#     """
#     required_vars = {
#         "CODEFORCES_HANDLE": "Codeforces user handle",
#         "CODEFORCES_SESSION_COOKIE": "Codeforces session cookie (JSESSIONID)",
#         "GEMINI_API_KEY": "Google Gemini API Key",
#         "GROQ_API_KEY": "Groq API Key",
#         "TELEGRAM_BOT_TOKEN": "Telegram Bot Token",
#         "TELEGRAM_CHAT_ID": "Telegram Chat ID",
#     }

#     missing = []
#     for var_name, description in required_vars.items():
#         if not os.environ.get(var_name):
#             missing.append(f"{var_name} ({description})")

#     if missing:
#         error_msg = "Error: Missing required environment variables:\n" + "\n".join(f"  - {m}" for m in missing)
#         print(error_msg)
#         raise ValueError(error_msg)


# # ============================================================================
# # 2. CODEFORCES SESSION PRE-FLIGHT VALIDATION
# # ============================================================================
# def verify_codeforces_session():
#     """
#     Verify Codeforces session is active by making a request to user profile.
#     Raises EnvironmentError if HTTP status is not 200 or redirects to login screen.
#     """
#     handle = os.environ.get("CODEFORCES_HANDLE", "").strip()
#     session_cookie = os.environ.get("CODEFORCES_SESSION_COOKIE", "").strip()

#     profile_url = f"https://codeforces.com/profile/{handle}"
#     headers = {
#         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
#         "Cookie": f"JSESSIONID={session_cookie};",
#     }
#     cookies = {"JSESSIONID": session_cookie}

#     try:
#         response = cf_requests.get(
#             profile_url,
#             headers=headers,
#             cookies=cookies,
#             impersonate="chrome",
#             timeout=15,
#         )

#         if response.status_code != 200:
#             raise EnvironmentError(f"Codeforces session validation failed with HTTP {response.status_code}")

#         final_url = str(getattr(response, "url", ""))
#         # Check if redirected to the login screen
#         if "/enter" in final_url or "/login" in final_url:
#             raise EnvironmentError("Codeforces session cookie has expired or redirected to login screen.")

#         # Check if login forms indicate unauthenticated state
#         if 'action="/enter"' in response.text and 'class="enter"' in response.text and f"/profile/{handle}" not in response.text:
#             raise EnvironmentError("Codeforces session cookie is invalid or expired. Redirected to login.")

#         print(f"✓ Authentication verified for Codeforces user: {handle}")

#     except Exception as e:
#         if isinstance(e, EnvironmentError):
#             raise
#         raise EnvironmentError(f"Failed to validate Codeforces session: {str(e)}. Please check your network connection.")


# # ============================================================================
# # 3. CODE SYNTAX PRE-FLIGHT VALIDATION (AST VALIDATION)
# # ============================================================================
# def validate_code_syntax(code: str) -> bool:
#     """
#     Validate generated Python code before submission using AST parsing.
#     Returns True if code is syntactically valid, False otherwise.
#     """
#     try:
#         ast.parse(code)
#         return True
#     except SyntaxError as e:
#         print(f"SyntaxError detected in LLM output: {e}")
#         return False


# # ============================================================================
# # 4. SAFE ERROR LOGGING (PREVENT SECRET LEAKS)
# # ============================================================================
# def log_http_error(url: str, status_code: int, error_detail: str = ""):
#     """
#     Log HTTP errors safely without exposing headers or sensitive data.
#     """
#     print(f"Failed to connect to {url}: HTTP {status_code}")
#     if error_detail:
#         print(f"Details: {error_detail}")


# # ============================================================================
# # 5. TELEGRAM NOTIFICATIONS
# # ============================================================================
# def send_telegram(message: str):
#     """Sends a markdown-formatted message to Telegram."""
#     token = os.getenv("TELEGRAM_BOT_TOKEN")
#     chat_id = os.getenv("TELEGRAM_CHAT_ID")
#     if not token or not chat_id:
#         return
#     url = f"https://api.telegram.org/bot{token}/sendMessage"
#     payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
#     try:
#         requests.post(url, json=payload, timeout=10)
#     except Exception as e:
#         print(f"Error sending Telegram notification: {e}")


# # ============================================================================
# # 6. AI GENERATION & FALLBACK PIPELINE
# # ============================================================================
# def query_groq_hard_problem(prompt: str) -> str:
#     """
#     Query Groq's OpenAI GPT-OSS-120B model as fallback solver.
#     """
#     groq_api_key = os.getenv("GROQ_API_KEY")
#     if not groq_api_key:
#         print("GROQ_API_KEY not set. Skipping Groq solver.")
#         return ""

#     print("Attempting Groq openai/gpt-oss-120b model...")

#     groq_url = "https://api.groq.com/openai/v1/chat/completions"
#     groq_headers = {
#         "Authorization": f"Bearer {groq_api_key}",
#         "Content-Type": "application/json",
#     }
#     groq_payload = {
#         "model": "openai/gpt-oss-120b",
#         "temperature": 0.2,
#         "messages": [
#             {
#                 "role": "system",
#                 "content": (
#                     "You are an elite competitive programmer solving a Codeforces problem in Python 3.\n"
#                     "CRITICAL REQUIREMENTS:\n"
#                     "1. Read all input directly from standard input using sys.stdin.read().split() or input().\n"
#                     "2. Write all output directly to standard output using sys.stdout.write() or print().\n"
#                     "3. Do NOT use interactive prompts like input('Enter number: ').\n"
#                     "4. Do NOT wrap code in LeetCode-style classes or methods. Output flat script code or main() execution.\n"
#                     "5. Ensure optimal time and space complexity.\n"
#                     "6. Return ONLY clean, executable Python 3 code. No markdown fences, no explanations."
#                 ),
#             },
#             {
#                 "role": "user",
#                 "content": prompt,
#             },
#         ],
#     }

#     for attempt in range(3):
#         try:
#             groq_res = requests.post(groq_url, json=groq_payload, headers=groq_headers, timeout=120)
#             if groq_res.status_code == 200:
#                 try:
#                     raw_code = groq_res.json()["choices"][0]["message"]["content"]
#                     match = re.search(r"```(?:python|python3)?\n(.*?)```", raw_code, re.DOTALL | re.IGNORECASE)
#                     clean_code = match.group(1).strip() if match else raw_code.strip()
#                     if clean_code.startswith("```"):
#                         clean_code = re.sub(r"^```[a-zA-Z0-9]*\n?", "", clean_code)
#                     if clean_code.endswith("```"):
#                         clean_code = re.sub(r"\n?```$", "", clean_code)
#                     clean_code = clean_code.strip()

#                     # Validate syntax before returning
#                     if clean_code and validate_code_syntax(clean_code):
#                         print("✓ Groq gpt-oss-120b generated valid code.")
#                         return clean_code
#                     elif clean_code:
#                         print("Code generated but contains syntax errors. Retrying...")
#                         continue
#                     else:
#                         print("Groq gpt-oss-120b generated empty code.")
#                         continue
#                 except Exception as e:
#                     print(f"Code extraction error with Groq gpt-oss-120b: {e}")
#                     return ""
#             elif groq_res.status_code in [429, 503]:
#                 sleep_time = (2 ** attempt) + random.uniform(0.5, 1.5)
#                 print(f"Groq gpt-oss-120b API rate limited/overloaded. Retrying in {sleep_time:.2f}s...")
#                 time.sleep(sleep_time)
#             else:
#                 log_http_error(groq_url, groq_res.status_code, "Groq API error")
#                 return ""
#         except Exception as e:
#             print(f"Exception while querying Groq gpt-oss-120b: {e}")
#             return ""

#     return ""


# def generate_solution_with_fallback(prompt: str) -> str:
#     """
#     Generate solution code with Gemini Flash models first (with exponential backoff
#     for 429/503 errors and AST syntax validation), falling back to Groq openai/gpt-oss-120b.
#     """
#     clean_code = None
#     gemini_api_key = os.getenv("GEMINI_API_KEY")
#     models = ["gemini-2.5-flash", "gemini-1.5-flash"]

#     for model in models:
#         if clean_code:
#             break
#         print(f"Trying Gemini model: {model}...")
#         gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_api_key}"
#         ai_payload = {"contents": [{"parts": [{"text": prompt}]}]}

#         for attempt in range(3):
#             try:
#                 ai_res = requests.post(gemini_url, json=ai_payload, timeout=120)
#                 if ai_res.status_code == 200:
#                     try:
#                         ai_json = ai_res.json()
#                         if "candidates" not in ai_json:
#                             raise ValueError("Unexpected Gemini response format")
#                         raw_code = ai_json["candidates"][0]["content"]["parts"][0]["text"]
#                         match = re.search(r"```(?:python|python3)?\n(.*?)```", raw_code, re.DOTALL | re.IGNORECASE)
#                         clean_code = match.group(1).strip() if match else raw_code.strip()
#                         if clean_code.startswith("```"):
#                             clean_code = re.sub(r"^```[a-zA-Z0-9]*\n?", "", clean_code)
#                         if clean_code.endswith("```"):
#                             clean_code = re.sub(r"\n?```$", "", clean_code)
#                         clean_code = clean_code.strip()

#                         # Validate syntax before returning
#                         if clean_code and validate_code_syntax(clean_code):
#                             break
#                         elif clean_code:
#                             print(f"Code generated but contains syntax errors. Retrying with {model}...")
#                             clean_code = None
#                             continue
#                         else:
#                             break
#                     except Exception as e:
#                         print(f"Code extraction error with {model}: {e}")
#                         break
#                 elif ai_res.status_code in [429, 503]:
#                     sleep_time = (2 ** attempt) + random.uniform(0.5, 1.5)
#                     print(f"Gemini API rate limited/overloaded. Retrying in {sleep_time:.2f}s...")
#                     time.sleep(sleep_time)
#                 else:
#                     log_http_error(gemini_url, ai_res.status_code)
#                     break
#             except Exception as e:
#                 print(f"Exception while querying {model}: {e}")
#                 break

#     # Fallback to Groq openai/gpt-oss-120b if Gemini fails or produces syntax errors
#     if not clean_code:
#         print("Gemini models failed or produced syntax errors. Falling back to Groq gpt-oss-120b...")
#         clean_code = query_groq_hard_problem(prompt)

#     if not clean_code:
#         err = "All AI models failed to generate valid code."
#         print(err)
#         send_telegram(f"❌ *Codeforces Bot Failed*\n`{err}`")
#         sys.exit(1)

#     return clean_code


# # ============================================================================
# # 7. PROBLEM ACQUISITION & CSRF SCRAPING
# # ============================================================================
# def get_random_unsolved_problem(handle: str):
#     """
#     Query Codeforces API to get master problem list and user submission history.
#     Filter and pick one random unsolved problem with rating between 800 and 1200.
#     """
#     print("Fetching Codeforces master problemset list...")
#     master_url = "https://codeforces.com/api/problemset.problems"
#     master_res = requests.get(master_url, timeout=30)
#     if master_res.status_code != 200:
#         log_http_error(master_url, master_res.status_code, "Failed to fetch master problem list")
#         raise RuntimeError(f"Failed to fetch master problemset: HTTP {master_res.status_code}")

#     master_data = master_res.json()
#     if master_data.get("status") != "OK":
#         raise RuntimeError(f"Codeforces API error: {master_data.get('comment')}")

#     all_problems = master_data.get("result", {}).get("problems", [])

#     print(f"Fetching solved problems for user {handle}...")
#     user_status_url = f"https://codeforces.com/api/user.status?handle={handle}"
#     status_res = requests.get(user_status_url, timeout=30)
#     if status_res.status_code != 200:
#         log_http_error(user_status_url, status_res.status_code, "Failed to fetch user submissions")
#         raise RuntimeError(f"Failed to fetch user submissions: HTTP {status_res.status_code}")

#     status_data = status_res.json()
#     if status_data.get("status") != "OK":
#         raise RuntimeError(f"Codeforces API error: {status_data.get('comment')}")

#     submissions = status_data.get("result", [])

#     solved_set = set()
#     for sub in submissions:
#         if sub.get("verdict") == "OK":
#             prob = sub.get("problem", {})
#             c_id = prob.get("contestId")
#             idx = prob.get("index")
#             if c_id is not None and idx is not None:
#                 solved_set.add((c_id, str(idx).strip().upper()))

#     # Filter: rating between 800 and 1200, unsolved, valid contestId and index
#     eligible_problems = []
#     for p in all_problems:
#         c_id = p.get("contestId")
#         idx = p.get("index")
#         rating = p.get("rating")
#         if c_id is None or idx is None:
#             continue
#         idx_str = str(idx).strip().upper()
#         if rating is not None and 800 <= rating <= 1200:
#             if (c_id, idx_str) not in solved_set:
#                 eligible_problems.append(p)

#     if not eligible_problems:
#         print("No unsolved problems found with rating between 800 and 1200.")
#         return None

#     chosen = random.choice(eligible_problems)
#     return chosen


# def fetch_problem_page_and_csrf(contest_id: int, problem_index: str, session_cookie: str):
#     """
#     GET the specific problem page using curl_cffi and parse HTML.
#     Locates and extracts the mandatory CSRF token from <meta name="X-Csrf-Token" content="..." />
#     Also extracts problem statement text for AI generation.
#     """
#     problem_url = f"https://codeforces.com/problemset/problem/{contest_id}/{problem_index}"
#     print(f"Fetching problem page from {problem_url}...")

#     headers = {
#         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
#         "Cookie": f"JSESSIONID={session_cookie};",
#     }
#     cookies = {"JSESSIONID": session_cookie}

#     res = cf_requests.get(problem_url, headers=headers, cookies=cookies, impersonate="chrome", timeout=20)
#     if res.status_code != 200:
#         log_http_error(problem_url, res.status_code, "Failed to fetch problem page")
#         raise RuntimeError(f"Failed to fetch problem page: HTTP {res.status_code}")

#     soup = BeautifulSoup(res.text, "html.parser")

#     # Locate the mandatory <meta name="X-Csrf-Token" content="..." /> tag
#     csrf_meta = soup.find("meta", attrs={"name": "X-Csrf-Token"})
#     csrf_token = None
#     if csrf_meta and csrf_meta.get("content"):
#         csrf_token = csrf_meta["content"].strip()
#     else:
#         # Fallback search if tag has different casing or in span
#         meta_fallback = soup.find("meta", attrs={"name": re.compile(r"^X-Csrf-Token$", re.I)})
#         if meta_fallback and meta_fallback.get("content"):
#             csrf_token = meta_fallback["content"].strip()
#         else:
#             span_csrf = soup.find("span", class_="csrf-token")
#             if span_csrf and span_csrf.get("data-csrf"):
#                 csrf_token = span_csrf["data-csrf"].strip()

#     if not csrf_token:
#         raise ValueError("Could not extract mandatory X-Csrf-Token from Codeforces problem page.")

#     # Extract problem statement content
#     statement_div = soup.find("div", class_="problem-statement")
#     if statement_div:
#         problem_text = statement_div.get_text(separator="\n", strip=True)
#     else:
#         problem_text = soup.get_text(separator="\n", strip=True)

#     return csrf_token, problem_text, problem_url


# # ============================================================================
# # MAIN EXECUTION STARTS HERE
# # ============================================================================
# if __name__ == "__main__":
#     # 1. Environment & Pre-Flight (Fail Fast)
#     try:
#         verify_environment()
#         verify_codeforces_session()
#     except (ValueError, EnvironmentError) as e:
#         print(str(e))
#         sys.exit(1)

#     CODEFORCES_HANDLE = os.getenv("CODEFORCES_HANDLE", "").strip()
#     CODEFORCES_SESSION_COOKIE = os.getenv("CODEFORCES_SESSION_COOKIE", "").strip()

#     # 2. Problem Acquisition (Via Official API)
#     try:
#         chosen_problem = get_random_unsolved_problem(CODEFORCES_HANDLE)
#         if not chosen_problem:
#             print("No suitable unsolved problem found. Exiting gracefully.")
#             sys.exit(0)
#     except Exception as e:
#         err = f"Failed to acquire problem: {e}"
#         print(err)
#         send_telegram(f"❌ *Codeforces Bot Failed*\n`{err}`")
#         sys.exit(1)

#     contest_id = chosen_problem["contestId"]
#     problem_index = str(chosen_problem["index"]).strip().upper()
#     problem_id = f"{contest_id}{problem_index}"
#     title = chosen_problem.get("name", "Unknown Title")
#     rating = chosen_problem.get("rating", "Unrated")
#     safe_title = re.sub(r'[*_`\[\]]', '', title)

#     print(f"Problem Found: #{problem_id} - {safe_title}")
#     print(f"Difficulty Rating: {rating}")

#     # 3. Dynamic CSRF Scraping & Statement Extraction
#     try:
#         csrf_token, problem_text, problem_url = fetch_problem_page_and_csrf(
#             contest_id, problem_index, CODEFORCES_SESSION_COOKIE
#         )
#         print("✓ Dynamic CSRF token extracted successfully.")
#     except Exception as e:
#         err = f"CSRF scraping error: {e}"
#         print(err)
#         send_telegram(f"❌ *Codeforces Bot Failed*\n`{err}`")
#         sys.exit(1)

#     # 4. AI Generation & Fallback Pipeline
#     print("Generating solution via AI pipeline...")
#     prompt = f"""
# You are an expert competitive programmer. Solve this Codeforces problem in Python 3.
# CRITICAL REQUIREMENTS:
# 1. Standard Input/Output: Read ALL input directly from standard input using sys.stdin.read().split() or input().
# 2. Write ALL output directly to standard output using sys.stdout.write() or print().
# 3. Do NOT use interactive prompts like input("Enter n: ").
# 4. Do NOT wrap code in LeetCode-style classes or methods. Output clean, runnable Python 3 code with optimal time and space complexity.
# 5. Return ONLY raw, executable Python 3 code. Do not include markdown code fences (no ```), explanations, or notes.

# Problem: #{problem_id} - {title}
# Difficulty Rating: {rating}

# Problem Statement:
# {problem_text}
# """

#     clean_code = generate_solution_with_fallback(prompt)

#     # 5. Cloudflare-Evasion Submission
#     print("Submitting solution to Codeforces via curl_cffi...")
#     submit_url = "https://codeforces.com/problemset/submit"
#     submit_headers = {
#         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
#         "Referer": problem_url,
#         "Origin": "https://codeforces.com",
#         "Cookie": f"JSESSIONID={CODEFORCES_SESSION_COOKIE};",
#     }
#     submit_cookies = {"JSESSIONID": CODEFORCES_SESSION_COOKIE}

#     submit_payload = {
#         "csrf_token": csrf_token,
#         "action": "submitSolutionForm",
#         "submittedProblemIndex": problem_index,
#         "submittedProblemCode": f"{contest_id}{problem_index}",
#         "programTypeId": "73",  # Python 3.8+
#         "source": clean_code,
#         "tabSize": "4",
#         "sourceFile": "",
#     }

#     try:
#         sub_res = cf_requests.post(
#             submit_url,
#             data=submit_payload,
#             headers=submit_headers,
#             cookies=submit_cookies,
#             impersonate="chrome",
#             timeout=30,
#         )

#         if sub_res.status_code not in (200, 302):
#             log_http_error(submit_url, sub_res.status_code, "Submission failed")
#             send_telegram(f"❌ *Codeforces Submission Failed*\nHTTP {sub_res.status_code}")
#             sys.exit(1)

#         # Check for potential submission error messages in HTML response
#         if "error for__source" in sub_res.text or "You have submitted exactly the same code before" in sub_res.text:
#             err_msg = "Codeforces rejected submission (duplicate code or syntax/source error)."
#             print(err_msg)
#             send_telegram(f"❌ *Codeforces Submission Rejected*\n`{err_msg}`")
#             sys.exit(1)

#         print("✓ Solution submitted successfully. Waiting for verdict...")

#     except Exception as e:
#         print(f"Exception during submission: {e}")
#         send_telegram(f"❌ *Codeforces Submission Failed*\n`{str(e)}`")
#         sys.exit(1)

#     # 6. Verdict Polling & Notification
#     print(f"Polling for verdict on #{problem_id} (up to 60 attempts, every 5s)...")
#     poll_url = f"https://codeforces.com/api/user.status?handle={CODEFORCES_HANDLE}&from=1&count=1"

#     for attempt in range(60): # 5 minutes of polling tolerance
#         time.sleep(5)
#         try:
#             status_res = requests.get(poll_url, timeout=15)
#             if status_res.status_code != 200:
#                 print(f"Polling attempt {attempt + 1}: HTTP {status_res.status_code}. Retrying...")
#                 continue

#             try:
#                 data = status_res.json()
#             except Exception:
#                 print("Cloudflare challenge received. Retrying...")
#                 continue

#             if data.get("status") != "OK":
#                 print(f"Codeforces API comment: {data.get('comment')}")
#                 continue

#             submissions = data.get("result", [])
#             if not submissions:
#                 print(f"Polling attempt {attempt + 1}: empty submissions list. Retrying...")
#                 continue

#             latest_sub = submissions[0]

#             # CACHE BYPASS: verify that str(latest_sub['problem']['contestId']) + latest_sub['problem']['index'] matches the target problem
#             try:
#                 sub_problem_id = str(latest_sub['problem']['contestId']) + str(latest_sub['problem']['index'])
#             except (KeyError, TypeError):
#                 print("API cache lag. Retrying...")
#                 continue

#             if sub_problem_id.upper() != problem_id.upper():
#                 print("API cache lag. Retrying...")
#                 continue

#             verdict = latest_sub.get("verdict")
#             if verdict is None or verdict == "TESTING":
#                 print(f"Polling attempt {attempt + 1}/60... State: TESTING")
#                 continue

#             print(f"Verdict: {verdict}")
#             if verdict == "OK":
#                 runtime_ms = latest_sub.get("timeConsumedMillis", "N/A")
#                 runtime = f"{runtime_ms} ms" if runtime_ms != "N/A" else "N/A"
#                 memory_bytes = latest_sub.get("memoryConsumedBytes")
#                 memory = f"{round(memory_bytes / 1024)} KB" if memory_bytes is not None else "N/A"

#                 send_telegram(
#                     f"✅ *Codeforces Solved!*\n\n"
#                     f"📌 *Problem:* #{problem_id} - {safe_title}\n"
#                     f"⏱ *Runtime:* `{runtime}`\n"
#                     f"💾 *Memory:* `{memory}`\n"
#                     f"📊 *Difficulty Rating:* {rating}\n"
#                     f"🔗 [View Problem]({problem_url})"
#                 )

#                 # Save successful code locally to Codeforces-{ID} directory for GitHub sync
#                 folder_name = f"Codeforces-{problem_id}"
#                 os.makedirs(folder_name, exist_ok=True)
#                 with open(f"{folder_name}/{problem_id}.py", "w", encoding="utf-8") as f:
#                     f.write(clean_code)
#                 with open(f"{folder_name}/README.md", "w", encoding="utf-8") as f:
#                     f.write(
#                         f"# Codeforces #{problem_id} - {safe_title}\n\n"
#                         f"- **Difficulty Rating:** {rating}\n"
#                         f"- **Problem URL:** {problem_url}\n"
#                         f"- **Runtime:** {runtime}\n"
#                         f"- **Memory:** {memory}\n\n"
#                         f"## Solution\n\n"
#                         f"```python\n{clean_code}\n```\n"
#                     )

#                 print(f"Success! Code saved locally to {folder_name}.")
#                 break
#             else:
#                 fail_reason = verdict
#                 send_telegram(f"❌ *Codeforces Not Accepted*\nProblem: #{problem_id} - {safe_title}\nVerdict: `{fail_reason}`")
#                 sys.exit(1)

#         except Exception as e:
#             print(f"Error checking status on attempt {attempt + 1}: {e}")
#     else:
#         print("Submission timed out.")
#         send_telegram("❌ *Codeforces Bot Timed Out*\nSubmission took over 5 minutes.")
#         sys.exit(1)
