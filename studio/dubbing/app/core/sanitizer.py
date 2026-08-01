import re
from typing import Optional

# Strip out markdown code block syntax, XML/HTML-like tags that could be used for prompt injection
# e.g., <system>, <user>, ```json, [INST], etc.
_PROMPT_INJECTION_RE = re.compile(
    r"(?:<[A-Za-z0-9_/\-]+>|\[/?(?:INST|SYS)\]|```(?:json|markdown)?)",
    re.IGNORECASE
)

def sanitize_transcript(text: Optional[str]) -> str:
    """
    Sanitize text to prevent downstream prompt injection and XSS.
    Strips XML tags, markdown block syntax, and LLM special tokens.
    """
    if not text:
        return ""
        
    # Replace common prompt injection tags and delimiters
    safe_text = _PROMPT_INJECTION_RE.sub(" ", text)
    
    # Escape remaining angle brackets to prevent generic HTML/XSS on render
    safe_text = safe_text.replace("<", "&lt;").replace(">", "&gt;")
    
    # Strip leading/trailing whitespace
    return safe_text.strip()
