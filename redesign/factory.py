# -*- coding: utf-8 -*-
"""Factory dataclass — 공장 단위 결합체.

여러 ``AASModel`` + ``cpro_config`` 의 정적 매핑을 한 객체로 묶고, 학습/시뮬에
필요한 derived 매핑 (process_group / line 의 ID 매핑, 정규화 분모) 까지 한 번에
계산한다.

시뮬·KG·env 코드는 이 객체만 받아서 동작한다. JSON / config dict 직접 접근 X.

경로 패턴(참고)::

    factory.models[m].MP.groups[g].processes[pc].CycleTimeSec.value
    factory.line_to_worker[ws_id]
    factory.pg_to_idx[group_name]
    factory.line_to_idx[ws_id]
    factory.T_REF, factory.E_REF, factory.total_order
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from aas import AASModel
import cpro_config as C


@dataclass
class Factory:
    """공장 1개의 모든 정적 정보 + derived.

    Note: 한 (model_id, process_code) 가 노드 키. 한 노드(pc)에는 시뮬 중
    여러 unit 이 동시에 ready 상태가 될 수 있으며 ``sim_env`` 가 (m, pc)
    별 FIFO queue 로 관리한다.
    """

    # ── 입력 ────────────────────────────────────────────────────────────
    models: Dict[str, AASModel]
    order:  Dict[str, int]                       # model_id -> qty
    line_to_worker: Dict[str, str]               # ws_id -> worker_group
    rated_kw_table: Dict[str, float]             # pc 또는 group -> kW
    worker_capacity: Dict[str, int]              # worker_group -> capacity

    # BOM 재고 universe (item_code -> threshold). 추후 path_extractor 가
    # HS Category[...].MinStock/MaxStock 을 추출하면 호출자가 그 dict 그대로 전달.
    bom_min_stock: Dict[str, int] = field(default_factory=dict)
    bom_max_stock: Dict[str, int] = field(default_factory=dict)

    # ── derived (post_init 에서 채워짐) ─────────────────────────────────
    pg_to_idx:   Dict[str, int] = field(default_factory=dict)
    line_to_idx: Dict[str, int] = field(default_factory=dict)
    unmapped_line_idx: int = 0  # WWM 미매핑 process 의 line_idx sentinel

    # 정규화 분모 (cpro_config 의 placeholder 식 참고)
    T_REF: float = 0.0
    E_REF: float = 0.0
    total_order: int = 0
    total_worker_capacity: int = 0

    def __post_init__(self) -> None:
        self._build_id_maps()
        self._compute_normalizers()

    # ── 식별자 ID 매핑 (학습 임베딩용) ─────────────────────────────────

    def _build_id_maps(self) -> None:
        """AAS 스캔으로 만나는 모든 process_group / line 을 0..N-1 idx 로 매핑.

        WWM 에 미매핑된 process 용 ``'_UNMAPPED'`` sentinel 라인을 마지막에 추가
        — embedding lookup 시 OOR 방지 + line_filter_mask 에서 자동 제외.
        """
        pg_seen:   List[str] = []
        line_seen: List[str] = []
        for aas in self.models.values():
            for group_name in aas.MP.groups.keys():
                if group_name not in pg_seen:
                    pg_seen.append(group_name)
            for ws_id in aas.process_to_workstation.values():
                if ws_id not in line_seen:
                    line_seen.append(ws_id)
        line_seen.append('_UNMAPPED')
        self.pg_to_idx   = {g:  i for i, g  in enumerate(pg_seen)}
        self.line_to_idx = {ws: i for i, ws in enumerate(line_seen)}
        self.unmapped_line_idx = self.line_to_idx['_UNMAPPED']

    # ── 정규화 분모 ─────────────────────────────────────────────────────

    def _compute_normalizers(self) -> None:
        """T_REF / E_REF / total_order / total_worker_capacity 계산.

        cpro_config.py 의 placeholder 식을 그대로 구현::

            T_REF = MAX_DAYS * work_sec_per_day
            E_REF = Σ_pc rated_kw[pc or grp] * ct[pc] * order[m]  / 3600
        """
        sch = C.WORK_SCHEDULE
        work_sec_per_day = sch['work_end_sec'] - sch['work_start_sec'] - sch['break_duration_sec']
        self.T_REF = float(C.MAX_DAYS * work_sec_per_day)

        self.total_order = sum(self.order.values())
        self.total_worker_capacity = sum(self.worker_capacity.values())

        e_ref = 0.0
        for model_id, aas in self.models.items():
            qty = self.order.get(model_id, 0)
            for process_code in aas.process_codes():
                rated_kw       = self.rated_kw_of(model_id, process_code)
                cycle_time_sec = float(aas.cycle_time_of[process_code])
                e_ref += rated_kw * cycle_time_sec * qty / 3600.0
        self.E_REF = max(e_ref, 1.0)

    # ── 편의 lookup ────────────────────────────────────────────────────

    def all_node_keys(self) -> List[Tuple[str, str]]:
        """전체 통합 KG 노드 키 list: ``[(model_id, process_code), ...]``."""
        return [(m, pc)
                for m, aas in self.models.items()
                for pc in aas.process_codes()]

    def all_bom_items(self) -> List[str]:
        """모든 모델의 모든 process 의 InputBOM 키 union (stable order)."""
        seen: List[str] = []
        for aas in self.models.values():
            for grp in aas.MP.groups.values():
                for node in grp.processes.values():
                    for item in node.InputBOM.keys():
                        if item not in seen:
                            seen.append(item)
        return seen

    def worker_of(self, model_id: str, process_code: str) -> str:
        """노드의 worker_group lookup (line → worker)."""
        ws_id = self.models[model_id].process_to_workstation.get(process_code, '')
        return self.line_to_worker.get(ws_id, '')

    def rated_kw_of(self, model_id: str, process_code: str) -> float:
        """노드의 rated_kw. 우선순위: AAS SIM 추출 → table(pc → abstract → mp_group).

        SIM AAS 가 RatedPowerKw 를 직접 들고 있으면 그 값. 0/없음일 때만 cpro_config
        의 RATED_POWER_KW dict 로 fallback (SMT 라인 등 SIM 미수록 process 용).
        """
        aas = self.models[model_id]
        kw = aas.rated_kw_of_pc.get(process_code, 0.0)
        if kw > 0:
            return kw
        abstract_group = aas.abstract_group_of.get(process_code, '')
        mp_group_name  = aas.process_group_of[process_code]
        return self.rated_kw_table.get(
            process_code,
            self.rated_kw_table.get(
                abstract_group,
                self.rated_kw_table.get(mp_group_name, 0.0)))
