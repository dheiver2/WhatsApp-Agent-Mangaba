import math
import re
import unicodedata
from collections import Counter

TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")
STOPWORDS = {
    "a", "agora", "ai", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
    "e", "ela", "ele", "em", "entre", "era", "essa", "esse", "esta", "este", "eu", "foi",
    "ja", "la", "mais", "mas", "me", "meu", "minha", "muito", "na", "nas", "no", "nos",
    "o", "oi", "ola", "os", "ou", "para", "por", "pra", "que", "se", "sem", "ser", "seu",
    "sua", "tambem", "te", "tem", "tenho", "um", "uma", "voce", "voces",
}


def normalize_text(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _char_ngrams(token: str, size: int = 4) -> list[str]:
    if len(token) < size + 1:
        return []
    return [f"g:{token[i:i + size]}" for i in range(len(token) - size + 1)]


def tokenize_text(text: str) -> list[str]:
    normalized = normalize_text(text)
    base_tokens = [token for token in TOKEN_PATTERN.findall(normalized) if token not in STOPWORDS]
    expanded_tokens = []
    for token in base_tokens:
        expanded_tokens.append(token)
        expanded_tokens.extend(_char_ngrams(token))
    return expanded_tokens


def build_idf_map(token_lists: list[list[str]]) -> dict[str, float]:
    document_count = max(len(token_lists), 1)
    doc_frequency = Counter()
    for tokens in token_lists:
        doc_frequency.update(set(tokens))
    return {
        token: math.log((1 + document_count) / (1 + frequency)) + 1.0
        for token, frequency in doc_frequency.items()
    }


def build_weighted_vector(tokens: list[str], idf_map: dict[str, float]) -> dict[str, float]:
    counts = Counter(tokens)
    return {
        token: (1.0 + math.log(count)) * idf_map.get(token, 1.0)
        for token, count in counts.items()
    }


def vector_norm(vector: dict[str, float]) -> float:
    norm = math.sqrt(sum(value * value for value in vector.values()))
    return norm or 1.0


def cosine_similarity(
    left: dict[str, float],
    right: dict[str, float],
    left_norm: float | None = None,
    right_norm: float | None = None,
) -> float:
    if not left or not right:
        return 0.0

    if len(left) > len(right):
        left, right = right, left
        left_norm, right_norm = right_norm, left_norm

    numerator = sum(value * right.get(token, 0.0) for token, value in left.items())
    return numerator / ((left_norm or vector_norm(left)) * (right_norm or vector_norm(right)))


def overlap_ratio(left_tokens: list[str], right_tokens: list[str]) -> float:
    left_set = set(left_tokens)
    right_set = set(right_tokens)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)
