from __future__ import annotations


class CalendarBackendError(RuntimeError):
    """Domain-specific exception for calendar backend failures."""

    @classmethod
    def from_process_error(cls, returncode: int, stderr: str | None = None) -> "CalendarBackendError":
        msg = f"AppleScript process failed with code {returncode}"
        if stderr:
            msg += f": {stderr.strip()}"
        return cls(msg)

    @classmethod
    def from_parse_error(cls, raw_output: str, reason: str | None = None) -> "CalendarBackendError":
        snippet = raw_output.strip()
        if len(snippet) > 512:
            snippet = snippet[:512] + "..."
        msg = "Failed to parse AppleScript output"
        if reason:
            msg += f" ({reason})"
        msg += f": {snippet}"
        return cls(msg)
