def find_max(lst):
    """Return the maximum element in a non-empty list."""
    best = lst[0]
    for x in lst[1:]:
        if x > best:
            best = x
    return best
