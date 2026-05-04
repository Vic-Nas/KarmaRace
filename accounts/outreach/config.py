# accounts/outreach/config.py
"""Outreach configuration, scoring, and API helpers."""
import base64
import json
import logging
import time
import urllib.error
import urllib.request

from django.conf import settings
from github import Github, GithubException

logger = logging.getLogger(__name__)

# Target candidates per harvest run. Stays well within GitHub's 5000/hr limit:
# each candidate uses ~2 API calls (profile + repos), so 1200 ≈ 2400 calls.
BATCH       = 1200

GITHUB_API  = "https://api.github.com"
SUBJECT     = "Your project deserves users, not a bigger budget"

SENDPULSE_TOKEN_URL = 'https://api.sendpulse.com/oauth/access_token'
SENDPULSE_SMTP_URL  = 'https://api.sendpulse.com/smtp/emails'

# Web-focused languages. Targets JS/TS (frontend), Go (backend services).
WEB_LANGUAGES   = ["javascript", "typescript", "go"]
# Broader language pool for less web-focused projects
OTHER_LANGUAGES = ["python", "rust", "c++"]
LANGUAGES       = WEB_LANGUAGES + OTHER_LANGUAGES

SEARCH_BASE = "type:user followers:0..500 repos:3..100"

# Module-level token cache: {'token': str, 'expires_at': float}
_sendpulse_token_cache: dict = {}


def _repo_attr(repo, name, default=None):
	if isinstance(repo, dict):
		return repo.get(name, default)
	return getattr(repo, name, default)


def score_user(profile: dict, repos: list) -> int:
	"""Score a candidate. Higher = better target (small/active builders)."""
	promoted = sum(1 for r in repos if _repo_attr(r, "homepage"))
	followers = profile.get("followers", 0) or 0
	total_stars = sum(_repo_attr(r, "stargazers_count", 0) or 0 for r in repos)

	# Weighted: more promoted projects = higher; small projects favored
	score  = promoted * 20
	score += min(followers, 100) // 5         # cap follower bonus at 20
	score -= max(total_stars - 50, 0) // 10   # penalize already-popular accts
	return score


def iter_candidates(query: str, max_candidates: int, max_repos: int = 100):
	"""Yield (profile, repos) for GitHub users matching the query."""
	try:
		gh = Github(settings.GITHUB_TOKEN)
		for idx, user in enumerate(gh.search_users(query)):
			if idx >= max_candidates:
				break
			username = (getattr(user, 'login', '') or '').strip()
			if not username:
				continue
			try:
				full_user = gh.get_user(username)
				profile = full_user.raw_data or {}
				repos = []
				for r_idx, repo in enumerate(full_user.get_repos()):
					if r_idx >= max_repos:
						break
					repos.append(repo)
				yield profile, repos
			except GithubException as exc:
				logger.error("GitHub user error %s: %s", username, exc)
				continue
	except GithubException as exc:
		logger.error("GitHub search error %s: %s", query, exc)
		return


def get_sendpulse_token() -> str:
	"""Return a valid SendPulse bearer token, fetching a new one if needed."""
	now = time.time()
	if _sendpulse_token_cache.get('token') and now < _sendpulse_token_cache.get('expires_at', 0):
		return _sendpulse_token_cache['token']

	payload = json.dumps({
		'grant_type':    'client_credentials',
		'client_id':     settings.SENDPULSE_API_ID,
		'client_secret': settings.SENDPULSE_API_SECRET,
	}).encode()

	req = urllib.request.Request(
		SENDPULSE_TOKEN_URL,
		data=payload,
		headers={'Content-Type': 'application/json'},
		method='POST',
	)
	with urllib.request.urlopen(req, timeout=15) as resp:
		data = json.loads(resp.read())

	token = data['access_token']
	expires_in = data.get('expires_in', 3600)
	_sendpulse_token_cache['token'] = token
	_sendpulse_token_cache['expires_at'] = now + expires_in - 60  # 60s buffer

	return token


def sendpulse_post(payload: dict) -> bool:
	"""Send email via SendPulse SMTP API. Returns True when result:true in body."""
	try:
		token = get_sendpulse_token()
		email = payload.get('email', {})
		logger.info("sendpulse_post: from=%r to=%r", email.get('from'), email.get('to'))
		if 'html' in email:
			email['html'] = base64.b64encode(email['html'].encode()).decode()
		body = json.dumps(payload).encode()
		req = urllib.request.Request(
			SENDPULSE_SMTP_URL,
			data=body,
			headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'},
			method='POST',
		)
		with urllib.request.urlopen(req, timeout=15) as resp:
			data = json.loads(resp.read())
		return bool(data.get('result'))
	except urllib.error.HTTPError as exc:
		logger.error("SendPulse HTTP %s: %s", exc.code, exc.read())
		return False
	except Exception as exc:
		logger.error("SendPulse error: %s", exc)
		return False


def update_daily_stats(date, harvested=None, queued_count=None, sent_count=None,
				   failed_count=None, pending_after=None):
	from accounts.models import OutreachDailyStats
	stats, _ = OutreachDailyStats.objects.get_or_create(date=date)
	update_fields = []
	if harvested is not None:
		stats.harvested = harvested
		update_fields.append("harvested")
	if queued_count is not None:
		stats.queued_count = queued_count
		update_fields.append("queued_count")
	if sent_count is not None:
		stats.sent_count = sent_count
		update_fields.append("sent_count")
	if failed_count is not None:
		stats.failed_count = failed_count
		update_fields.append("failed_count")
	if pending_after is not None:
		stats.pending_after = pending_after
		update_fields.append("pending_after")
	if update_fields:
		update_fields.append("updated_at")
		stats.save(update_fields=update_fields)