# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict

import carbon


def build_payload(env, summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'throughput'   : dict(summary.get('Throughput', {})),
        'makespan_sec' : summary.get('makespan_sec'),
        'energy_kwh'   : summary.get('EpisodeEnergyKwh'),
        'carbon_kgco2e': carbon.total(summary.get('EpisodeEnergyKwh') or 0.0),
    }


def send(payload: Dict[str, Any]) -> None:
    raise NotImplementedError('export.send: 외부 API 계약 미정 — Task 5 에서 구현')
