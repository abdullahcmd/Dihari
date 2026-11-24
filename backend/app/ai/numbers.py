"""Number / token helpers shared by extraction grounding, mock LLM and answer parsing. Lexicons come from locale files."""
import re

from .. import i18n

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
LANGS = ("ur", "en")


def norm(text: str) -> str:
    return (text or "").translate(_DIGITS).replace("،", " ").replace("۔", " ").lower()


def lex(name: str, lang: str):
    return i18n.lexicon(name, lang)


def tokenize(text: str, lang: str = "ur") -> list[str]:
    t = norm(text)
    t = re.sub(r"(\d),(\d{3})", r"\1\2", t)
    return re.findall(r"\d+(?:\.\d+)?|[^\W\d_]+(?:['.][^\W\d_]+)*", t, flags=re.UNICODE)


def _word_value(tok: str, lang: str):
    nums = i18n.lexicon("numbers", lang)
    for l in {lang, "ur", "en"}:
        n = i18n.lexicon("numbers", l)
        if tok in n:
            return n[tok]
    return None


def number_spans(tokens: list[str], lang: str = "ur") -> list[tuple[float, int, int]]:
    """[(value, start_idx, end_idx)] merging 'ٹپندرہ سو'→1500, '2 hazar'→2000, 'ڈیڑھ ہزار'→1500."""
    fr = {}
    for l in {lang, "ur", "en"}:
        fr.update(i18n.lexicon("fractions", l) or {})
    vals: list[tuple[float, int] | None] = []
    for i, tk in enumerate(tokens):
        if re.fullmatch(r"\d+(?:\.\d+)?", tk):
            v = float(tk)
            vals.append((v, i))
        elif tk in fr:
            vals.append((fr[tk], i))
        else:
            w = _word_value(tk, lang)
            vals.append((float(w), i) if w is not None else None)
    spans = []
    i = 0
    while i < len(vals):
        if vals[i] is None:
            i += 1
            continue
        cur, start, end = vals[i][0], i, i
        i += 1
        while i < len(vals) and vals[i] is not None and vals[i][0] in (100, 1000) and cur < vals[i][0]:
            cur *= vals[i][0]; end = i; i += 1
        # a bare multiplier word alone ("hazar") is not a number on its own
        if not (end == start and cur in (100, 1000) and not re.fullmatch(r"\d+", tokens[start])):
            spans.append((cur, start, end))
    return spans


def numbers_in(text: str, lang: str = "ur") -> set[float]:
    return {v for v, _, _ in number_spans(tokenize(text, lang), lang)}


def has_time_cue(text: str, lang: str = "ur") -> bool:
    toks = tokenize(text, lang)
    cues = set()
    for l in {lang, *LANGS}:
        cues |= {w.lower() for k in ("today", "tomorrow", "time_words", "am_words", "pm_words", "same_day") for w in lex(k, l)}
        cues |= set(i18n.lexicon("weekdays", l))
    s = " ".join(toks)
    return any(t in cues for t in toks) or any(c in s for c in cues if " " in c) or bool(re.search(r"\d{1,2}[/-]\d{1,2}", norm(text)))


def yes_no(text: str, lang: str = "ur") -> str:
    toks = set(tokenize(text, lang))
    s = norm(text)
    yes = {w.lower() for l in {lang, *LANGS} for w in lex("yes", l)}
    no = {w.lower() for l in {lang, *LANGS} for w in lex("no", l)}
    is_no = bool(toks & no) or any(" " in w and w in s for w in no)
    is_yes = bool(toks & yes) or any(" " in w and w in s for w in yes)
    if is_no and not is_yes:
        return "no"
    if is_yes and not is_no:
        return "yes"
    return "unknown"
