# -*- coding: utf-8 -*-
# 최적해 후보(candidate) → 데이터 의미별 뷰. 순수 함수만.
#   metric / history / timeseries / summary
from typing import Optional


def paginate(items: list, limit: Optional[int], offset: int = 0) -> dict:
    total = len(items)
    start = max(0, offset)
    end = total if limit is None else start + max(0, limit)
    return {'total': total, 'offset': start, 'limit': limit, 'items': items[start:end]}


def metric(candidate: dict) -> dict:
    return candidate['metric']


def history_types(candidate: dict) -> list:
    return sorted(candidate.get('history', {}))


def history(candidate: dict, history_type: str, *,
           workstation: str = None, process_code: str = None,
           from_sec: float = None, to_sec: float = None,
           limit: int = None, offset: int = 0) -> dict:
    bucket = candidate.get('history', {}).get(history_type)
    if bucket is None:
        raise KeyError(history_type)

    def keep(e):
        if workstation and e.get('workstation') != workstation and e.get('line') != workstation:
            return False
        if process_code and e.get('process_code') != process_code:
            return False
        if from_sec is not None and e.get('end_sec', e.get('t_sec', 0)) < from_sec:
            return False
        if to_sec is not None and e.get('start_sec', e.get('t_sec', 0)) > to_sec:
            return False
        return True

    picked = [e for e in bucket if keep(e)]
    page = paginate(picked, limit, offset)
    page['type'] = history_type
    return page


def timeseries(candidate: dict, features: list = None) -> dict:
    series = candidate['timeseries']
    available = list(series['features'])
    chosen = [f for f in (features or available) if f in series['features']]
    unknown = [f for f in (features or []) if f not in series['features']]
    if unknown:
        raise KeyError(', '.join(unknown))
    return {
        'sample_sec': series['sample_sec'],
        't_sec'     : series['t_sec'],
        'features'  : {f: series['features'][f] for f in chosen},
        'available' : available,
    }


def summary_kinds(candidate: dict) -> list:
    return sorted(candidate.get('summary', {}))


def summary(candidate: dict, by: str) -> dict:
    bucket = candidate.get('summary', {})
    if by not in bucket:
        raise KeyError(by)
    return {'by': by, 'data': bucket[by]}


def history_csv_rows(candidate: dict, history_type: str, **filters):
    page = history(candidate, history_type, limit=None, **filters)
    items = page['items']
    if not items:
        return [], []
    columns = list(items[0])
    return columns, [[row.get(c) for c in columns] for row in items]
