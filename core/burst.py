"""连拍分组：按拍摄时间聚簇，再用 dHash 去掉"同时间不同画面"的情况。

两段式的好处：时间窗能挡住绝大多数无关照片（不同时刻拍的一定不是连拍），
dHash 再兜住"两秒内转头拍了另一个方向"这种误聚类。
"""

from __future__ import annotations

from .analyze import hamming
from .const import BURST_HAMMING_MAX, BURST_TIME_GAP


def _clusters_by_time(photos: list[dict], gap: float) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    current: list[dict] = []
    for photo in photos:
        if not current:
            current = [photo]
            continue
        prev = current[-1]
        t_prev, t_cur = prev.get("taken_at"), photo.get("taken_at")
        if t_prev is not None and t_cur is not None and abs(t_cur - t_prev) <= gap:
            current.append(photo)
        else:
            clusters.append(current)
            current = [photo]
    if current:
        clusters.append(current)
    return clusters


def _split_by_similarity(cluster: list[dict], ham_max: int) -> list[list[dict]]:
    """把一簇按画面相似度拆成若干连拍组；每组至少 2 张。"""
    groups: list[list[dict]] = []
    taken = [False] * len(cluster)
    for i, anchor in enumerate(cluster):
        if taken[i]:
            continue
        try:
            anchor_hash = int(anchor["dhash"])
        except (TypeError, ValueError):
            taken[i] = True
            continue
        group = [anchor]
        taken[i] = True
        for j in range(i + 1, len(cluster)):
            if taken[j]:
                continue
            try:
                if hamming(anchor_hash, int(cluster[j]["dhash"])) <= ham_max:
                    group.append(cluster[j])
                    taken[j] = True
            except (TypeError, ValueError):
                taken[j] = True
        if len(group) >= 2:
            groups.append(group)
    return groups


def build_groups(
    photos: list[dict],
    time_gap: float = BURST_TIME_GAP,
    ham_max: int = BURST_HAMMING_MAX,
) -> list[list[int]]:
    """输入按拍摄时间排好序的照片行，输出分组（每组成员 id，组内 2 张以上）。"""
    usable = [p for p in photos if p.get("dhash")]
    usable.sort(key=lambda p: (p.get("taken_at") or 0, p["id"]))
    groups: list[list[int]] = []
    for cluster in _clusters_by_time(usable, time_gap):
        if len(cluster) < 2:
            continue
        for group in _split_by_similarity(cluster, ham_max):
            groups.append([p["id"] for p in group])
    return groups
