from __future__ import annotations

from collections import defaultdict, deque
from math import floor, hypot
from typing import Iterable

from .geometry import Stroke


POINT_TOLERANCE_MM = 1e-5
GRID_BLOCK_SIZE_MM = 10.0
EndpointKey = tuple[int, int]
BlockKey = tuple[int, int]


def optimize_plot_strokes(
    geometry_strokes: Iterable[Stroke],
    text_blocks: Iterable[Iterable[Stroke]] | None = None,
) -> list[Stroke]:
    """Return whole text blocks first, then optimized non-text geometry."""
    neighboring_merged = _merge_neighboring_strokes(geometry_strokes)
    globally_merged = _merge_shared_endpoint_strokes_hash(neighboring_merged)
    optimized_geometry = _sort_strokes_center_spiral_blocks(globally_merged)
    ordered_text = _clean_text_blocks(text_blocks or [])
    return [
        stroke for block in ordered_text for stroke in block
    ] + optimized_geometry


def _clean_text_blocks(text_blocks: Iterable[Iterable[Stroke]]) -> list[list[Stroke]]:
    cleaned_blocks: list[list[Stroke]] = []
    for block in text_blocks:
        cleaned = [
            _clean_stroke(stroke)
            for stroke in block
        ]
        cleaned = [
            stroke
            for stroke in cleaned
            if _stroke_length(stroke) > POINT_TOLERANCE_MM
        ]
        if cleaned:
            cleaned_blocks.append(cleaned)
    return cleaned_blocks


def _merge_neighboring_strokes(strokes: Iterable[Stroke]) -> list[Stroke]:
    cleaned = [_clean_stroke(stroke) for stroke in strokes]
    cleaned = [
        stroke
        for stroke in cleaned
        if _stroke_length(stroke) > POINT_TOLERANCE_MM
    ]
    if not cleaned:
        return []

    merged: list[Stroke] = []
    active = cleaned[0]
    for stroke in cleaned[1:]:
        candidate = _try_merge(active, stroke)
        if candidate is None:
            merged.append(active)
            active = stroke
            continue
        active = _clean_stroke(candidate)
    merged.append(active)
    return merged


def _merge_shared_endpoint_strokes_hash(strokes: Iterable[Stroke]) -> list[Stroke]:
    active: dict[int, Stroke] = {
        index: _clean_stroke(stroke)
        for index, stroke in enumerate(strokes)
    }
    active = {
        index: stroke
        for index, stroke in active.items()
        if _stroke_length(stroke) > POINT_TOLERANCE_MM
    }
    endpoint_index: dict[EndpointKey, set[int]] = defaultdict(set)
    for stroke_id, stroke in active.items():
        _add_stroke_endpoints(endpoint_index, stroke_id, stroke)

    merge_queue: deque[EndpointKey] = deque(endpoint_index)
    next_id = (max(active) + 1) if active else 0

    while merge_queue:
        key = merge_queue.popleft()
        pair = _find_merge_pair(endpoint_index.get(key, set()), active)
        if pair is None:
            continue

        first_id, second_id, merged_stroke = pair
        first = active.pop(first_id)
        second = active.pop(second_id)
        touched_keys = set(_endpoint_keys(first) + _endpoint_keys(second))
        _remove_stroke_endpoints(endpoint_index, first_id, first)
        _remove_stroke_endpoints(endpoint_index, second_id, second)

        merged_stroke = _clean_stroke(merged_stroke)
        if _stroke_length(merged_stroke) > POINT_TOLERANCE_MM:
            active[next_id] = merged_stroke
            new_keys = _endpoint_keys(merged_stroke)
            _add_stroke_endpoints(endpoint_index, next_id, merged_stroke)
            touched_keys.update(new_keys)
            next_id += 1

        merge_queue.extend(touched_keys)

    return list(active.values())


def _find_merge_pair(
    stroke_ids: Iterable[int],
    active: dict[int, Stroke],
) -> tuple[int, int, Stroke] | None:
    ids = [
        stroke_id
        for stroke_id in stroke_ids
        if stroke_id in active
    ]
    ids.sort()
    for first_index, first_id in enumerate(ids):
        first = active[first_id]
        for second_id in ids[first_index + 1:]:
            candidate = _try_merge(first, active[second_id])
            if candidate is not None:
                return first_id, second_id, candidate
    return None


def _add_stroke_endpoints(
    endpoint_index: dict[EndpointKey, set[int]],
    stroke_id: int,
    stroke: Stroke,
) -> None:
    for key in _endpoint_keys(stroke):
        endpoint_index[key].add(stroke_id)


def _remove_stroke_endpoints(
    endpoint_index: dict[EndpointKey, set[int]],
    stroke_id: int,
    stroke: Stroke,
) -> None:
    for key in _endpoint_keys(stroke):
        endpoint_index[key].discard(stroke_id)


def _endpoint_keys(stroke: Stroke) -> list[EndpointKey]:
    return [
        key
        for point in (stroke[0], stroke[-1])
        for key in _nearby_point_keys(point)
    ]


def _nearby_point_keys(point: tuple[float, float]) -> list[EndpointKey]:
    center_x, center_y = _point_key(point)
    return [
        (center_x + dx, center_y + dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
    ]


def _point_key(point: tuple[float, float]) -> EndpointKey:
    return (
        floor(point[0] / POINT_TOLERANCE_MM),
        floor(point[1] / POINT_TOLERANCE_MM),
    )


def _sort_strokes_center_spiral_blocks(strokes: Iterable[Stroke]) -> list[Stroke]:
    cleaned = [
        _clean_stroke(stroke)
        for stroke in strokes
    ]
    cleaned = [
        stroke
        for stroke in cleaned
        if _stroke_length(stroke) > POINT_TOLERANCE_MM
    ]
    if not cleaned:
        return []

    blocks = {_stroke_block_key(stroke) for stroke in cleaned}
    block_order = _spiral_block_order_map(blocks)
    return sorted(
        cleaned,
        key=lambda stroke: (
            block_order[_stroke_block_key(stroke)],
            stroke[0][0],
            stroke[0][1],
        ),
    )


def _stroke_block_key(stroke: Stroke) -> BlockKey:
    return _block_key(stroke[0])


def _block_key(point: tuple[float, float]) -> BlockKey:
    return (
        floor(point[0] / GRID_BLOCK_SIZE_MM),
        floor(point[1] / GRID_BLOCK_SIZE_MM),
    )


def _spiral_block_order_map(blocks: set[BlockKey]) -> dict[BlockKey, int]:
    min_x = min(block[0] for block in blocks)
    max_x = max(block[0] for block in blocks)
    min_y = min(block[1] for block in blocks)
    max_y = max(block[1] for block in blocks)
    center = ((min_x + max_x) // 2, (min_y + max_y) // 2)

    order: dict[BlockKey, int] = {}
    position = center
    if position in blocks:
        order[position] = 0

    directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    step_length = 1
    direction_index = 0
    rank = len(order)

    while len(order) < len(blocks):
        for _repeat in range(2):
            dx, dy = directions[direction_index % len(directions)]
            for _step in range(step_length):
                position = (position[0] + dx, position[1] + dy)
                if position in blocks and position not in order:
                    order[position] = rank
                    rank += 1
            direction_index += 1
        step_length += 1

    return order


def _try_merge(first: Stroke, second: Stroke) -> Stroke | None:
    first_start = first[0]
    first_end = first[-1]
    second_start = second[0]
    second_end = second[-1]

    candidates: list[Stroke] = []
    if _same_point(first_end, second_start):
        candidates.append(first + second[1:])
    if _same_point(first_end, second_end):
        candidates.append(first + list(reversed(second[:-1])))
    if _same_point(first_start, second_end):
        candidates.append(second + first[1:])
    if _same_point(first_start, second_start):
        candidates.append(list(reversed(second)) + first[1:])

    if not candidates:
        return None
    return min(candidates, key=_stroke_sort_key)


def _sort_strokes_bottom_left(strokes: Iterable[Stroke]) -> list[Stroke]:
    return sorted(strokes, key=_stroke_sort_key)


def _stroke_sort_key(stroke: Stroke) -> tuple[float, float, float]:
    start = stroke[0]
    return (start[0] + start[1], start[0], start[1])


def _clean_stroke(stroke: Stroke) -> Stroke:
    cleaned: Stroke = []
    for x, y in stroke:
        point = (float(x), float(y))
        if cleaned and _same_point(cleaned[-1], point):
            continue
        cleaned.append(point)
    return cleaned


def _same_point(
    first: tuple[float, float],
    second: tuple[float, float],
    tolerance: float = POINT_TOLERANCE_MM,
) -> bool:
    return abs(first[0] - second[0]) <= tolerance and abs(first[1] - second[1]) <= tolerance


def _stroke_length(stroke: Stroke) -> float:
    return sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(stroke, stroke[1:]))
