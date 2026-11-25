import re
import unicodedata

_CALENDAR = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|janvier|fevrier|mars|avril|mai|juin|"
    r"juillet|aout|septembre|octobre|novembre|decembre)\b"
)
_NUMBER = re.compile(r"\d+(?:[,.]\d+)?")
_SMALL_NUMBERS = (
    "zero", "une?", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
    "treize", "quatorze", "quinze", "seize", "dix[- ]sept", "dix[- ]huit", "dix[- ]neuf",
    "vingt", "vingt[- ]et[- ]une?", "vingt[- ]deux", "vingt[- ]trois",
)
_UNIT_NUMBER = re.compile(
    r"(?<![\w-])(?:" + "|".join(f"(?P<n{i}>{word})" for i, word in reversed(list(enumerate(_SMALL_NUMBERS))))
    + r")\s+(?P<unit>heures?|dollars?|euros?|billets?|places?|appareils?)\b"
)
_NAMED = re.compile(
    r"\b(?:[Bb]onjour|[Ss]alut|[Cc]h[èe]re?|[Hh][ôo]tel|[Gg]are|[Vv]ille de|[Aa][ée]roport de)"
    r"[ \t]+([A-ZÀ-ÖØ-Þ][^\W\d_]+(?:-[A-ZÀ-ÖØ-Þ][^\W\d_]+)?)\b"
)
_COMMON_WORDS = {"aussi", "bonjour", "comme", "cette", "encore", "faire", "merci", "parce", "passe", "pouvez", "salut"}


def _fold(text):
    return "".join(char for char in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(char))


def _facts(text):
    folded = _fold(text)
    numbers = {value.replace(",", ".") for value in _NUMBER.findall(folded)}
    for match in _UNIT_NUMBER.finditer(folded):
        number = next(i for i in range(len(_SMALL_NUMBERS)) if match[f"n{i}"] is not None)
        if number != 1 or match["unit"].startswith(("heure", "dollar", "euro")):
            numbers.add(str(number))
    return numbers | set(_CALENDAR.findall(folded))


def _names(text):
    return {_fold(name) for name in _NAMED.findall(text)}


def _words(text):
    return set(re.findall(r"\b[a-z]+(?:-[a-z]+)*\b", _fold(text)))


def faithful_rewrite(original, revised, *, reference="", reference_only=False, required_facts_from=None):
    """Keep checkable facts; EE3 synthesis may replace mistakes with source facts."""
    original_facts = _facts(original)
    reference_facts = _facts(reference)
    required = original_facts if required_facts_from is None else _facts(required_facts_from)
    if reference_only:
        required &= reference_facts
    allowed = reference_facts if reference_only else original_facts | reference_facts
    if not required <= _facts(revised) <= allowed:
        return False
    original_words, reference_words, revised_words = map(_words, (original, reference, revised))
    original_names = _names(original)
    required_names = original_names & reference_words if reference_only else original_names
    allowed_names = reference_words if reference_only else original_words | reference_words
    if not required_names <= revised_words or not _names(revised) <= allowed_names:
        return False
    terms = {word for word in original_words - _COMMON_WORDS if len(word) >= 5}
    context_terms = {word for word in reference_words - _COMMON_WORDS if len(word) >= 5}
    return len(terms) < 5 or bool((terms | context_terms) & revised_words)
