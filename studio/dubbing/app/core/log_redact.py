"""PIRD-025: workspace_id redaction for logs."""
import hashlib


def safe_ws(workspace_id: str) -> str:
    """Return a redacted-but-stable representation of workspace_id for
    inclusion in log lines. First 8 chars of the id, an ellipsis, and a
    6-char SHA-256 suffix. Two callers with the same workspace see the
    same redacted form; an attacker reading logs can't recover the id."""
    if not workspace_id:
        return ""
    prefix = workspace_id[:8]
    suffix = hashlib.sha256(workspace_id.encode()).hexdigest()[:6]
    return f"{prefix}…{suffix}"
