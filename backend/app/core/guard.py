"""A cheap first-pass check for prompt-injection phrasing in user questions.

This is not the main defence. The real protections are structural: retrieved text is fenced
as untrusted data in the prompt, the model has no tools or secrets to leak, and every
retrieval is scoped to the user's course. This check only flags obvious attempts so they can
be refused early and seen in logs.
"""

import re

_PATTERNS = [
    r"\bignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts?|rules)",
    r"\bdisregard (all |your |the )?(previous |prior )?(instructions|guidelines|rules)",
    r"\bforget (everything|all|what) (you|you've|you were)",
    r"\b(reveal|print|show|repeat|output) (me )?(your|the) (system|hidden|initial) "
    r"(prompt|instructions)",
    r"\byou are now (a|an|in) ",
    r"\b(developer|god|jailbreak|dan) mode\b",
    r"</?(system|context)>",
]
_RE = re.compile("|".join(_PATTERNS), re.IGNORECASE)

REFUSAL = (
    "That looks like an instruction to change how I work, so I didn't run it. "
    "Ask a question about your course materials instead."
)


def looks_like_injection(text: str) -> bool:
    return _RE.search(text) is not None
