# setup/log_filters.py
import logging


class DedupFilter(logging.Filter):
    """
    Suppress consecutive duplicate log records.

    A record is considered a duplicate when its (name, levelno, getMessage())
    triple matches the previous record that passed through this filter.
    Each handler gets its own filter instance, so the dedup state is
    per-handler, which is fine since we only attach it to 'console'.

    This collapses the N-per-worker repetition of startup warnings like
    the StreamingHttpResponse sync-iterator notice without hiding genuinely
    new occurrences that appear later during normal operation.
    """

    def __init__(self, name: str = '') -> None:
        super().__init__(name)
        self._last: tuple[str, int, str] | None = None

    def filter(self, record: logging.LogRecord) -> bool:
        key = (record.name, record.levelno, record.getMessage())
        if key == self._last:
            return False
        self._last = key
        return True