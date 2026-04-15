# /karma/models.py
from django.db import models
from django.conf import settings

class KarmaConfig(models.Model):
	"""
	Stores tunable karma system parameters (e.g., base_cost).
	key: unique name for the config (CharField, unique)
	value: decimal value for the config
	"""
	key = models.CharField(max_length=64, unique=True, help_text="Config key name (e.g., base_cost)")
	value = models.DecimalField(max_digits=12, decimal_places=4, help_text="Config value")

	def __str__(self):
		return f"{self.key}: {self.value}"

class KarmaTransaction(models.Model):
	"""
	Records all karma movements for users.
	user: ForeignKey to AUTH_USER_MODEL
	delta: DecimalField (positive or negative)
	reason: TextChoices for transaction reason
	created_at: auto timestamp
	"""
	class Reason(models.TextChoices):
		EARN = "EARN", "Earned"
		SPEND = "SPEND", "Spent"
		SYSTEM = "SYSTEM", "System Reward"
		TASK_REWARD = "TASK_REWARD", "Task Reward"
		TASK_COST = "TASK_COST", "Task Cost"
		FLAGUP = "FLAGUP", "Flag-Up"

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="karma_transactions")
	delta = models.DecimalField(max_digits=12, decimal_places=4, help_text="Karma change (+/-)")
	reason = models.CharField(max_length=32, choices=Reason.choices)
	created_at = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return f"{self.user} {self.delta} ({self.reason}) @ {self.created_at}"
