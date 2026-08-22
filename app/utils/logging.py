"""Local, rotating application logging.

Mediary logs to a file so users can diagnose failed downloads, but it never
records credentials, cookies or authentication tokens. Anything that could
carry a secret is redacted before it reaches a handler.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys

from app.utils.paths import logs_dir

LOGGER_NAME = "mediary"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 5

#: Patterns scrubbed from every log record. Keeping this at the handler level
#: means a careless ``logger.debug(payload)`` anywhere still cannot leak.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Header-style secrets run to the end of the line: "Bearer <token>" is two
    # whitespace-separated words, so consuming a single \S+ would leave the
    # token itself behind.
    (re.compile(r"(?i)\b(cookie|set-cookie)\b\s*[:=].*$", re.M), r"\1: [redacted]"),
    (re.compile(r"(?i)\b(authorization|proxy-authorization)\b\s*[:=].*$", re.M),
     r"\1: [redacted]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+\S+"), r"\1 [redacted]"),
    (re.compile(r"(?i)\b(auth[-_]?token)\b\s*[:=]?\s*\S+"), r"\1 [redacted]"),
    (re.compile(
        r"(?i)\b(password|passwd|pwd|secret|api[-_]?key|"
        r"(?:access[-_]?|refresh[-_]?|auth[-_]?|bearer[-_]?|session[-_]?|csrf[-_]?)?token|"
        r"client[-_]?secret|private[-_]?key)\b\s*[:=]\s*\S+"
    ), r"\1=[redacted]"),
    (re.compile(r"(?i)([?&](?:token|key|signature|sig|auth|password)=)[^&\s]+"), r"\1[redacted]"),
    (re.compile(r"(?i)\bhttps?://[^\s/@]+:[^\s/@]+@"), "https://[redacted]@"),
)


class RedactingFilter(logging.Filter):
    """Strip credential-shaped text out of a record before it is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            return True
        cleaned = message
        for pattern, replacement in _REDACTIONS:
            cleaned = pattern.sub(replacement, cleaned)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


_configured = False


def configure_logging(level: int = logging.INFO, *, to_stderr: bool = True) -> logging.Logger:
    """Install the file + console handlers. Safe to call more than once."""
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    redactor = RedactingFilter()

    directory = logs_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            directory / "mediary.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-7s  %(name)-28s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        file_handler.addFilter(redactor)
        logger.addHandler(file_handler)
    except OSError:
        # A read-only or unavailable log directory must never stop the app.
        pass

    if to_stderr:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(level)
        console.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
        console.addFilter(redactor)
        logger.addHandler(console)

    _configured = True
    return logger


def get_logger(name: str = "") -> logging.Logger:
    """Return a namespaced child of the Mediary logger."""
    if not name:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def redact(text: str) -> str:
    """Apply the log redaction rules to an arbitrary string."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text
