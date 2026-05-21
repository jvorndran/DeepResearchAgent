"""Shared semantic aliases for current-scalar fact matching."""

from __future__ import annotations


CURRENT_SCALAR_TOKEN_ALIASES = {
    "unrate": {"unrate", "unemployment"},
    "unemployment": {"unrate", "unemployment"},
    "payems": {"payems", "payroll", "payrolls"},
    "payroll": {"payems", "payroll", "payrolls"},
    "payrolls": {"payems", "payroll", "payrolls"},
    "civpart": {"civpart", "participation"},
    "participation": {"civpart", "participation"},
    "jtsjol": {"jtsjol", "opening", "openings"},
    "opening": {"jtsjol", "opening", "openings"},
    "openings": {"jtsjol", "opening", "openings"},
    "jtsqur": {"jtsqur", "quits"},
    "quits": {"jtsqur", "quits"},
    "icsa": {"icsa", "claims"},
    "claims": {"icsa", "claims"},
    "uempm": {"uempm", "duration"},
    "duration": {"uempm", "duration"},
    "usrec": {"usrec", "recession"},
    "recession": {"usrec", "recession"},
    "t10y2y": {"t10y2y", "yield", "curve", "treasury"},
    "yield": {"t10y2y", "yield", "curve", "treasury"},
    "curve": {"t10y2y", "yield", "curve", "treasury"},
    "cpiaucsl": {"cpiaucsl", "cpi", "inflation"},
    "cpi": {"cpiaucsl", "cpi", "inflation"},
    "inflation": {"cpiaucsl", "cpi", "inflation"},
    "pcepilfe": {"pcepilfe", "core", "pce", "inflation"},
    "core": {"pcepilfe", "core", "pce", "inflation"},
    "pce": {"pcepilfe", "core", "pce", "inflation"},
    "fedfunds": {"fedfunds", "fed", "funds", "policy"},
    "fed": {"fedfunds", "fed", "funds", "policy"},
    "funds": {"fedfunds", "fed", "funds", "policy"},
    "policy": {"fedfunds", "fed", "funds", "policy"},
}
CURRENT_SCALAR_SOURCE_KEY_TOKENS = {
    # Opaque FRED/BLS identifiers from labor-market helpers need semantic tokens;
    # the source IDs themselves do not tokenize into useful field names.
    "ces0500000003": {"ahe", "average", "hourly", "earnings", "wage", "wages"},
    "uempm": {"uempm", "unemployment", "duration", "weeks", "unemployed"},
    "uempmean": {"uempm", "unemployment", "duration", "weeks", "unemployed"},
    "lns12032195": {
        "underemployment",
        "part",
        "time",
        "economic",
        "reasons",
        "slack",
    },
}


def expand_current_scalar_aliases(tokens: set[str]) -> set[str]:
    """Return tokens plus domain aliases used by current-scalar validation."""

    expanded = set(tokens)
    for token in tuple(tokens):
        expanded.update(CURRENT_SCALAR_TOKEN_ALIASES.get(token, ()))
        expanded.update(CURRENT_SCALAR_SOURCE_KEY_TOKENS.get(token, ()))
    return expanded
