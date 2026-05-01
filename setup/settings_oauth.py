"""OAuth provider configurations."""
import environ

env = environ.Env()
environ.Env.read_env('.env')

# Google OAuth
GOOGLE_CLIENT_ID = env('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = env('GOOGLE_CLIENT_SECRET')

# GitHub OAuth
GITHUB_CLIENT_ID = env('GITHUB_CLIENT_ID', default='')
GITHUB_CLIENT_SECRET = env('GITHUB_CLIENT_SECRET', default='')

# Discord OAuth + guild sync
DISCORD_CLIENT_ID = env('DISCORD_CLIENT_ID', default='')
DISCORD_CLIENT_SECRET = env('DISCORD_CLIENT_SECRET', default='')
DISCORD_BOT_TOKEN = env('DISCORD_BOT_TOKEN', default='')
DISCORD_GUILD_ID = env('DISCORD_GUILD_ID', default='')
DISCORD_USER_ROLE_ID = env('DISCORD_USER_ROLE_ID', default='')
DISCORD_STAFF_ROLE_ID = env('DISCORD_STAFF_ROLE_ID', default='')
DISCORD_SUPERUSER_ROLE_ID = env('DISCORD_SUPERUSER_ROLE_ID', default='')

SOCIALACCOUNT_PROVIDERS = {
	'google': {
		'APP': {
			'client_id': GOOGLE_CLIENT_ID,
			'secret': GOOGLE_CLIENT_SECRET,
		},
		'SCOPE': ['profile', 'email'],
	},
	'github': {
		'APP': {
			'client_id': GITHUB_CLIENT_ID,
			'secret': GITHUB_CLIENT_SECRET,
		},
		'SCOPE': ['read:user'],
	},
	'discord': {
		'APP': {
			'client_id': DISCORD_CLIENT_ID,
			'secret': DISCORD_CLIENT_SECRET,
		},
		'SCOPE': ['identify', 'guilds.join'],
	},
}
