"""Small utility helpers for quality analysis."""
import json

def _truncate(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[truncated for review]"


def _parse_required_fixes(raw: str | list[str]) -> list[str]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except json.JSONDecodeError:
            return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return [str(raw)]
