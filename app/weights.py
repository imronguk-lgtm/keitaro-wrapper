"""Пересчёт весов офферов в потоке.

Правило: закреплённые (pinned) веса не меняются, остаток до 100%
делится поровну между незакреплёнными офферами. Веса целые, поэтому
остаток от деления раздаём по +1% первым офферам: 100 / 3 → 34, 33, 33.
"""


def distribute(pinned: list[int], unpinned_count: int) -> list[int]:
    """Вернуть веса для незакреплённых офферов."""
    if unpinned_count == 0:
        return []
    rest = max(0, 100 - sum(pinned))
    base, remainder = divmod(rest, unpinned_count)
    return [base + 1 if i < remainder else base for i in range(unpinned_count)]


def recalc(links) -> None:
    """Пересчитать share у включённых привязок (объекты StreamOffer).

    Выключенные (удалённые) офферы получают 0%.
    """
    active = [link for link in links if link.included]
    for link in links:
        if not link.included:
            link.share = 0

    pinned = [link for link in active if link.pinned]
    unpinned = [link for link in active if not link.pinned]
    shares = distribute([link.share for link in pinned], len(unpinned))
    for link, share in zip(unpinned, shares):
        link.share = share
