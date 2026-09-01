def _normalize(text):
    return " ".join(text.strip().split())

def slugify(text):
    normalized = _normalize(text).lower().replace("_", " ")
    return "-".join(part for part in normalized.split(" ") if part)

def bounded_sum(values, limit):
    return min(sum(values), limit)

def median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
