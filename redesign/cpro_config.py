# -*- coding: utf-8 -*-
"""정책 상수 / 정적 매핑 / 정규화 분모.

AAS 에 없는 모든 외부 데이터를 한 파일에 모은다. 시뮬·KG 코드는
``from cpro_config import *`` 한 줄로 사용.

섹션::

    1. 시뮬 진입점 상수
    2. 라인 → 워커 그룹 매핑
    3. 정격 전력
    4. 재고 정책 (부족/초과 기준)
    5. 시뮬 시간 일정
    6. 학습 하이퍼파라미터 (PPO, GNN)
    7. 보상 정규화 분모 — 시뮬 init 시 계산되는 placeholder

규칙: AAS 템플릿에 어떤 항목이 추출 가능해지면 여기서 제거하고
``path_extractor`` derive 로 옮긴다.
"""
from __future__ import annotations

# ── 1. 시뮬 진입점 ─────────────────────────────────────────────────────────

RANDOM_SEED = 42
MAX_DAYS    = 7
DAY_SEC     = 86400


# ── 2. WWM 라인 → 워커 그룹 매핑 ───────────────────────────────────────────
#
# AAS 에 미반영. AAS qualifier 로 옮길 수 있을 때 derive 로 이동.
# 'WWM_InspectionLine' 은 기존 코드에는 없었지만 WWM JSON 에 존재 → INSP 그룹과
# 같은 워커 풀(WORKER_AGING) 으로 매핑.

WWM_LINE_TO_WORKER: dict = {
    'WWM_FwInputLine'      : 'WORKER_FW',
    'WWM_LensHolderLine'   : 'WORKER_LENS_HOLDER',
    'WWM_FocusLine'        : 'WORKER_SENSOR_FOCUS',
    'WWM_SemiAssemblyLine' : 'WORKER_SEMI',
    'WWM_SetAssemblyLine'  : 'WORKER_SET',
    'WWM_InspectionLine'   : 'WORKER_AGING',
    'WWM_AgingLine'        : 'WORKER_AGING',
    'WWM_OqcLine'          : 'WORKER_OQC',
    'WWM_RMALine'          : 'WORKER_RMA',
    'WWM_PackagingLine'    : 'WORKER_PACK',
}

WORKER_GROUPS = {
    'WORKER_FW', 'WORKER_SENSOR_FOCUS', 'WORKER_LENS_HOLDER',
    'WORKER_SEMI', 'WORKER_SET', 'WORKER_SET_INSP',
    'WORKER_AGING', 'WORKER_OQC', 'WORKER_PACK', 'WORKER_RMA',
}


# ── 3. 정격 전력 (kW) ──────────────────────────────────────────────────────
#
# pc 또는 process_group 단위 dict.
# Factory.rated_kw_of(m, pc) 가 pc 우선 → 못 찾으면 group 으로 lookup.
# AAS qualifier 'RatedPowerKw' 추가 시 derive 로 이동.

RATED_POWER_KW: dict = {
    # SMT 라인 1
    'SMT_LOADER_L1':    0.66,
    'SMT_PRINTER_L1':   0.84,
    'SMT_SPI_L1':       2.20,
    'SMT_MOUNTER_H_L1': 19.93,
    'SMT_MOUNTER_M_L1': 4.64,
    'SMT_REFLOW_L1':    63.26,
    'SMT_UNLOADER_L1':  0.33,
    # SMT 라인 2
    'SMT_LOADER_L2':    0.66,
    'SMT_PRINTER_L2':   1.72,
    'SMT_SPI_L2':       1.29,
    'SMT_MOUNTER_H_L2': 10.13,
    'SMT_MOUNTER_M_L2': 4.64,
    'SMT_REFLOW_L2':    48.03,
    'SMT_UNLOADER_L2':  0.33,
    'SMT_AOI':          0.29,
    # 공정 그룹 (pc lookup 실패 시 fallback)
    'MODULE_FW':        0.0,
    'NVD_40_FOCUS':     0.36,
    'MODULE':          23.38,
    'SEMI':            25.50,
    'SET':             33.67,
    'INSP':             1.22,
    'AGING':            1.84,
    'OQC':              0.44,
    'PACK':             8.31,
    'PACK_LABEL':       0.37,
    'RMA':              0.50,
}


# ── 4. 재고 정책 ───────────────────────────────────────────────────────────

MIN_STOCK = 50          # 발주 트리거 임계
CRITICAL_STOCK = 0      # 재고 부족 발생 임계 (violations 누적 기준)

# WIP (재공품) 한도 — 라인/그룹 한도 초과 시 violations 누적
WIP_LIMIT_PER_GROUP = 20

# 발주 리드타임 (초). Replenisher 가 이 주기로 부족 항목 검사 → MaxStock 까지 채움.
REPLENISH_LEAD_TIME_SEC = 4 * 3600     # 4 시간


# ── 5. 시뮬 시간 일정 ──────────────────────────────────────────────────────

WORK_SCHEDULE = {
    'work_start_sec':     8 * 3600,
    'work_end_sec':      18 * 3600,
    'break_duration_sec': 1 * 3600,
}


# ── 6. 학습 하이퍼파라미터 ─────────────────────────────────────────────────

# GNN
GNN_IN_DIM   = 17        # 노드 feat (정적 5 + pg_emb 4 + line_emb 4 + 동적 4)
GNN_HIDDEN   = 32
GNN_OUT_DIM  = 16
EMB_DIM_PG   = 4
EMB_DIM_LINE = 4
NUM_RELATIONS = 5        # fwd_join / fwd_seq / bwd_join / bwd_seq / self

# PPO
PPO_LR       = 3e-4
PPO_GAMMA    = 0.99
PPO_LAMBDA   = 0.95
PPO_CLIP_EPS = 0.2
PPO_EPOCHS   = 4
PPO_C_VALUE  = 0.5
PPO_C_ENT    = 0.01

# Critic encoder
CRITIC_HIDDEN_1 = 128
CRITIC_HIDDEN_2 = 64


# ── 7. 보상 정규화 분모 (시뮬 init 시 계산) ─────────────────────────────────

# Factory init 직후 실측/이론 계산해서 채우는 placeholder.
# 각 항이 어떻게 계산되는지 한 곳에서 보이도록 식을 명시:
#
#   T_REF         = MAX_DAYS * (WORK_SCHEDULE['work_end_sec']
#                              - WORK_SCHEDULE['work_start_sec']
#                              - WORK_SCHEDULE['break_duration_sec'])
#   E_REF         = Σ_pc  RATED_POWER_KW[pc 또는 grp]
#                       *  MP.groups[g].processes[pc].CycleTimeSec.value
#                       *  order[m for pc in m]                        / 3600
#   TOTAL_ORDER   = sum(order.values())
#   TOTAL_WORKER_CAPACITY = sum(worker_capacities.values())
#
# 실제 값은 ``Factory.__init__`` 에서 채움.


# ── 보상 가중치 (튜닝 placeholder) ─────────────────────────────────────────

# dense 4 항
REWARD_W_STOCK_SHORT = 0.20   # 재고 부족 delta
REWARD_W_STOCK_OVER  = 0.20   # 재고 초과 (WIP) delta
REWARD_W_DONE        = 0.30   # 완성 진행 delta
REWARD_W_IDLE        = 0.10   # 워커 idle delta

# terminal 3 항
REWARD_W_MAKESPAN    = 0.10
REWARD_W_KWH         = 0.05
REWARD_W_SUCCESS     = 0.05   # +1 보너스에 곱해질 가중치
