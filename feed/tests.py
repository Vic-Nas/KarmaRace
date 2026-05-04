# feed/tests.py
from django.test import TestCase
from feed.views.filtering import normalize_task_types
from tasks.models import Task


class NormalizeTaskTypesTests(TestCase):

    def test_empty_returns_all(self):
        result = normalize_task_types([])
        self.assertEqual(set(result), {Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK, Task.Type.WEBHOOK})

    def test_none_returns_all(self):
        result = normalize_task_types(None)
        self.assertEqual(set(result), {Task.Type.GITHUB_STAR, Task.Type.GITHUB_FORK, Task.Type.WEBHOOK})

    def test_valid_types_preserved(self):
        result = normalize_task_types(['GITHUB_STAR', 'WEBHOOK'])
        self.assertIn('GITHUB_STAR', result)
        self.assertIn('WEBHOOK', result)
        self.assertNotIn('GITHUB_FORK', result)

    def test_invalid_types_filtered(self):
        result = normalize_task_types(['GITHUB_STAR', 'INVALID_TYPE'])
        self.assertNotIn('INVALID_TYPE', result)

    def test_deduplication(self):
        result = normalize_task_types(['GITHUB_STAR', 'GITHUB_STAR'])
        self.assertEqual(result.count('GITHUB_STAR'), 1)

    def test_csv_string_parsed(self):
        result = normalize_task_types(['GITHUB_STAR,WEBHOOK'])
        self.assertIn('GITHUB_STAR', result)
        self.assertIn('WEBHOOK', result)
