import re
from unidecode import unidecode
from rapidfuzz import fuzz


def normalize_name(s: str) -> str:
    """
    Lowercase, keep letters/digits/space/'/-, collapse spaces.
    Unidecode for accents.
    """
    s = unidecode(s or "").lower()
    s = re.sub(r"[^a-z0-9\s'-]+", " ", s)
    return " ".join(s.split())


def name_similarity(a: str, b: str) -> float:
    """Compute name similarity between two names."""
    a, b = normalize_name(a), normalize_name(b)
    return float(fuzz.token_sort_ratio(a, b))


def is_exact_name(a: str, b: str) -> bool:
    """
    Exact equality after normalization.
    """
    return normalize_name(a) == normalize_name(b)


def cli():
    import argparse

    ap = argparse.ArgumentParser(description="Name matcher quick test")
    ap.add_argument("a", help="First name string")
    ap.add_argument("b", help="Second name string")
    args = ap.parse_args()

    sim = name_similarity(args.a, args.b)
    exact = is_exact_name(args.a, args.b)

    print(f"similarity: {sim}")
    print(f"exact: {exact}")


if __name__ == "__main__":
    cli()