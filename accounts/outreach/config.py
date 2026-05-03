"""Outreach configuration, scoring, and API helpers."""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

# Target candidates per harvest run. Stays well within GitHub's 5000/hr limit:
# each candidate uses ~2 API calls (profile + repos), so 500 ≈ 1000 calls.
BATCH       = 500

GITHUB_API  = "https://api.github.com"
RESEND_API  = "https://api.resend.com/emails"
SUBJECT     = "Your project deserves users — not a bigger budget"

# Web-focused languages. Targets JS/TS (frontend), Go (backend services).
WEB_LANGUAGES   = ["javascript", "typescript", "go"]
# Broader language pool for less web-focused projects
OTHER_LANGUAGES = ["python", "rust", "c++"]
LANGUAGES       = WEB_LANGUAGES + OTHER_LANGUAGES

SEARCH_BASE = "type:user followers:0..500 repos:3..100"


def score_user(profile: dict, repos: list) -> int:
	"""Score a candidate. Higher = better target (small/active builders)."""
	promoted   = sum(1 for r in repos if r.get("homepage"))
	followers  = profile.get("followers", 0) or 0
	total_stars = sum(r.get("stargazers_count", 0) or 0 for r in repos)

	# Weighted: more promoted projects = higher; small projects favored
	score  = promoted * 20
	score += min(followers, 100) // 5         # cap follower bonus at 20
	score -= max(total_stars - 50, 0) // 10   # penalize already-popular accts
	return score


def gh_headers() -> dict:
	"""Build GitHub API headers."""
	return {
		"Authorization":        f"Bearer {settings.GITHUB_TOKEN}",
		"Accept":               "application/vnd.github+json",
		"X-GitHub-Api-Version": "2022-11-28",
	}


def gh_get(url: str):
	"""Fetch JSON from GitHub API."""
	req = urllib.request.Request(url, headers=gh_headers())
	try:
		with urllib.request.urlopen(req, timeout=15) as resp:
			return json.loads(resp.read())
	except urllib.error.URLError as exc:
		logger.error("GitHub API error %s: %s", url, exc)
		return None


def resend_post(payload: dict) -> bool:
	"""Send email via Resend API."""
	req = urllib.request.Request(
		RESEND_API,
		data=json.dumps(payload).encode(),
		headers={
			"Authorization": f"Bearer {settings.RESEND_API_KEY}",
			"Content-Type":  "application/json",
		},
		method="POST",
	)
	try:
		with urllib.request.urlopen(req, timeout=15) as resp:
			return resp.status in (200, 201)
	except urllib.error.HTTPError as exc:
		body = exc.read().decode(errors="replace")
		print(f"Resend error {exc.code}: {body}")
		logger.error("Resend error %s: %s", exc.code, body)
		return False
	except urllib.error.URLError as exc:
		print(f"Resend connection error: {exc.reason}")
		logger.error("Resend connection error: %s", exc.reason)
		return False