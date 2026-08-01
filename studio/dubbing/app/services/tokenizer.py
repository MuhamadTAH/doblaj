import re

def normalize_text(text: str) -> str:
    """
    Normalizes text by removing diacritics (tashkeel), zero-width characters,
    and standardizing spaces. Essential for consistent Arabic/Kurdish tokenization.
    """
    if not text:
        return ""
    
    # Arabic Diacritics (Tashkeel)
    tashkeel = re.compile(r'[\u0617-\u061A\u064B-\u0652\u06D6-\u06DC\u06DF-\u06E8\u06EA-\u06ED]')
    text = re.sub(tashkeel, '', text)
    
    # Remove zero-width spaces/joiners
    text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)
    
    # Standardize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def count_words(text: str) -> int:
    """
    Deterministic word count. Uses basic space delimiting after normalization.
    Since Arabic and Kurdish Sorani use attached clitics (e.g. "والكتاب"), this treats 
    the clitic+word as a single token, which is the baseline mathematical assumption for WPS.
    """
    normalized = normalize_text(text)
    if not normalized:
        return 0
    return len(normalized.split(' '))

def count_syllables_approx(text: str) -> int:
    """
    A rough heuristic for syllable counting in Arabic/Kurdish.
    Typically, the number of vowels/long vowels roughly correlates with syllables.
    For more precise ML constraints, actual phonetic g2p might be needed,
    but this provides a baseline diagnostic metric.
    """
    normalized = normalize_text(text)
    # Very crude approximation: count words + long vowels
    # Arabic long vowels: Alif, Waw, Yaa
    long_vowels = len(re.findall(r'[اوي]', normalized))
    words = count_words(normalized)
    
    # A standard Arabic word has ~2.5 syllables. This is a naive fallback.
    return max(words, long_vowels + (words // 2))
