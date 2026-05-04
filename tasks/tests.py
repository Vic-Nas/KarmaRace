# tasks/tests.py
from django.test import TestCase
from django.contrib.auth import get_user_model
from tasks.models import Task, TaskCompletion
from tasks.check_feedback import msg
from setup.platform_rules import karma_reward_for_task

User = get_user_model()


class TaskModelTests(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='x')

    def _make_task(self, task_type=Task.Type.GITHUB_STAR, target='owner/repo'):
        return Task.objects.create(
            owner=self.owner,
            type=task_type,
            description='Test task',
            target_id=target,
        )

    def test_difficulty_defaults_to_1(self):
        task = self._make_task()
        self.assertEqual(task.difficulty, 1)

    def test_difficulty_calculated_correctly(self):
        task = self._make_task()
        task.difficulty_sum = 8
        task.difficulty_count = 2
        self.assertEqual(task.difficulty, 4)

    def test_difficulty_clamped_to_5(self):
        task = self._make_task()
        task.difficulty_sum = 100
        task.difficulty_count = 5
        self.assertEqual(task.difficulty, 5)

    def test_target_url_github(self):
        task = self._make_task(Task.Type.GITHUB_STAR, 'user/repo')
        self.assertEqual(task.target_url, 'https://github.com/user/repo')

    def test_target_url_webhook(self):
        task = self._make_task(Task.Type.WEBHOOK, 'https://example.com/hook')
        self.assertEqual(task.target_url, 'https://example.com/hook')

    def test_target_url_empty_when_no_target(self):
        task = self._make_task()
        task.target_id = ''
        self.assertEqual(task.target_url, '')


class KarmaRewardTests(TestCase):

    def test_base_reward_at_zero_karma(self):
        self.assertEqual(karma_reward_for_task(0, 'GITHUB_STAR'), 5)
        self.assertEqual(karma_reward_for_task(0, 'GITHUB_FORK'), 10)
        self.assertEqual(karma_reward_for_task(0, 'WEBHOOK'), 20)

    def test_reward_increases_with_karma(self):
        low = karma_reward_for_task(10, 'WEBHOOK')
        high = karma_reward_for_task(500, 'WEBHOOK')
        self.assertGreater(high, low)

    def test_reward_capped_at_3x_base(self):
        reward = karma_reward_for_task(999999, 'WEBHOOK')
        self.assertLessEqual(reward, 60)  # 3x base of 20


class CheckFeedbackTests(TestCase):

    def test_msg_returns_text(self):
        self.assertIn('karma', msg('CHECK_CONFIRMED').lower())

    def test_msg_with_kwargs(self):
        result = msg('GITHUB_STAR_NOT_FOUND', username='testuser')
        self.assertIn('testuser', result)

    def test_msg_unknown_key_returns_key(self):
        self.assertEqual(msg('NONEXISTENT_KEY'), 'NONEXISTENT_KEY')
