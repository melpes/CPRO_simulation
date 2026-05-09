import simpy
import random
import os
import time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from path_extractor import (
    load_aas, AASModel,
    ProcessNode, SkillLevel,
)

try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    BASE_DIR = os.getcwd()

POLICY_PATH  = os.path.join(BASE_DIR, 'ppo_policy.pt')
RESULT_PATH  = os.path.join(BASE_DIR, 'simulation_results.xlsx')
AAS_JSON_PATHS = {
    'MODEL_A': os.path.join(BASE_DIR, 'MODEL_A.json'),
    'MODEL_B': os.path.join(BASE_DIR, 'MODEL_B.json'),
    'MODEL_C': os.path.join(BASE_DIR, 'MODEL_C.json'),
}

RANDOM_SEED = 42
DAY_SEC     = 24 * 3600
MAX_DAYS    = 365
_active_schedule: dict = {}

_EVENT_BUF = []
def _log_event(t, msg):
    _EVENT_BUF.append((float(t), str(msg)))
    if len(_EVENT_BUF) > 100:
        del _EVENT_BUF[:-100]

def _apply_schedule(schedule_dict: dict):

    _active_schedule.update(schedule_dict)
    required = ('work_start_sec', 'work_end_sec',
                'lunch_start_sec', 'lunch_end_sec', 'break_duration_sec')
    missing = [k for k in required if k not in _active_schedule]
    if missing:
        raise RuntimeError(
            f'AAS 가 근무 스케줄 미제공: {missing}. '
            f'WorkstationWorkerMatchingData 의 WorkStartTime / WorkEndTime / '
            f'BreakDurationMin(Range) 을 확인하세요.')

PCB_PER_UNIT       = 1
MAG_SIZE           = 15
TRUCK_SIZE         = 30

SOLDER_G           = 500
SOLDER_VALID_SEC   = 24 * 3600
SOLDER_USE_G       = 0.07

CT_STD_RATIO       = 0.10
DEFECT_FLOOR       = 0.00001

MIN_STOCK                  = 100
CRITICAL_STOCK             = 5
REPLENISH_LEAD_DAY         = 1
REPLENISH_QTY_MULT         = 10
WIP_CAP_RATIO              = 1.5

OQC_RATE     = 0.05
OQC_TIME_SEC = 600
AOI_DEFECT_ACTION = 'repair'

RMA_REPAIR_TIME_MEAN_SEC = 300
RMA_REPAIR_TIME_STD_SEC  = 60
RMA_REPAIR_TIME_MIN_SEC  = 60

SMT_BREAKDOWN_PROB  = 0.000005
SMT_MTTR_DEFAULT_HR = 0.5
WORKER_ABSENT_PROB  = 0.0005
THT_DELAY_PROB      = 0.02
THT_DELAY_MIN_SEC   = 1  * 3600
THT_DELAY_MAX_SEC   = 24 * 3600
THT_OUTSOURCE_SEC   = 12 * 3600

TRAIN_MONITOR_INTERVAL = DAY_SEC
INFER_MONITOR_STEP_HR  = 0.1
INFER_MONITOR_INTERVAL = int(INFER_MONITOR_STEP_HR * 3600)
MONITOR_MIN_WALL_SEC   = 0.05

PCB_MAP = {
    'MODEL_A': '03203204',
    'MODEL_B': '03203145',
    'MODEL_C': '03203315',
}
THT_PCB_BY_MODEL = {
    'MODEL_A': ['03902715', '03903424'],
    'MODEL_B': ['03902608', '03902730'],
    'MODEL_C': ['03903388', '03903391'],
}
THT_RAW_SUFFIX = '_RAW'
def tht_raw_code(pcb_code):
    return f'{pcb_code}{THT_RAW_SUFFIX}'

SMT_LINE_IDS = ['L1', 'L2']
PCB_INITIAL_RATIO          = 0.8
BOM_INITIAL_RATIO          = 0.6
BOM_LOT_RATIO              = 0.5
WAREHOUSE_BOM_INIT_FLOOR   = 50
WAREHOUSE_BOM_LOT_FLOOR    = 50
WAREHOUSE_NONBOM_INIT_MULT = 10
RATED_POWER_KW = {
    'SMT_LOADER_L1':    0.66,
    'SMT_PRINTER_L1':   0.84,
    'SMT_SPI_L1':       2.20,
    'SMT_MOUNTER_H_L1': 19.93,
    'SMT_MOUNTER_M_L1': 4.64,
    'SMT_REFLOW_L1':    63.26,
    'SMT_UNLOADER_L1':  0.33,
    'SMT_LOADER_L2':    0.66,
    'SMT_PRINTER_L2':   1.72,
    'SMT_SPI_L2':       1.29,
    'SMT_MOUNTER_H_L2': 10.13,
    'SMT_MOUNTER_M_L2': 4.64,
    'SMT_REFLOW_L2':    48.03,
    'SMT_UNLOADER_L2':  0.33,
    'SMT_AOI':          0.29,
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

def get_rated_power_kw(process_code: str, process_group: str = '',
                       capacity: int = 1) -> float:
    base = RATED_POWER_KW.get(str(process_code))
    if base is None:
        base = RATED_POWER_KW.get(str(process_group), 0.0)
    return base / max(int(capacity), 1)
SET_INSP_HEADCOUNT = 3
PROCESS_GROUP_TO_WORKER_GROUP = {
    'MODULE':       None,
    'MODULE_FW':    'WORKER_FW',
    'NVD_40_FOCUS': 'WORKER_SENSOR_FOCUS',
    'SEMI':         'WORKER_SEMI',
    'SET':          'WORKER_SET',
    'INSP':         'WORKER_AGING',
    'AGING':        'WORKER_AGING',
    'OQC':          'WORKER_OQC',
    'PACK':         'WORKER_PACK',
    'RMA':          'WORKER_RMA',
}

def _find_pack_entry(data, model_id):
    try:
        procs = data.get_model_procs(model_id)
    except Exception:
        return None
    grp_of = {str(r['process_code']): str(r.get('process_group', '') or '')
              for _, r in procs.iterrows()}
    for _, r in procs.iterrows():
        if str(r.get('process_group', '') or '') != 'PACK':
            continue
        prevs = [p.strip() for p in
                 str(r.get('dep_prev_codes', '') or '').split(';') if p.strip()]
        for p in prevs:
            if grp_of.get(p) == 'INSP':
                return str(r['process_code'])
    return None

WORKER_GROUPS = {
    'WORKER_FW', 'WORKER_SENSOR_FOCUS', 'WORKER_LENS_HOLDER',
    'WORKER_SEMI', 'WORKER_SET', 'WORKER_SET_INSP',
    'WORKER_AGING', 'WORKER_OQC', 'WORKER_PACK', 'WORKER_RMA',
}

LOCATION_LABEL = {
    'WORKER_FW'          : 'F/W 입력',
    'WORKER_LENS_HOLDER' : 'LENS HOLDER 조립',
    'WORKER_SENSOR_FOCUS': 'FOCUS',
    'WORKER_SET'         : 'SET 조립',
    'WORKER_SET_INSP'    : 'SET 조립 (INSP)',
    'WORKER_SEMI'        : '반 조립 라인',
    'WORKER_RMA'         : 'RMA',
    'WORKER_OQC'         : 'OQC',
    'WORKER_AGING'       : 'Aging test',
    'WORKER_PACK'        : '포장',
}
LOCATION_ORDER = [
    'WORKER_FW', 'WORKER_LENS_HOLDER', 'WORKER_SENSOR_FOCUS',
    'WORKER_SET', 'WORKER_SET_INSP', 'WORKER_SEMI',
    'WORKER_RMA', 'WORKER_OQC', 'WORKER_AGING', 'WORKER_PACK',
]

class FallbackDataLoader:

    _PF_COLS = ('process_code', 'process_group', 'dep_type', 'dep_prev_codes',
                'worker_group', 'worker_count', 'cycle_time_sec', 'defect_rate',
                'transfer_qty', 'transport_mode', 'transfer_time_sec')

    _PF_ALL_ROWS = [
        ('RMA_REPAIR',       'RMA', 'SEQUENCE', '',                 'WORKER_RMA', 6, 600.0, 0.0,   0, '',         0.0),
        ('SMT_LOADER_L1',    'SMT', 'SEQUENCE', '',                 'OPERATOR',   2,   2.0, 0.001, 1, 'CONVEYOR', 5.0),
        ('SMT_LOADER_L2',    'SMT', 'SEQUENCE', '',                 'OPERATOR',   2,   2.0, 0.001, 1, 'CONVEYOR', 5.0),
        ('SMT_PRINTER_L1',   'SMT', 'SEQUENCE', 'SMT_LOADER_L1',    'OPERATOR',   2,  43.0, 0.001, 1, 'CONVEYOR', 5.0),
        ('SMT_PRINTER_L2',   'SMT', 'SEQUENCE', 'SMT_LOADER_L2',    'OPERATOR',   2,  43.0, 0.001, 1, 'CONVEYOR', 5.0),
        ('SMT_SPI_L1',       'SMT', 'SEQUENCE', 'SMT_PRINTER_L1',   'OPERATOR',   2,  15.0, 0.001, 1, 'CONVEYOR', 5.0),
        ('SMT_SPI_L2',       'SMT', 'SEQUENCE', 'SMT_PRINTER_L2',   'OPERATOR',   2,  15.0, 0.001, 1, 'CONVEYOR', 5.0),
        ('SMT_MOUNTER_H_L1', 'SMT', 'SEQUENCE', 'SMT_SPI_L1',       'OPERATOR',   2,  80.0, 0.003, 1, 'CONVEYOR', 5.0),
        ('SMT_MOUNTER_H_L2', 'SMT', 'SEQUENCE', 'SMT_SPI_L2',       'OPERATOR',   2,  80.0, 0.003, 1, 'CONVEYOR', 5.0),
        ('SMT_MOUNTER_M_L1', 'SMT', 'SEQUENCE', 'SMT_MOUNTER_H_L1', 'OPERATOR',   2,  45.0, 0.005, 1, 'CONVEYOR', 5.0),
        ('SMT_MOUNTER_M_L2', 'SMT', 'SEQUENCE', 'SMT_MOUNTER_H_L2', 'OPERATOR',   2,  45.0, 0.005, 1, 'CONVEYOR', 5.0),
        ('SMT_REFLOW_L1',    'SMT', 'SEQUENCE', 'SMT_MOUNTER_M_L1', 'OPERATOR',   2, 410.0, 0.001, 1, 'CONVEYOR', 5.0),
        ('SMT_REFLOW_L2',    'SMT', 'SEQUENCE', 'SMT_MOUNTER_M_L2', 'OPERATOR',   2, 410.0, 0.001, 1, 'CONVEYOR', 5.0),
        ('SMT_UNLOADER_L1',  'SMT', 'SEQUENCE', 'SMT_REFLOW_L1',    'OPERATOR',   2,   5.0, 0.001, 0, 'CART',     7.0),
        ('SMT_UNLOADER_L2',  'SMT', 'SEQUENCE', 'SMT_REFLOW_L2',    'OPERATOR',   2,   5.0, 0.001, 0, 'CART',     7.0),
        ('SMT_AOI', 'SMT', 'JOIN', 'SMT_UNLOADER_L1;SMT_UNLOADER_L2', 'OPERATOR', 2,  30.0, 0.003, 1, '',         0.0),
    ]

    _RESOURCE_MTTR_HR = {
        'SMT_AOI':          3.3,
        'SMT_MOUNTER_H_L1': 1.5,
        'SMT_MOUNTER_H_L2': 1.4,
        'SMT_MOUNTER_M_L1': 1.5,
        'SMT_MOUNTER_M_L2': 1.5,
        'SMT_PRINTER_L1':   4.0,
        'SMT_PRINTER_L2':   4.5,
        'SMT_REFLOW_L1':    8.0,
        'SMT_REFLOW_L2':    8.0,
        'SMT_SPI_L2':       2.3,
    }

    def __init__(self):
        rows = []
        for tup in self._PF_ALL_ROWS:
            rec = dict(zip(self._PF_COLS, tup))
            rec['model_id']    = 'ALL'
            rec['ref_no']      = ''
            rec['process_name']= ''
            rec['dep_wait_hr'] = 0.0
            rows.append(rec)
        self.pf = pd.DataFrame(rows)
        self.pf['defect_rate'] = self.pf['defect_rate'].apply(
            lambda x: x if x > 0 else DEFECT_FLOOR)

        self.bom = pd.DataFrame(columns=[
            'item_code', 'item_name', 'smt_side', 'min_stock_qty',
            'lot_size', 'critical_stock_qty', 'defect_rate'])
        self.bom_struct = pd.DataFrame(columns=[
            'model_id', 'parent_type', 'parent_code', 'item_code',
            'item_name', 'qty_per_parent'])

        self.workers   = {}
        self.resources = []

        self._pc_map = {str(r['process_code']): r for _, r in self.pf.iterrows()}
        self._grp_kw = defaultdict(float)
        self._mttr   = {pc: hr * 3600 for pc, hr in self._RESOURCE_MTTR_HR.items()}
        self._bom_idx = defaultdict(list)
        self._min_stock_cache      = {}
        self._lot_size_cache       = {}
        self._item_name_cache      = {}
        self._smt_side_cache       = {}
        self._critical_stock_cache = {}
        self._bom_dup_merge_log    = []

    def get_proc(self, pc):
        return self._pc_map.get(str(pc))

    def get_kw(self, process_code, process_group, capacity=1):
        kw = get_rated_power_kw(process_code, process_group, capacity)
        if kw > 0:
            return kw
        return {'SMT': 5.0, 'MODULE': 1.0, 'SEMI': 2.0, 'SET': 2.0,
                'INSP': 0.5, 'OQC': 0.2, 'PACK': 1.0, 'RMA': 0.1
                }.get(process_group, 0.5) / max(capacity, 1)

    def get_mttr(self, process_code):
        return self._mttr.get(str(process_code), SMT_MTTR_DEFAULT_HR * 3600)

    def get_min_stock(self, item_code):
        return self._min_stock_cache.get(str(item_code), float(MIN_STOCK))

    def get_critical_stock(self, item_code):
        return self._critical_stock_cache.get(str(item_code), float(CRITICAL_STOCK))

    def get_lot_size(self, item_code):
        c = str(item_code)
        lot = self._lot_size_cache.get(c, -1)
        if lot > 0:
            return lot
        return int(self.get_min_stock(c) * REPLENISH_QTY_MULT)

    def get_bom_parts(self, model_id, parent_code):
        return self._bom_idx.get((model_id, str(parent_code)), [])

    def get_pcb_parts(self, pcb_code):
        return []

    def get_item_name(self, item_code):
        return self._item_name_cache.get(str(item_code), '')

    def smt_side(self, item_code):
        return 'double'

    def iter_all_bom_items(self):
        return set()

    def get_all_bom_codes(self):
        if not hasattr(self, '_all_bom_codes_cache'):
            self._all_bom_codes_cache = self.iter_all_bom_items()
        return self._all_bom_codes_cache

    def get_model_procs(self, model_id):
        df = self.pf
        return df[df['model_id'].isin([model_id, 'ALL'])
                  & ~df['process_group'].isin(
                      ['SMT', 'LOGISTICS', 'SMT_SHARED', 'RMA'])].copy()

class CombinedDataLoader:

    def __init__(self, static_loader: 'FallbackDataLoader', aas_models: dict):
        self.static   = static_loader
        self.aas_map  = aas_models

        self._pc_map = dict(static_loader._pc_map)
        for model_id, aas in aas_models.items():
            for ProcessCode, node in aas.ManufacturingProcess.items():
                self._pc_map[ProcessCode] = {
                    'process_code'     : node.ProcessCode,
                    'model_id'         : model_id,
                    'process_group'    : node.ProcessGroup,
                    'worker_group'     : self._resolve_worker(node, aas),
                    'cycle_time_sec'   : float(node.CycleTimeSec),
                    'defect_rate'      : max(float(node.DefectRate), DEFECT_FLOOR),
                    'dep_type'         : node.DepType,
                    'dep_prev_codes'   : ';'.join(node.DepPrev),
                    'dep_wait_hr'      : 0.0,
                    'transfer_qty'     : 1,
                    'transfer_time_sec': 0.0,
                    'transport_mode'   : '',
                }

        self._bom_idx = dict(static_loader._bom_idx)
        for model_id, aas in aas_models.items():
            for ProcessCode, node in aas.ManufacturingProcess.items():
                key = (model_id, ProcessCode)
                entries = [(item.item_code, item.Quantity) for item in node.InputBOM]
                if entries:
                    self._bom_idx[key] = entries

        self._hs_bom_idx = {}
        for model_id, aas in aas_models.items():
            for pcb_id, pcb in aas.HierarchicalStructures.pcb_entries.items():
                key = (model_id, pcb_id)
                self._hs_bom_idx[key] = [
                    (comp.item_code, comp.Quantity, comp.Category)
                    for comp in pcb.components
                ]
            for part_id, part in aas.HierarchicalStructures.assembly_parts.items():
                key = (model_id, '__UNIT__')
                self._hs_bom_idx.setdefault(key, [])
                self._hs_bom_idx[key].append((part_id, part.Quantity, part.Category))

        self.workers = {}
        for aas in aas_models.values():
            for ws_id, ws in aas.WorkstationWorkerMatchingData.items():
                wgrp = self._ws_to_worker(ws_id)
                if wgrp:
                    self.workers[wgrp] = ws.WorkstationConfigurationRecords
        missing = [w for w in WORKER_GROUPS
                   if w != 'WORKER_SET_INSP' and w not in self.workers]
        if missing:
            raise RuntimeError(
                f'AAS WorkstationWorkerMatchingData 에서 미매핑 worker group: {missing}')
        set_total = self.workers['WORKER_SET']
        self.workers['WORKER_SET_INSP'] = max(int(set_total * 0.2), SET_INSP_HEADCOUNT)

        self.worker_skill = {}
        self.skill_ct     = {}
        self.skill_dr     = {}
        for aas in aas_models.values():
            for ws_id, ws in aas.WorkstationWorkerMatchingData.items():
                wgrp = self._ws_to_worker(ws_id)
                if wgrp:
                    self.worker_skill[wgrp] = ws.SkillLevel
            for name, sl in aas.SkillLevelType.items():
                self.skill_ct[sl.rank] = sl.ct_factor
                self.skill_dr[sl.rank] = sl.dr_factor
        if not self.skill_ct:
            raise RuntimeError('AAS SkillLevelType 누락 — SkillLevel 의 ct/dr factor 추출 실패')

        self.worker_groups  = set(self.workers.keys())
        self.location_order = [ws for ws in LOCATION_ORDER if ws in self.worker_groups]
        self.location_label = dict(LOCATION_LABEL)

        self.pcb_map          = dict(PCB_MAP)
        self.tht_pcb_by_model = dict(THT_PCB_BY_MODEL)

        self.schedule = {}
        for aas in aas_models.values():
            s = aas.schedule
            if s:
                self.schedule = {
                    'work_start_sec'    : s['WorkStartTime'],
                    'work_end_sec'      : s['WorkEndTime'],
                    'lunch_start_sec'   : s['BreakDurationMin_min'],
                    'lunch_end_sec'     : s['BreakDurationMin_max'],
                    'break_duration_sec': s['BreakDurationMin_max']
                                        - s['BreakDurationMin_min'],
                }
                break
        if not self.schedule:
            raise RuntimeError('AAS schedule 누락 — WorkstationWorkerMatchingData 확인')

        self.bom        = static_loader.bom
        self.bom_struct = static_loader.bom_struct
        self.resources  = static_loader.resources
        self._pf_combined = self._build_combined_pf()

    _WWM_LINE_TO_WORKER = {
        'WWM_FwInputLine'      : 'WORKER_FW',
        'WWM_LensHolderLine'   : 'WORKER_LENS_HOLDER',
        'WWM_FocusLine'        : 'WORKER_SENSOR_FOCUS',
        'WWM_SemiAssemblyLine' : 'WORKER_SEMI',
        'WWM_SetAssemblyLine'  : 'WORKER_SET',
        'WWM_AgingLine'        : 'WORKER_AGING',
        'WWM_OqcLine'          : 'WORKER_OQC',
        'WWM_RMALine'          : 'WORKER_RMA',
        'WWM_PackagingLine'    : 'WORKER_PACK',
    }

    def _ws_to_worker(self, ws_id: str) -> str:
        return self._WWM_LINE_TO_WORKER.get(ws_id, '')

    def _resolve_worker(self, node: ProcessNode, aas: AASModel) -> str:
        ws_id = aas.group_to_workstation.get(node.GroupIdShort, '')
        wgrp  = self._ws_to_worker(ws_id)
        if not wgrp:
            pg = node.ProcessGroup
            wgrp = PROCESS_GROUP_TO_WORKER_GROUP.get(pg, 'WORKER_SEMI') or 'WORKER_SEMI'
        return wgrp

    def _build_combined_pf(self) -> pd.DataFrame:
        aas_rows = list(self._pc_map.values())
        static_rows = self.static.pf.to_dict('records')
        df = pd.DataFrame(static_rows + [r for r in aas_rows if isinstance(r, dict)])
        for col in ['cycle_time_sec','defect_rate','transfer_qty','transfer_time_sec','dep_wait_hr']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        if 'defect_rate' in df.columns:
            df['defect_rate'] = df['defect_rate'].apply(lambda x: x if x > 0 else DEFECT_FLOOR)
        return df

    def get_proc(self, pc):
        return self._pc_map.get(str(pc))

    def get_kw(self, process_code, process_group, capacity=None):
        return self.static.get_kw(process_code, process_group, capacity or 1)

    def get_mttr(self, process_code):
        return self.static.get_mttr(process_code)

    def get_min_stock(self, item_code):
        return self.static.get_min_stock(item_code)

    def get_critical_stock(self, item_code):
        return self.static.get_critical_stock(item_code)

    def get_lot_size(self, item_code):
        return self.static.get_lot_size(item_code)

    def get_item_name(self, item_code):
        return self.static.get_item_name(item_code)

    def get_bom_parts(self, model_id, parent_code):
        return self._bom_idx.get((model_id, str(parent_code)), [])

    def get_pcb_parts(self, pcb_code):
        for model_id in self.aas_map:
            result = self._hs_bom_idx.get((model_id, f'PCB_{pcb_code}'), [])
            if result:
                return [(ic, qty) for ic, qty, _ in result]
        return []

    def smt_side(self, item_code):
        c = str(item_code)
        for aas in self.aas_map.values():
            pcb = aas.HierarchicalStructures.pcb_entries.get(f'PCB_{c}')
            if pcb:
                return pcb.SMT_Side
        return 'double'

    def get_all_bom_codes(self):
        codes = set()
        for (mid, pc), items in self._bom_idx.items():
            for ic, _ in items:
                codes.add(str(ic))
        return codes

    def iter_all_bom_items(self):
        return self.get_all_bom_codes()

    def get_model_procs(self, model_id):
        df = self._pf_combined
        return df[
            df['model_id'].isin([model_id, 'ALL'])
            & ~df['process_group'].isin(['SMT','LOGISTICS','SMT_SHARED','RMA'])
        ].copy()

class ProcessKnowledgeGraph:
    def __init__(self, data, model_id: str):
        self.model_id = model_id
        self._data    = data
        self.nodes    = {}
        self.edges    = []
        df     = data.get_model_procs(model_id)
        max_ct = max(df['cycle_time_sec'].max(), 1)
        for _, r in df.iterrows():
            pc   = str(r['process_code'])
            wgrp = str(r.get('worker_group','') or '')
            kw   = data.get_kw(pc, str(r.get('process_group','') or ''))
            dt   = str(r.get('dep_type','SEQUENCE') or 'SEQUENCE').upper()
            self.nodes[pc] = {
                'process_code' : pc,
                'process_group': str(r.get('process_group','') or ''),
                'cycle_time_sec': float(r['cycle_time_sec'] or 0),
                'defect_rate'  : float(r['defect_rate'] or DEFECT_FLOOR),
                'dep_wait_hr'  : float(r['dep_wait_hr'] or 0),
                'worker_group' : wgrp,
                'worker_count' : data.workers.get(wgrp, 1),
                'rated_kw'     : kw,
                'transfer_time': float(r['transfer_time_sec'] or 0),
                'dep_type'     : dt,
                'feat': np.array([
                    float(r['cycle_time_sec'] or 0) / max_ct,
                    min(float(r['defect_rate'] or DEFECT_FLOOR) * 1000, 1.0),
                    data.workers.get(wgrp, 1) / 20,
                    min(kw / 100, 1.0),
                    1.0 if dt == 'FORK' else 0.0,
                    1.0 if dt == 'JOIN'  else 0.0,
                ], dtype=np.float32)
            }
            for prev in [p.strip() for p in
                         str(r.get('dep_prev_codes','') or '').split(';') if p.strip()]:
                if prev != pc:
                    self.edges.append((prev, pc, dt))

    def get_feat_matrix(self):
        pcs = list(self.nodes.keys())
        return pcs, np.stack([self.nodes[p]['feat'] for p in pcs])

    def get_adj(self):
        pcs = list(self.nodes.keys())
        idx = {p: i for i, p in enumerate(pcs)}
        N   = len(pcs)
        adj = np.zeros((N, N), dtype=np.float32)
        for f, t, _ in self.edges:
            if f in idx and t in idx:
                adj[idx[f]][idx[t]] = 1.0
        return adj

    def ready_processes(self, ctx) -> list:
        return [pc for pc in self.nodes
                if pc not in ctx.done_set
                and is_process_ready(pc, ctx) == ReadyStatus.READY]

class ReadyStatus(Enum):
    READY       = 'ready'
    WAIT_PRED   = 'wait_pred'
    WAIT_STOCK  = 'wait_stock'
    WAIT_WORKER = 'wait_worker'
    UNKNOWN_PC  = 'unknown_pc'

@dataclass
class ReadyContext:
    kg       : 'ProcessKnowledgeGraph'
    done_set : set
    wh       : 'Warehouse'
    wres     : dict
    data     : object
    model_id : str

def resolve_worker_group(pc: str, node: dict) -> str:
    wgrp = str(node.get('worker_group', '') or '')
    grp  = str(node.get('process_group', '') or '')
    if wgrp == 'WORKER_SET' and grp == 'SET':
        if str(pc).rsplit('_', 1)[-1].upper() == 'INSP':
            wgrp = 'WORKER_SET_INSP'
    return wgrp

def is_process_ready(pc: str, ctx: ReadyContext) -> ReadyStatus:
    pc = str(pc)
    if pc not in ctx.kg.nodes:
        return ReadyStatus.UNKNOWN_PC
    node = ctx.kg.nodes[pc]

    preds = [p for (p, t, _) in ctx.kg.edges if t == pc]
    if not all(p in ctx.done_set for p in preds):
        return ReadyStatus.WAIT_PRED

    for code, qty in ctx.data.get_bom_parts(ctx.model_id, pc):
        if ctx.wh.stock[str(code)] < qty:
            return ReadyStatus.WAIT_STOCK

    wgrp = resolve_worker_group(pc, node)
    if wgrp:
        res = ctx.wres.get(wgrp)
        if res is None or res.count >= res.capacity:
            return ReadyStatus.WAIT_WORKER

    return ReadyStatus.READY

def ready_processes_with_status(ctx: ReadyContext) -> dict:
    out = {st: [] for st in ReadyStatus}
    for pc in ctx.kg.nodes:
        if pc in ctx.done_set:
            continue
        out[is_process_ready(pc, ctx)].append(pc)
    return out

class Warehouse:
    def __init__(self, data, order: dict):
        self.data    = data
        self.order   = order
        total_qty    = sum(order.values())

        bom_codes             = data.get_all_bom_codes()
        self._bom_codes       = bom_codes
        self._bom_init_stock  = WAREHOUSE_BOM_INIT_FLOOR
        self._init_stock      = float(total_qty * WAREHOUSE_NONBOM_INIT_MULT)

        demand = defaultdict(float)
        for model_id, qty in order.items():
            try:
                procs = data.get_model_procs(model_id)
            except Exception:
                continue
            for _, row in procs.iterrows():
                pc = str(row['process_code'])
                for ic, q in data.get_bom_parts(model_id, pc):
                    demand[str(ic)] += float(q) * int(qty)

        self.stock = defaultdict(lambda: self._init_stock)
        self._demand = dict(demand)
        self._initial_stocks = {}
        for code in bom_codes:
            d   = demand.get(str(code), 0.0)
            init = max(WAREHOUSE_BOM_INIT_FLOOR, int(d * BOM_INITIAL_RATIO))
            self.stock[str(code)] = float(init)
            self._initial_stocks[str(code)] = init

        for model_id, qty in order.items():
            main_pcb = self.data.pcb_map.get(model_id)
            if main_pcb is not None:
                self.stock[str(main_pcb)] = float(int(qty * PCB_INITIAL_RATIO))
            for tht_pcb in self.data.tht_pcb_by_model.get(model_id, []):
                self.stock[str(tht_pcb)] = float(int(qty * PCB_INITIAL_RATIO))

        for pcb_code in {c for codes in self.data.tht_pcb_by_model.values() for c in codes}:
            self.stock[tht_raw_code(pcb_code)] = 0.0

        self.consumed        = defaultdict(int)
        self.violations      = defaultdict(int)
        self.history         = defaultdict(list)
        self._pending_orders = set()
        self._wait_events    = defaultdict(list)
        self.snapshots       = defaultdict(list)
        self.reorder_log     = []
        self.reorder_count   = defaultdict(int)

        self._pcb_codes          = (set(self.data.pcb_map.values())
                                    | {c for codes in self.data.tht_pcb_by_model.values()
                                       for c in codes})
        self.outsource_log       = []
        self.unit_completions    = {}
        self.smt_per_model       = defaultdict(int)
        self.pcb_flow            = defaultdict(lambda: defaultdict(int))
        self.skipped_pcs         = defaultdict(int)
        self.smt_model_choices   = []
        self.kg_incomplete_log   = []
        self.smt_single_side_log = []
        self.stuck_wait_log      = []

    def consume(self, item_code, qty, sim_time=0):
        c = str(item_code)
        self.stock[c] = max(0, self.stock[c] - int(qty))
        self.consumed[c] += int(qty)
        if not c.endswith(THT_RAW_SUFFIX):
            is_pcb = c in self._pcb_codes
            if (not is_pcb
                    and self.stock[c] < self.data.get_min_stock(c)
                    and c not in self._pending_orders):
                self._pending_orders.add(c)
                self.snapshots[c].append((sim_time, self.stock[c]))
            if self.stock[c] < self.data.get_critical_stock(c):
                self.violations[c] += 1
        self.history[c].append((sim_time, self.stock[c]))

    def restore(self, item_code, qty, sim_time=0):
        c = str(item_code)
        self.stock[c] += int(qty)
        self.history[c].append((sim_time, self.stock[c]))
        if c.endswith(THT_RAW_SUFFIX):
            base = c[:-len(THT_RAW_SUFFIX)]
            self.pcb_flow[base]['outsource_in'] += int(qty)
        elif c in self._pcb_codes:
            self.pcb_flow[c]['restore_from_smt_or_outsource'] += int(qty)
        self._notify_waiters(c)

    def wait_stock(self, env, item_code, qty, max_wait_sec=None):
        if max_wait_sec is None:
            max_wait_sec = MAX_DAYS * (
                _active_schedule['work_end_sec']
                - _active_schedule['work_start_sec']
                - _active_schedule['break_duration_sec']
            )
        c = str(item_code)
        blocked = False
        start_t = float(env.now)
        while self.stock[c] < qty:
            if not blocked and not c.endswith(THT_RAW_SUFFIX):
                self.violations[c] += 1
                blocked = True
            ev = env.event()
            self._wait_events[c].append(ev)
            remaining = max_wait_sec - (env.now - start_t)
            if remaining <= 0:
                break
            timeout_ev = env.timeout(remaining)
            result = yield env.any_of([ev, timeout_ev])
            if timeout_ev in result and ev not in result:
                self.stuck_wait_log.append({
                    'item_code'    : c,
                    'qty'          : int(qty),
                    'wait_start_h' : start_t / 3600,
                    'wait_end_h'   : float(env.now) / 3600,
                    'stock_at_end' : float(self.stock[c]),
                })
                self.consume(c, qty, env.now)
                return
        self.consume(c, qty, env.now)

    def _notify_waiters(self, item_code):
        c = str(item_code)
        for ev in self._wait_events.pop(c, []):
            if not ev.triggered:
                ev.succeed()

    def stock_penalty(self):
        return sum(self.violations.values())

    def _lot_for(self, item_code):
        c = str(item_code)
        d = self._demand.get(c, 0.0)
        if d > 0:
            return max(WAREHOUSE_BOM_LOT_FLOOR, int(d * BOM_LOT_RATIO))
        return int(self.data.get_lot_size(c))

    def replenish(self, item_code, sim_time=0, order_time=None, stock_at_order=None):
        c = str(item_code)
        if c.endswith(THT_RAW_SUFFIX):
            return
        if c in self._pcb_codes:
            self._pending_orders.discard(c)
            return
        lot      = self._lot_for(c)
        min_s    = self.data.get_min_stock(c)
        incoming = max(lot, int(min_s) - self.stock[c] + lot)
        self.stock[c] += incoming
        self._pending_orders.discard(c)
        self.history[c].append((sim_time, self.stock[c]))
        is_pcb = c in self._pcb_codes
        self.reorder_log.append({
            'item_code'     : c,
            'order_time'    : float(order_time) if order_time is not None else float(sim_time),
            'arrive_time'   : float(sim_time),
            'lot_size'      : int(lot),
            'incoming'      : int(incoming),
            'stock_at_order': (int(stock_at_order) if stock_at_order is not None
                               else int(self.stock[c] - incoming)),
            'is_pcb'        : is_pcb,
        })
        self.reorder_count[c] += 1
        if is_pcb:
            self.pcb_flow[c]['external_replenish_arrived'] += 1
        self._notify_waiters(c)

    def snapshot_loop(self, env, interval=3600):
        tracked = set()
        try:
            for c in self.data.iter_all_bom_items():
                tracked.add(c)
        except AttributeError:
            pass
        while True:
            yield env.timeout(interval)
            tracked.update(self.stock.keys())
            now = env.now
            for c in tracked:
                q = self.stock[c]
                self.snapshots[c].append((now, int(q)))

class WIPTracker:
    def __init__(self, order: dict):
        self.wip  = defaultdict(int)
        self.cap  = defaultdict(int)
        self.viol = defaultdict(int)
        self.history = defaultdict(list)
        self.snapshots = defaultdict(list)
        total = sum(order.values())
        for grp in ['MODULE','SEMI','SET','INSP','PACK','SMT']:
            self.cap[grp] = max(int(total * WIP_CAP_RATIO * 3), 10)

    def enter(self, grp):
        self.wip[grp] += 1
        if self.wip[grp] > self.cap.get(grp, 9999):
            self.viol[grp] += 1

    def leave(self, grp):
        self.wip[grp] = max(0, self.wip[grp] - 1)

    def violations(self):
        return sum(self.viol.values())

    def snapshot_loop(self, env, interval=3600):
        tracked_grps = ['SMT', 'MODULE', 'SEMI', 'SET', 'INSP', 'PACK', 'RMA']
        while True:
            yield env.timeout(interval)
            now = env.now
            for grp in tracked_grps:
                self.snapshots[grp].append((now, int(self.wip.get(grp, 0))))

class EnergyLogger:
    def __init__(self, data):
        self.data   = data
        self.by_pc  = defaultdict(float)
        self.by_grp = defaultdict(float)
        self.total  = 0.0
        self.history = []

    def record(self, pc, grp, ct, sim_time=0, capacity=None):
        if capacity is None:
            wgrp = PROCESS_GROUP_TO_WORKER_GROUP.get(str(grp))
            if wgrp:
                capacity = int(self.data.workers.get(wgrp, 1))
            else:
                capacity = 1
        kw  = self.data.get_kw(pc, grp, capacity)
        kwh = kw * float(ct) / 3600
        self.by_pc[pc]   += kwh
        self.by_grp[grp] += kwh
        self.total       += kwh
        self.history.append((sim_time, self.total))
        return kwh

    def report(self):
        print('\n[공정그룹별 전력 소비 (kWh)]')
        print(f'  {"그룹":12s} {"kWh":>10s}')
        for g in sorted(self.by_grp):
            print(f'  {g:12s} {self.by_grp[g]:>10.4f}')
        print(f'  {"합계":12s} {self.total:>10.4f}')

class IdleTracker:
    def __init__(self):
        self._capacity     = {}
        self._active       = defaultdict(int)
        self._last_t       = defaultdict(float)
        self.total_idle    = defaultdict(float)
        self.absent_groups = set()
        self._completed_at = {}
        self._completion_target  = {}
        self._completion_counter = defaultdict(int)
        self._last         = {}

    def configure(self, capacity_map: dict):
        for g, cap in capacity_map.items():
            self._capacity[g] = int(cap)
            self._active.setdefault(g, 0)
            self._last_t.setdefault(g, 0.0)

    def set_target(self, g: str, target: int):
        if target > 0:
            self._completion_target[g] = int(target)

    def _flush(self, env, g):
        now = float(env.now)
        last = self._last_t.get(g, 0.0)
        if g not in self._capacity:
            self._last_t[g] = now
            return
        if now <= last:
            return
        cap    = self._capacity[g]
        active = self._active.get(g, 0)
        idle_workers = max(cap - active, 0)
        completed = self._completed_at.get(g)
        if completed is not None and last >= completed:
            self._last_t[g] = now
            return
        eff_end = now if completed is None else min(now, completed)
        if eff_end > last and idle_workers > 0:
            self.total_idle[g] += idle_workers * _work_seconds_between(last, eff_end)
        self._last_t[g] = now

    def flush_all(self, env):
        for g in list(self._capacity.keys()):
            self._flush(env, g)

    def acquire(self, env, g):
        if g not in self._capacity:
            self._capacity[g] = 1
            self._last_t.setdefault(g, float(env.now))
        self._flush(env, g)
        self._active[g] = self._active.get(g, 0) + 1

    def release(self, env, g):
        if g not in self._capacity:
            return
        self._flush(env, g)
        self._active[g] = max(self._active.get(g, 0) - 1, 0)
        self._completion_counter[g] += 1
        target = self._completion_target.get(g)
        if (target is not None
                and self._completion_counter[g] >= target
                and g not in self._completed_at):
            self._completed_at[g] = float(env.now)

    def mark_busy(self, env, name):
        now = env.now
        if name in self._last:
            self.total_idle[name] += _work_seconds_between(self._last[name], now)
        self._last[name] = now

    def mark_completed(self, wgrp: str, sim_time: float):
        existing = self._completed_at.get(wgrp)
        if existing is None or sim_time > existing:
            self._completed_at[wgrp] = float(sim_time)

    def worker_idle_penalty(self, threshold=300):
        total = 0.0
        for name in self._capacity:
            if name not in WORKER_GROUPS:
                continue
            v = self.total_idle.get(name, 0.0)
            if v > threshold:
                total += v
        return total

    def report(self):
        print('\n[작업자 유휴 시간 상위 10 (그룹 person·hh:mm:ss)]')
        workers = {k: v for k, v in self.total_idle.items() if k in WORKER_GROUPS}
        for n, v in sorted(workers.items(), key=lambda x: -x[1])[:10]:
            cap  = self._capacity.get(n, 1)
            flag = ' <- 임계초과' if v > 1800 * cap else ''
            sec = int(max(v, 0))
            h, rem = divmod(sec, 3600)
            mm, ss = divmod(rem, 60)
            print(f'  {n:25s}(cap={cap:2d}): {h:02d}:{mm:02d}:{ss:02d}{flag}')

class SolderCream:
    def __init__(self, env, name):
        self.env       = env
        self.name      = name
        self.stock_g   = SOLDER_G
        self.open_time = None

    def use(self):
        if self.open_time is None:
            self.open_time = self.env.now
        if self.env.now - self.open_time >= SOLDER_VALID_SEC:
            self.stock_g   = SOLDER_G
            self.open_time = self.env.now
        self.stock_g -= SOLDER_USE_G
        if self.stock_g <= 0:
            self.stock_g   = SOLDER_G
            self.open_time = self.env.now

class OutsourceTruckPool:

    def __init__(self, env, wh, stats, smt_lines_ref):
        self.env = env
        self.wh = wh
        self.stats = stats
        self.smt_lines = smt_lines_ref
        self.truck = []
        self.dispatched_count = 0
        self.in_transit = []
        self.truck_log = []

    def add_board(self, line_sid, pcb_code, model_id, board_id):
        raw_code = tht_raw_code(pcb_code)
        self.wh.restore(raw_code, 1, self.env.now)
        self.stats['tht_out'] = self.stats.get('tht_out', 0) + 1
        ev_idx = len(self.wh.outsource_log)
        self.wh.outsource_log.append({
            'pcb_code'    : pcb_code,
            'model_id'    : model_id,
            'board_id'    : board_id,
            'send_time'   : float(self.env.now),
            'return_time' : None,
            'delay_sec'   : 0.0,
            'status'      : 'queued',
        })
        self.truck.append({
            'pcb_code': pcb_code,
            'model_id': model_id,
            'board_id': board_id,
            'line_sid': line_sid,
            'ev_idx'  : ev_idx,
        })

    def flush_now(self):
        if self.truck:
            self._dispatch()

    def _dispatch(self):
        truck = self.truck
        self.truck = []
        delay = 0.0
        if random.random() < THT_DELAY_PROB:
            delay = random.uniform(THT_DELAY_MIN_SEC, THT_DELAY_MAX_SEC)
            _log_event(self.env.now,
                       f'THT 외주 트럭 납기 지연: {len(truck)}보드 +{delay/3600:.1f}h')
        send_t = float(self.env.now)
        for entry in truck:
            log = self.wh.outsource_log[entry['ev_idx']]
            log['send_time'] = send_t
            log['delay_sec'] = float(delay)
            log['status']    = 'in_flight'
        eta = send_t + THT_OUTSOURCE_SEC + delay
        self.dispatched_count += 1
        breakdown = defaultdict(int)
        for entry in truck:
            breakdown[entry['pcb_code']] += 1
        truck_log_entry = {
            'dispatch_id'  : self.dispatched_count,
            'send_t'       : send_t,
            'eta'          : eta,
            'delay_sec'    : float(delay),
            'size'         : len(truck),
            'breakdown'    : dict(breakdown),
            'truck_count'  : max(1, (len(truck) + TRUCK_SIZE - 1) // TRUCK_SIZE),
            'return_t'     : None,
        }
        self.truck_log.append(truck_log_entry)
        transit_meta = {'size': len(truck), 'send_t': send_t, 'eta': eta,
                        'log_entry': truck_log_entry}
        self.in_transit.append(transit_meta)
        _log_event(self.env.now,
                   f'THT 외주 convoy #{self.dispatched_count} 출발: '
                   f'{len(truck)}보드 (트럭 환산 {truck_log_entry["truck_count"]}대, '
                   f'도착 +{(eta - send_t)/3600:.1f}h)')
        self.env.process(self._truck_arrive(truck, delay, transit_meta))

    def _truck_arrive(self, truck, delay, transit_meta):
        yield self.env.timeout(THT_OUTSOURCE_SEC + delay)
        try:
            self.in_transit.remove(transit_meta)
        except ValueError:
            pass
        log_entry = transit_meta.get('log_entry')
        if log_entry is not None:
            log_entry['return_t'] = float(self.env.now)
        for entry in truck:
            pcb_code = entry['pcb_code']
            line_sid = entry['line_sid']
            line = self.smt_lines.get(line_sid)
            raw_code = tht_raw_code(pcb_code)
            self.wh.consume(raw_code, 1, self.env.now)
            log = self.wh.outsource_log[entry['ev_idx']]
            log['return_time'] = float(self.env.now)
            log['status']      = 'returned'
            self.wh.pcb_flow[pcb_code]['outsource_returned'] += 1
            if line is None:
                self.wh.restore(pcb_code, 1, self.env.now)
                continue
            line.mag_buf[pcb_code] += 1
            in_flight = (self.wh.pcb_flow[pcb_code].get('outsource_in', 0)
                         - self.wh.pcb_flow[pcb_code].get('outsource_returned', 0))
            if line.mag_buf[pcb_code] >= MAG_SIZE:
                flush = MAG_SIZE
            elif in_flight == 0 and line.mag_buf[pcb_code] > 0:
                flush = line.mag_buf[pcb_code]
            else:
                flush = 0
            if flush > 0:
                line.mag_buf[pcb_code] -= flush
                self.wh.restore(pcb_code, flush, self.env.now)
                line.pcb_count[pcb_code] += flush
                self.stats['pcb_done'] = self.stats.get('pcb_done', 0) + flush
                self.wh.smt_per_model[(line_sid, entry['model_id'], pcb_code)] += flush
        _log_event(self.env.now, f'THT 외주 트럭 도착: {len(truck)}보드')

class SMTLine:
    def __init__(self, env, suffix, data, wh,
                 aoi_res, rma_store, energy, idle, wip, stats, broken_flag,
                 outsource_pool=None):
        self.env          = env
        self.sfx          = suffix
        self.data         = data
        self.wh           = wh
        self.aoi_res      = aoi_res
        self.rma          = rma_store
        self.outsource_pool = outsource_pool
        self.energy       = energy
        self.idle         = idle
        self.wip          = wip
        self.stats        = stats
        self.broken_flag  = broken_flag
        self.solder       = SolderCream(env, f'SMT_{suffix}')
        self.mag_buf      = defaultdict(int)
        self.assigned_model = None
        self._res = {pc: simpy.Resource(env, capacity=1) for pc in [
            f'SMT_LOADER_{suffix}',    f'SMT_PRINTER_{suffix}',
            f'SMT_SPI_{suffix}',       f'SMT_MOUNTER_H_{suffix}',
            f'SMT_MOUNTER_M_{suffix}', f'SMT_REFLOW_{suffix}',
            f'SMT_UNLOADER_{suffix}']}
        self.pcb_count = defaultdict(int)
        self.stage_active = {}
        self.stage_events = []

    def process_board(self, pcb_code, board_id, model_id, is_second=False):
        seq = [f'SMT_LOADER_{self.sfx}',    f'SMT_PRINTER_{self.sfx}',
               f'SMT_SPI_{self.sfx}',       f'SMT_MOUNTER_H_{self.sfx}',
               f'SMT_MOUNTER_M_{self.sfx}', f'SMT_REFLOW_{self.sfx}',
               f'SMT_UNLOADER_{self.sfx}']

        self.wip.enter('SMT')
        board_has_defect = False
        for pc in seq:
            pr = self.data.get_proc(pc)
            if pr is None:
                yield self.env.timeout(0.001)
                continue
            ct = float(pr['cycle_time_sec'] or 0.001)
            tt = float(pr['transfer_time_sec'] or 0)
            dr = float(pr['defect_rate'] or DEFECT_FLOOR)

            if not _is_work_time(self.env.now):
                yield self.env.timeout(_next_work_start(self.env.now) - self.env.now)

            while self.broken_flag.get(pc, False):
                yield self.env.timeout(60)

            self.idle.mark_busy(self.env, pc)
            with self._res[pc].request() as req:
                yield req
                _start_t = float(self.env.now)
                self.stage_active[pc] = (pcb_code, board_id, is_second)
                try:
                    act = max(random.normalvariate(ct, ct * CT_STD_RATIO), ct * 0.5)
                    yield self.env.timeout(act)
                finally:
                    self.stage_active.pop(pc, None)
                    self.stage_events.append({
                        'pc': pc, 'pcb_code': pcb_code,
                        'model_id': model_id, 'board_id': board_id,
                        'is_second': is_second,
                        'start': _start_t, 'end': float(self.env.now),
                    })
            self.energy.record(pc, 'SMT', act, self.env.now)
            if 'PRINTER' in pc:
                self.solder.use()
            if tt > 0:
                yield self.env.timeout(tt)
            if random.random() < dr:
                self.stats['smt_defect'] += 1
                board_has_defect = True

        aoi = self.data.get_proc('SMT_AOI')
        aoi_ct = float(aoi['cycle_time_sec'] or 30)
        aoi_dr = float(aoi['defect_rate'] or DEFECT_FLOOR)

        if not _is_work_time(self.env.now):
            yield self.env.timeout(_next_work_start(self.env.now) - self.env.now)

        self.idle.mark_busy(self.env, 'SMT_AOI')
        with self.aoi_res.request() as req:
            yield req
            _aoi_start_t = float(self.env.now)
            self.stage_active['SMT_AOI'] = (pcb_code, board_id, is_second)
            try:
                yield self.env.timeout(aoi_ct)
            finally:
                self.stage_active.pop('SMT_AOI', None)
                self.stage_events.append({
                    'pc': 'SMT_AOI', 'pcb_code': pcb_code,
                    'model_id': model_id, 'board_id': board_id,
                    'is_second': is_second,
                    'start': _aoi_start_t, 'end': float(self.env.now),
                })
        self.energy.record('SMT_AOI', 'SMT_SHARED', aoi_ct, self.env.now)
        detected = board_has_defect and (random.random() < aoi_dr)
        if detected:
            self.stats['aoi_defect'] += 1
            self.wip.leave('SMT')
            yield self.rma.put({'src':'AOI','board':board_id,
                                'pcb':pcb_code,'grp':'SMT_SHARED','model':model_id})
            return

        self.wip.leave('SMT')

        side = self.data.smt_side(pcb_code)
        if not is_second and side == 'double':
            self.wh.pcb_flow[pcb_code]['double_first_pass'] += 1
            yield self.env.process(
                self.process_board(pcb_code, board_id, model_id,
                                    is_second=True))
            return

        if side == 'double' and not is_second:
            self.wh.smt_single_side_log.append({
                'pcb_code': pcb_code, 'model_id': model_id,
                'board_id': board_id, 'time_h': self.env.now/3600,
                'reason': 'double_pcb_flushed_without_second_pass',
            })

        if pcb_code in {c for codes in self.data.tht_pcb_by_model.values() for c in codes}:
            if self.outsource_pool is not None:
                self.outsource_pool.add_board(self.sfx, pcb_code, model_id, board_id)
            else:
                self.wh.restore(pcb_code, 1, self.env.now)
            return

        self.mag_buf[pcb_code] += 1
        if self.mag_buf[pcb_code] >= MAG_SIZE:
            self.mag_buf[pcb_code] -= MAG_SIZE
            self.wh.restore(pcb_code, MAG_SIZE, self.env.now)
            self.pcb_count[pcb_code] += MAG_SIZE
            self.stats['pcb_done'] += MAG_SIZE
            self.wh.smt_per_model[(self.sfx, model_id, pcb_code)] += MAG_SIZE

def _is_work_time(sim_now_sec):
    _s = _active_schedule
    t  = sim_now_sec % DAY_SEC
    if not (_s['work_start_sec'] <= t < _s['work_end_sec']):
        return False
    if _s['lunch_start_sec'] <= t < _s['lunch_end_sec']:
        return False
    return True

def _next_work_start(sim_now_sec):
    _s      = _active_schedule
    day_num = int(sim_now_sec // DAY_SEC)
    t       = sim_now_sec % DAY_SEC
    if _s['lunch_start_sec'] <= t < _s['lunch_end_sec']:
        return day_num * DAY_SEC + _s['lunch_end_sec']
    if t < _s['work_start_sec']:
        return day_num * DAY_SEC + _s['work_start_sec']
    return (day_num + 1) * DAY_SEC + _s['work_start_sec']

def work_timeout(env, duration):
    _s        = _active_schedule
    remaining = float(max(duration, 0))
    while remaining > 1e-6:
        if not _is_work_time(env.now):
            yield env.timeout(_next_work_start(env.now) - env.now)
            continue
        t = env.now % DAY_SEC
        if t < _s['lunch_start_sec']:
            next_boundary = env.now - t + _s['lunch_start_sec']
        else:
            next_boundary = env.now - t + _s['work_end_sec']
        chunk = min(remaining, max(next_boundary - env.now, 0))
        if chunk <= 0:
            yield env.timeout(_next_work_start(env.now) - env.now)
            continue
        yield env.timeout(chunk)
        remaining -= chunk

def _work_seconds_between(start_sec, end_sec):
    _s = _active_schedule
    if end_sec <= start_sec:
        return 0.0
    total = 0.0
    t     = float(start_sec)
    end   = float(end_sec)
    while t < end:
        if not _is_work_time(t):
            nxt = _next_work_start(t)
            if nxt >= end:
                break
            t = nxt
            continue
        day_t = t % DAY_SEC
        if day_t < _s['lunch_start_sec']:
            boundary = t - day_t + _s['lunch_start_sec']
        else:
            boundary = t - day_t + _s['work_end_sec']
        chunk = min(end, boundary) - t
        if chunk > 0:
            total += chunk
        t = min(end, boundary)
    return total

def run_process(env, prow, done_ev, wres, wh, rma, energy,
                idle, wip, stats, mid, data, plogger=None, uid=0,
                unit_defect_flag=None, progress=None):
    pc    = str(prow['process_code'])
    grp   = str(prow.get('process_group','') or '')
    ct    = float(prow['cycle_time_sec'] or 0)
    dr    = float(prow['defect_rate'] or DEFECT_FLOOR)
    tt    = float(prow['transfer_time_sec'] or 0)
    whr   = float(prow['dep_wait_hr'] or 0)
    wgrp  = str(prow.get('worker_group','') or '')
    dtype = str(prow.get('dep_type','SEQUENCE') or 'SEQUENCE').upper()
    prevs = [p.strip() for p in
             str(prow.get('dep_prev_codes','') or '').split(';') if p.strip()]

    if wgrp == 'WORKER_SET' and grp == 'SET':
        if pc.rsplit('_', 1)[-1].upper() == 'INSP':
            wgrp = 'WORKER_SET_INSP'

    skill_base   = data.worker_skill.get(wgrp, 2)
    skill_actual = max(1, skill_base - (1 if wgrp in idle.absent_groups else 0))
    ct = ct * data.skill_ct.get(skill_actual, 1.0)
    dr = dr * data.skill_dr.get(skill_actual, 1.0)

    if prevs:
        wait_evs = [done_ev[p] for p in prevs if p in done_ev]
        if dtype == 'JOIN':
            if wait_evs:
                yield simpy.AllOf(env, wait_evs)
        elif wait_evs:
            yield wait_evs[0]

    if whr > 0:
        yield env.timeout(whr * 3600)
    if tt > 0:
        yield env.timeout(tt)

    if not _is_work_time(env.now):
        yield env.timeout(_next_work_start(env.now) - env.now)

    wip.enter(grp)
    for item_code, qty in data.get_bom_parts(mid, pc):
        yield from wh.wait_stock(env, item_code, qty)

    res = wres.get(wgrp)
    req = res.request() if res else None
    acquired = False
    if req:
        yield req
        idle.acquire(env, wgrp)
        acquired = True

    logger_started = False
    ev_id_p = None
    try:
        if plogger is not None:
            _cap = res.capacity if res is not None else 1
            ev_id_p = plogger.mark_start(pc, mid, uid, env.now, grp,
                                         wgrp=wgrp, cap=_cap,
                                         work_timed=True)
            logger_started = True
        act = max(random.normalvariate(ct, ct * CT_STD_RATIO), ct * 0.5) if ct > 0 else 0.001
        yield from work_timeout(env, act)
        energy.record(pc, grp, act, env.now)
        _is_insp = (grp == 'SET' and pc.rsplit('_', 1)[-1].upper() == 'INSP')

        if _is_insp:
            has_prior_defect = (unit_defect_flag is not None
                                and unit_defect_flag.get(uid, False))
            detected = has_prior_defect and (random.random() < dr)
            if detected:
                stats['assy_defect'] = stats.get('assy_defect', 0) + 1
                if unit_defect_flag is not None:
                    unit_defect_flag[uid] = False
                    unit_defect_flag['_routed_to_rma'] = True
                wip.leave(grp)
                yield rma.put({'src': pc, 'grp': grp, 'model': mid,
                               'uid': uid,
                               'progress': progress})
                if req and res:
                    if acquired:
                        idle.release(env, wgrp)
                        acquired = False
                    res.release(req)
                ev = done_ev.get(pc)
                if ev and not ev.triggered:
                    ev.succeed()
                return
        else:
            if random.random() < dr:
                stats['assy_defect'] = stats.get('assy_defect', 0) + 1
                if unit_defect_flag is not None:
                    unit_defect_flag[uid] = True
    finally:
        if plogger is not None and logger_started:
            try:
                plogger.mark_end(pc, env.now, ev_id_p)
            except Exception:
                pass
        if req and res:
            try:
                if acquired:
                    idle.release(env, wgrp)
                    acquired = False
                res.release(req)
            except Exception:
                pass

    wip.leave(grp)
    ev = done_ev.get(pc)
    if ev and not ev.triggered:
        ev.succeed()

def run_rma(env, rma, wres, wh, energy, idle, wip, stats, data,
            progress=None, plogger=None):
    while True:
        item = yield rma.get()
        src = str(item.get('src', ''))
        if src == 'AOI':
            if AOI_DEFECT_ACTION == 'repair':
                env.process(_rma_repair_aoi_board(
                    env, item, wres, wh, energy, idle, wip, stats, data))
                continue
            else:
                stats['smt_rma_scrap'] = stats.get('smt_rma_scrap', 0) + 1
                _log_event(env.now,
                           f'AOI 보드 불량 폐기: pcb={item.get("pcb","")} '
                           f'model={item.get("model","")} '
                           f'board={item.get("board","")}')
                continue
        env.process(_rma_repair_and_reinsert(
            env, item, wres, wh, energy, idle, wip, stats, data,
            progress=progress, plogger=plogger))

def _rma_repair_aoi_board(env, item, wres, wh, energy, idle, wip, stats, data):
    pcb_code = str(item.get('pcb', ''))
    model    = str(item.get('model', ''))
    res = wres.get('WORKER_RMA')
    req = res.request() if res else None
    acquired = False
    try:
        if req:
            yield req
            idle.acquire(env, 'WORKER_RMA')
            acquired = True
        rt = max(random.normalvariate(RMA_REPAIR_TIME_MEAN_SEC,
                                       RMA_REPAIR_TIME_STD_SEC),
                 RMA_REPAIR_TIME_MIN_SEC)
        yield from work_timeout(env, rt)
        energy.record('RMA_REPAIR', 'RMA', rt, env.now)
        stats['aoi_repaired'] = stats.get('aoi_repaired', 0) + 1

        if pcb_code:
            for part_code, part_qty in data.get_pcb_parts(pcb_code):
                yield from wh.wait_stock(env, part_code, part_qty)
            wh.restore(pcb_code, 1, env.now)
        _log_event(env.now,
                   f'AOI 불량 수리 완료 → PCB 재투입: pcb={pcb_code} model={model}')
    finally:
        if req:
            if acquired:
                idle.release(env, 'WORKER_RMA')
            res.release(req)

def _sample_defective_predecessor(data, model_id, src_pc):
    try:
        procs = data.get_model_procs(model_id)
    except Exception:
        return None
    prow_map = {str(r['process_code']): r for _, r in procs.iterrows()}

    visited = set()
    queue = [str(src_pc)]
    candidates = []
    while queue:
        cur = queue.pop(0)
        prow = prow_map.get(cur)
        if prow is None:
            continue
        prevs = [p.strip() for p in
                 str(prow.get('dep_prev_codes', '') or '').split(';') if p.strip()]
        for prev in prevs:
            if prev in visited:
                continue
            visited.add(prev)
            queue.append(prev)
            prev_row = prow_map.get(prev)
            if prev_row is None:
                continue
            grp  = str(prev_row.get('process_group', '') or '')
            wgrp = str(prev_row.get('worker_group', '') or '')
            if grp not in ('MODULE', 'SEMI', 'SET'):
                continue
            if prev.rsplit('_', 1)[-1].upper() == 'INSP':
                continue
            if wgrp == 'WORKER_SET_INSP':
                continue
            candidates.append(prev_row)

    if not candidates:
        return None
    weights = [max(float(c.get('defect_rate', 0) or 0), 0.0) for c in candidates]
    if sum(weights) <= 0:
        return None
    chosen = random.choices(candidates, weights=weights, k=1)[0]
    return str(chosen['process_code'])

def _rma_repair_and_reinsert(env, item, wres, wh, energy, idle, wip, stats, data,
                             progress=None, plogger=None):
    if not _is_work_time(env.now):
        yield env.timeout(_next_work_start(env.now) - env.now)

    res = wres.get('WORKER_RMA')
    req = res.request() if res else None
    acquired = False
    if req:
        yield req
        idle.acquire(env, 'WORKER_RMA')
        acquired = True

    model    = item.get('model', '')
    src_pc   = item.get('src', '')
    rma_uid  = int(item.get('uid', 0))
    progress = item.get('progress') or progress or {}
    pc_rma   = 'RMA_REPAIR'
    ev_id_p  = None

    try:
        if plogger is not None:
            _cap = res.capacity if res is not None else 1
            ev_id_p = plogger.mark_start(pc_rma, model or '-', rma_uid,
                                         env.now, 'RMA',
                                         wgrp='WORKER_RMA', cap=_cap,
                                         work_timed=True)
        rt = max(random.normalvariate(RMA_REPAIR_TIME_MEAN_SEC,
                                       RMA_REPAIR_TIME_STD_SEC),
                 RMA_REPAIR_TIME_MIN_SEC)
        yield from work_timeout(env, rt)
        energy.record('RMA_REPAIR', 'RMA', rt, env.now)
        stats['rma_repaired'] = stats.get('rma_repaired', 0) + 1

        if src_pc:
            sampled_pc = _sample_defective_predecessor(data, model, src_pc)
            if sampled_pc:
                for part_code, part_qty in data.get_bom_parts(model, sampled_pc):
                    yield from wh.wait_stock(env, part_code, part_qty)
                _log_event(env.now,
                           f'RMA 추정 결함공정={sampled_pc} → BOM 한 세트 재소모')

        _log_event(env.now, f'RMA 수리 완료: {src_pc} ({model}) -> PACK 진입')
    finally:
        if plogger is not None and ev_id_p is not None:
            try:
                plogger.mark_end(pc_rma, env.now, ev_id_p)
            except Exception:
                pass
        if req and res:
            try:
                if acquired:
                    idle.release(env, 'WORKER_RMA')
                    acquired = False
                res.release(req)
            except Exception:
                pass

    pack_pc = _find_pack_entry(data, model)
    if pack_pc is None:
        _do_complete(stats, progress, model, env.now, wh=wh, src_pc=src_pc)
        return

    prow = data.get_proc(pack_pc)
    if prow is None:
        _do_complete(stats, progress, model, env.now, wh=wh, src_pc=src_pc)
        return

    done_ev_rma = {}
    pack_pcs = _get_pack_sequence(data, model, pack_pc)
    for p_pc in pack_pcs:
        p_prow = data.get_proc(p_pc)
        if p_prow is None:
            continue
        p_prow_copy = p_prow.copy()
        p_prow_copy['dep_prev_codes'] = ''
        p_prow_copy['dep_wait_hr']    = 0
        done_ev_rma[p_pc] = env.event()
        yield env.process(
            run_process(env, p_prow_copy, done_ev_rma, wres, wh,
                        simpy.Store(env), energy, idle, wip, stats, model, data,
                        plogger=plogger, uid=rma_uid,
                        unit_defect_flag=None,
                        progress=progress))

    _do_complete(stats, progress, model, env.now, wh=wh, src_pc=src_pc)

def _do_complete(stats, progress, model, now, wh=None, src_pc=None):
    if not model or model not in progress:
        return
    done, total = progress[model]
    if done >= total:
        if wh is not None:
            wh.unit_completions[('RMA', f'{model}_{src_pc}_{int(now)}')] = {
                'path': 'rma_blocked_by_quota',
                'end_time': float(now),
                'done_n': -1,
                'total_n': -1,
                'rma_count': 1,
            }
        return
    stats[f'{model}_done'] = stats.get(f'{model}_done', 0) + 1
    progress[model] = (done + 1, total)
    pct = (done + 1) / max(total, 1) * 100
    _log_event(now, f'{model} RMA->PACK 완성 ({pct:.0f}%)')
    if wh is not None:
        rma_idx = sum(1 for k in wh.unit_completions
                      if isinstance(k, tuple) and k[0] == model and
                      isinstance(k[1], str) and k[1].startswith('rma_'))
        wh.unit_completions[(model, f'rma_{rma_idx}')] = {
            'path': 'rma',
            'end_time': float(now),
            'done_n': -1,
            'total_n': -1,
            'rma_count': 1,
            'src_pc': str(src_pc) if src_pc else '',
        }

def _get_pack_sequence(data, model, first_pack_pc):
    result = [first_pack_pc]
    visited = {first_pack_pc}
    try:
        procs = data.get_model_procs(model)
    except Exception:
        return result

    next_map = {}
    for _, row in procs.iterrows():
        pc   = str(row['process_code'])
        prev = str(row.get('dep_prev_codes', '') or '')
        grp  = str(row.get('process_group', '') or '')
        if grp != 'PACK':
            continue
        for p in [x.strip() for x in prev.split(';') if x.strip()]:
            next_map[p] = pc
    cur = first_pack_pc
    while cur in next_map:
        nxt = next_map[cur]
        if nxt in visited:
            break
        result.append(nxt)
        visited.add(nxt)
        cur = nxt
    return result

def produce_unit(env, model_id, unit_id, data, kg,
                 wres, wh, rma, energy, idle, wip, stats, progress, menv=None,
                 plogger=None):
    done_ev = {pc: env.event() for pc in kg.nodes}

    pcs     = list(kg.nodes.keys())
    idx_map = {pc: i for i, pc in enumerate(pcs)}
    if menv is not None and hasattr(menv, '_H_cache'):
        H   = menv._H_cache[model_id]
        adj = menv._adj_cache[model_id]
    else:
        _, H_np = kg.get_feat_matrix()
        H   = torch.tensor(H_np,  dtype=torch.float32)
        adj = torch.tensor(kg.get_adj(), dtype=torch.float32)
    done_set = {'SMT_COMPLETE', 'SMT_THT'}
    kg_done  = set()
    kg_total = set(kg.nodes.keys())
    unit_defect_flag = {unit_id: False}

    unit_key = (model_id, unit_id)
    us = None
    if menv is not None and hasattr(menv, 'unit_states'):
        us = menv.unit_states
        us[unit_key] = {'state': 'SMT_WAIT', 'pc': '-', 'done_n': 0,
                        'total_n': len(kg.nodes), 'ready': []}

    ready_ctx = ReadyContext(
        kg=kg, done_set=done_set, wh=wh, wres=wres,
        data=data, model_id=model_id)
    while kg_done != kg_total:
        ready_pcs = kg.ready_processes(ready_ctx)

        if us is not None:
            us[unit_key].update({
                'done_n': len(kg_done),
                'ready': list(ready_pcs)[:5],
                'state': 'READY_WAIT' if not ready_pcs else 'RUNNING',
            })

        if not ready_pcs:
            yield env.timeout(1)
            continue

        if menv is not None and menv.agent is not None:
            s = menv.get_state()
            ready_mask = torch.zeros(len(pcs), dtype=torch.bool)
            for pc in ready_pcs:
                if pc in idx_map:
                    ready_mask[idx_map[pc]] = True
            a, lp, v, emb, mask_bytes = menv.agent.act(s, H, adj, ready_mask)
            next_pc = pcs[a] if (a < len(pcs) and ready_mask[a]) else ready_pcs[0]
            r = menv.reward()
            menv.agent.store(s, emb, a, r, lp, v, mask=mask_bytes, model_id=model_id)
        else:
            next_pc = ready_pcs[0]

        if us is not None:
            us[unit_key]['pc'] = next_pc

        prow = data.get_proc(next_pc)
        if prow is None:
            if menv is not None and hasattr(menv, 'wh'):
                menv.wh.skipped_pcs[(model_id, str(next_pc))] += 1
            done_set.add(next_pc)
            kg_done.add(next_pc)
            continue

        yield env.process(
            run_process(env, prow, done_ev, wres, wh, rma,
                        energy, idle, wip, stats, model_id, data,
                        plogger=plogger, uid=unit_id,
                        unit_defect_flag=unit_defect_flag,
                        progress=progress))

        done_set.add(next_pc)
        kg_done.add(next_pc)

        if unit_defect_flag.get('_routed_to_rma'):
            if us is not None:
                us[unit_key].update({'state': 'ROUTED_TO_RMA', 'pc': '-'})
            if menv is not None and hasattr(menv, 'wh'):
                menv.wh.unit_completions[(model_id, unit_id)] = {
                    'path': 'routed_to_rma',
                    'end_time': float(env.now),
                    'done_n': len(kg_done),
                    'total_n': len(kg_total),
                    'rma_count': 0,
                }
            return

    missing = kg_total - kg_done
    if missing:
        stats['kg_incomplete_units'] = stats.get('kg_incomplete_units', 0) + 1
        if menv is not None and hasattr(menv, 'wh'):
            menv.wh.kg_incomplete_log.append({
                'model_id': model_id, 'unit_id': unit_id,
                'time_h': float(env.now)/3600,
                'missing_pcs': sorted(missing),
            })
        _log_event(env.now,
                   f'[안전로직] {model_id} #{unit_id+1} 미처리 공정: '
                   f'{sorted(missing)}')

    if us is not None:
        us[unit_key].update({'state': 'DONE', 'pc': '-',
                             'done_n': len(kg_done)})

    if random.random() < OQC_RATE:
        if not _is_work_time(env.now):
            yield env.timeout(_next_work_start(env.now) - env.now)
        res = wres.get('WORKER_OQC')
        req = res.request() if res else None
        acquired = False
        if req:
            yield req
            idle.acquire(env, 'WORKER_OQC')
            acquired = True
        ev_id_oqc = None
        try:
            if plogger is not None:
                _cap = res.capacity if res is not None else 1
                ev_id_oqc = plogger.mark_start(
                    'OQC_SAMPLE', model_id, unit_id, env.now, 'OQC',
                    wgrp='WORKER_OQC', cap=_cap,
                    work_timed=True)
            yield from work_timeout(env, OQC_TIME_SEC)
            energy.record('OQC', 'INSP', OQC_TIME_SEC, env.now)
        finally:
            if plogger is not None and ev_id_oqc is not None:
                try:
                    plogger.mark_end('OQC_SAMPLE', env.now, ev_id_oqc)
                except Exception:
                    pass
            if req and res:
                if acquired:
                    idle.release(env, 'WORKER_OQC')
                    acquired = False
                res.release(req)
        stats['oqc_inspected'] = stats.get('oqc_inspected', 0) + 1

    done, total = progress[model_id]
    if done >= total:
        if menv is not None and hasattr(menv, 'wh'):
            menv.wh.unit_completions[(model_id, unit_id)] = {
                'path': 'normal_blocked_by_quota',
                'end_time': float(env.now),
                'done_n': len(kg_done),
                'total_n': len(kg_total),
                'rma_count': 0,
            }
        return
    stats[f'{model_id}_done'] = stats.get(f'{model_id}_done', 0) + 1
    progress[model_id] = (done + 1, total)
    pct = (done + 1) / total * 100
    _log_event(env.now, f'{model_id} #{unit_id+1} 완성 ({pct:.0f}%)')
    if done + 1 >= total and menv is not None:
        for _pc, node in kg.nodes.items():
            wgrp = node.get('worker_group', '')
            if wgrp:
                menv.idle.mark_completed(wgrp, float(env.now))
    if menv is not None and hasattr(menv, 'wh'):
        menv.wh.unit_completions[(model_id, unit_id)] = {
            'path': 'normal',
            'end_time': float(env.now),
            'done_n': len(done_set),
            'total_n': len(kg.nodes),
            'rma_count': 0,
        }

class ProcessActivityLogger:
    def __init__(self):
        self.log = {}
        self.current = {}
        self.groups = {}
        self.events = []
        self.slot_pool = {}
        self.max_slot  = {}
        self._active    = {}
        self._ev_counter = 0

    def _next_ev_id(self):
        self._ev_counter += 1
        return self._ev_counter

    def mark_start(self, pc, mid, uid, now, grp=None, wgrp=None, cap=None,
                   work_timed=False):
        c = str(pc)
        self.current[c] = (str(mid), int(uid), float(now))
        if grp:
            self.groups[c] = str(grp)
        ev_id = self._next_ev_id()
        meta = {
            'pc'        : c,
            'mid'       : str(mid),
            'uid'       : int(uid),
            'start'     : float(now),
            'wgrp'      : '',
            'slot'      : -1,
            'work_timed': bool(work_timed),
        }
        if wgrp:
            wg = str(wgrp)
            pool = self.slot_pool.setdefault(wg, [])
            target_cap = int(cap) if cap and cap > 0 else 1
            while len(pool) < target_cap:
                pool.append(None)
            slot_i = -1
            for i, v in enumerate(pool):
                if v is None:
                    slot_i = i
                    break
            if slot_i < 0:
                slot_i = len(pool)
                pool.append(None)
            pool[slot_i] = ev_id
            meta['wgrp'] = wg
            meta['slot'] = slot_i
            if slot_i + 1 > self.max_slot.get(wg, 0):
                self.max_slot[wg] = slot_i + 1
        self._active[ev_id] = meta
        return ev_id

    def mark_end(self, pc, now, ev_id=None):
        c = str(pc)
        self.current.pop(c, None)
        meta = None
        if ev_id is not None:
            meta = self._active.pop(ev_id, None)
        if meta is None:
            for eid, m in list(self._active.items()):
                if m['pc'] == c:
                    meta = self._active.pop(eid)
                    ev_id = eid
                    break
        if meta is None:
            return
        t_end = float(now)
        mid, uid, t0 = meta['mid'], meta['uid'], meta['start']
        label = f'{mid}/u{uid+1}'
        h_start = int(t0 // 3600)
        h_end   = int(t_end // 3600)
        if h_end < h_start:
            h_end = h_start
        self.log.setdefault(c, {})
        for h in range(h_start, h_end + 1):
            self.log[c].setdefault(h, []).append(label)
        self.events.append({
            'pc'        : c,
            'mid'       : mid,
            'uid'       : uid,
            'start'     : t0,
            'end'       : t_end,
            'grp'       : self.groups.get(c, ''),
            'wgrp'      : meta['wgrp'],
            'slot'      : meta['slot'],
            'work_timed': meta.get('work_timed', False),
        })
        wg, slot_i = meta['wgrp'], meta['slot']
        if wg:
            pool = self.slot_pool.get(wg)
            if pool and 0 <= slot_i < len(pool) and pool[slot_i] == ev_id:
                pool[slot_i] = None

    def busy_now(self, pc):
        return self.current.get(str(pc))

    def summary(self):
        out = {}
        for pc, hdict in self.log.items():
            out[pc] = {h: '; '.join(labels) for h, labels in hdict.items()}
        return out

def monitor(env, progress, energy, wh, idle, wip, stats,
            smt_lines, interval=3600, plogger=None, menv=None):
    _wall_prev = time.time()
    BAR_W = 20

    def _bar(value, max_v, width=BAR_W, fill='█', empty='░'):
        v = max(0, min(int(value), int(max_v)))
        n = int((v / max(int(max_v), 1)) * width)
        return fill * n + empty * (width - n)

    def _pcb_label(model_id, pcb_code):
        m_short = (model_id or '?').replace('MODEL_', '')
        is_main = (wh.data.pcb_map.get(model_id) == pcb_code)
        kind = '메인' if is_main else '수삽'
        try:
            side_raw = wh.data.smt_side(pcb_code)
        except Exception:
            side_raw = 'double'
        side = '양면' if side_raw == 'double' else '단면'
        tag = (str(pcb_code) or '')[-4:]
        return f'{m_short} {kind}-{side} ({tag})'

    STAGE_KEYS   = ['LOADER', 'PRINTER', 'SPI', 'MOUNTER_H',
                    'MOUNTER_M', 'REFLOW', 'UNLOADER']
    STAGE_LABELS = ['LD', 'PR', 'SP', 'MH', 'MM', 'RF', 'UL']

    while True:
        yield env.timeout(interval)
        _wall_now = time.time()
        _wall_delta = _wall_now - _wall_prev
        if _wall_delta < MONITOR_MIN_WALL_SEC:
            time.sleep(MONITOR_MIN_WALL_SEC - _wall_delta)
            _wall_now = time.time()
            _wall_delta = _wall_now - _wall_prev
        _wall_prev = _wall_now

        try:
            sys.stdout.write('\033[2J\033[H')
            sys.stdout.flush()
        except Exception:
            pass

        day  = int(env.now // DAY_SEC) + 1
        h_in = (env.now % DAY_SEC) / 3600
        pace = f'  {INFER_MONITOR_STEP_HR}h sim ≈ {_wall_delta:.2f}s wall' if _wall_delta > 0 else ''
        header = f' Day{day} {h_in:>4.1f}h │ 누적 {env.now/3600:>6.1f}h │{pace} '
        print('╔' + '═' * (len(header) + 2) + '╗')
        print(f'║ {header} ║')
        print('╚' + '═' * (len(header) + 2) + '╝')

        print('[ SMT 라인 ]')
        print('              ' + '   '.join(f'{s:^3}' for s in STAGE_LABELS))
        for sid, line in smt_lines.items():
            model = line.assigned_model
            row = []
            boards_set = set()
            for stage in STAGE_KEYS:
                pc = f'SMT_{stage}_{sid}'
                if pc in line.stage_active:
                    pcb_code, _bid, _is2 = line.stage_active[pc]
                    row.append(' ●  ')
                    if model:
                        boards_set.add(_pcb_label(model, pcb_code))
                else:
                    row.append(' ─  ')
            head = f'  {sid} ⌊{(model or "-"):^7}⌉'
            print(f'{head} {"".join(row)}')
            if boards_set:
                print(f'         ↳ 처리 중: {", ".join(sorted(boards_set))}')

        aoi_label = None
        for sid, line in smt_lines.items():
            if 'SMT_AOI' in line.stage_active:
                pcb_code, _bid, _is2 = line.stage_active['SMT_AOI']
                aoi_label = _pcb_label(line.assigned_model, pcb_code)
                break
        print(f'  AOI (공유):  {"● 진행중 " + aoi_label if aoi_label else "○ 유휴"}')

        print('\n[ THT 외주 (외주중 = in-flight, mag = 도착 후 미적재) ]')
        pool = getattr(menv, 'outsource_pool', None) if menv is not None else None
        if pool is not None:
            cur_n = len(pool.truck)
            cur_bar = _bar(cur_n, TRUCK_SIZE, width=15)
            in_transit_n = len(pool.in_transit)
            in_transit_boards = sum(t['size'] for t in pool.in_transit)
            print(f'  적재 중 트럭   {cur_bar} {cur_n:>2d}/{TRUCK_SIZE}  '
                  f'│  운송 중: {in_transit_n}대 ({in_transit_boards}보드)  '
                  f'│  누적 출발: {pool.dispatched_count}대')
        for model in progress:
            for tht_code in wh.data.tht_pcb_by_model.get(model, []):
                flow     = wh.pcb_flow.get(tht_code, {})
                fired    = int(flow.get('outsource_in', 0))
                returned = int(flow.get('outsource_returned', 0))
                in_flight = fired - returned
                mag_remain = sum(line.mag_buf.get(tht_code, 0)
                                 for line in smt_lines.values())
                lbl = _pcb_label(model, tht_code)
                print(f'  {lbl:<13s} 발사 {fired:>3}  외주중 {in_flight:>2}  '
                      f'mag(도착 후 미적재) {mag_remain:>2}')

        print('\n[ PCB 인벤토리 ]   (그래프 max = 주문 수량)')
        for model, (_done, total) in progress.items():
            for pcb in [wh.data.pcb_map.get(model)] + wh.data.tht_pcb_by_model.get(model, []):
                if not pcb:
                    continue
                stock = int(wh.stock.get(pcb, 0))
                lbl = _pcb_label(model, pcb)
                bar = _bar(stock, total, width=BAR_W)
                print(f'  {lbl:<13s} {bar} {stock:>3d}/{total}')

        print('\n[ 조립 라인 (가동 워커 / 선택 가능) ]')
        flow_groups = ['MODULE', 'SEMI', 'SET', 'INSP', 'PACK']
        grp_wgrp = {
            'MODULE': ['WORKER_FW', 'WORKER_LENS_HOLDER', 'WORKER_SENSOR_FOCUS'],
            'SEMI'  : ['WORKER_SEMI'],
            'SET'   : ['WORKER_SET', 'WORKER_SET_INSP'],
            'INSP'  : ['WORKER_AGING'],
            'PACK'  : ['WORKER_PACK'],
        }
        wres = getattr(menv, 'wres', {}) if menv is not None else {}
        cells = []
        for g in flow_groups:
            total  = wip.wip.get(g, 0)
            active = sum(wres[w].count for w in grp_wgrp.get(g, [])
                         if w in wres)
            cells.append(f'{g}({active}/{total})')
        print(f'  {"  ▶  ".join(cells)}')
        print(f'  SMT({wip.wip.get("SMT", 0):>2d})  '
              f'│  RMA({wip.wip.get("RMA", 0):>2d})')

        print('\n[ 완성 ]')
        for m, (done, total) in progress.items():
            bar = _bar(done, total, width=BAR_W)
            pct = done / max(total, 1) * 100
            print(f'  {m}  {bar} {done:>3d}/{total:<3d} ({pct:>3.0f}%)')

        rows = []
        for c, cur in wh.stock.items():
            if str(c).endswith(THT_RAW_SUFFIX):
                continue
            try:
                ms = wh.data.get_min_stock(c)
            except Exception:
                ms = MIN_STOCK
            if cur < ms:
                rows.append((cur / max(ms, 1), c, int(cur), int(ms)))
        rows.sort()
        if rows:
            top = rows[:3]
            parts = '  '.join(f'{c}={s}/{m}' for _, c, s, m in top)
            pending = len(wh._pending_orders)
            print(f'\n[ 부품 부족 ]  ⚠ {parts}  │  발주중 {pending}건')

        if idle.absent_groups:
            print(f'\n[ 결근 ] {", ".join(sorted(idle.absent_groups))}')

        if _EVENT_BUF:
            print('\n[ 최근 이벤트 ]')
            for t_sec, msg in _EVENT_BUF[-5:]:
                print(f'  {t_sec/3600:>6.2f}h  {msg}')

class ProcessGNN(nn.Module):
    def __init__(self, in_dim=6, hidden=32, out_dim=16):
        super().__init__()
        self.conv1 = nn.Linear(in_dim,  hidden)
        self.conv2 = nn.Linear(hidden,  out_dim)
        self.score = nn.Linear(out_dim, 1)

    def forward(self, H: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        deg = adj.sum(dim=1, keepdim=True).clamp(min=1e-6)
        A_n = adj / deg
        H1  = F.relu(self.conv1(A_n @ H))
        H2  = F.relu(self.conv2(A_n @ H1))
        return self.score(H2).squeeze(-1)

    def graph_embed(self, H: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        deg = adj.sum(dim=1, keepdim=True).clamp(min=1e-6)
        A_n = adj / deg
        H1  = F.relu(self.conv1(A_n @ H))
        H2  = F.relu(self.conv2(A_n @ H1))
        return H2.mean(dim=0)

class PPOAgent(nn.Module):
    LR             = 3e-4
    GAMMA          = 0.99
    LAM            = 0.95
    EPS            = 0.2
    EPOCHS         = 4
    CONV_WINDOW    = 100
    CONV_THRESHOLD = 0.01

    def __init__(self, state_dim: int, gnn: ProcessGNN):
        super().__init__()
        self.gnn      = gnn
        embed_dim     = gnn.conv2.out_features
        in_dim        = state_dim + embed_dim

        self.encoder  = nn.Sequential(
            nn.Linear(in_dim, 128), nn.ReLU(),
            nn.Linear(128,     64), nn.ReLU(),
        )
        self.actor_head  = nn.Linear(64, 1)
        self.critic_head = nn.Linear(64, 1)

        self.optimizer  = torch.optim.Adam(self.parameters(), lr=self.LR)
        self.buf        = []
        self.ep_rewards = []
        self.ep_rewards_decomp = []

    def forward(self, state_vec: torch.Tensor,
                graph_embed: torch.Tensor) -> tuple:
        x   = torch.cat([state_vec, graph_embed], dim=-1)
        enc = self.encoder(x)
        return self.actor_head(enc), self.critic_head(enc)

    def act(self, state_np: np.ndarray,
            H: torch.Tensor, adj: torch.Tensor,
            ready_mask: torch.Tensor) -> tuple:
        with torch.no_grad():
            s_t  = torch.tensor(state_np, dtype=torch.float32).unsqueeze(0)
            deg  = adj.sum(dim=1, keepdim=True).clamp(min=1e-6)
            A_n  = adj / deg
            H1   = F.relu(self.gnn.conv1(A_n @ H))
            H2   = F.relu(self.gnn.conv2(A_n @ H1))
            emb  = H2.mean(dim=0)
            emb_t = emb.unsqueeze(0)
            _, val = self.forward(s_t, emb_t)

            node_scores = self.gnn.score(H2).squeeze(-1)
            node_scores = node_scores.masked_fill(~ready_mask, float('-inf'))
            probs       = torch.softmax(node_scores, dim=0)
            dist        = torch.distributions.Categorical(probs=probs,
                                                          validate_args=False)
            action      = dist.sample()
            log_prob    = dist.log_prob(action)

        mask_bytes = ready_mask.detach().to(torch.bool).numpy().copy()
        return (action.item(), log_prob.item(),
                val.item(), emb.detach().numpy(), mask_bytes)

    def store(self, s, emb, a, r, lp, v, mask=None, model_id=None):
        self.buf.append((s, emb, a, r, lp, v, mask, model_id))

    def update(self, graphs_cache=None):
        if len(self.buf) < 2:
            return 0.0
        rewards   = [b[3] for b in self.buf]
        values    = [b[5] for b in self.buf]
        model_ids = [b[7] for b in self.buf]
        ep_r      = sum(rewards)
        self.ep_rewards.append(ep_r)

        advs, gae = [], 0.0
        for i in reversed(range(len(rewards) - 1)):
            delta = rewards[i] + self.GAMMA * values[i+1] - values[i]
            gae   = delta + self.GAMMA * self.LAM * gae
            advs.insert(0, gae)
        advs_t = torch.tensor(advs, dtype=torch.float32)
        advs_t = (advs_t - advs_t.mean()) / (advs_t.std() + 1e-8)

        for _ in range(self.EPOCHS):
            for i, entry in enumerate(self.buf[:-1]):
                if i >= len(advs):
                    break
                s, emb, a, _, old_lp, _old_v, mask, mid = entry
                s_t   = torch.tensor(s,   dtype=torch.float32).unsqueeze(0)
                emb_t = torch.tensor(emb, dtype=torch.float32).unsqueeze(0)

                _actor_out, critic_out = self.forward(s_t, emb_t)

                H_m   = graphs_cache.get(mid, (None, None))[0] if graphs_cache else None
                adj_m = graphs_cache.get(mid, (None, None))[1] if graphs_cache else None
                if H_m is not None and adj_m is not None and mask is not None:
                    mask_t = torch.tensor(mask, dtype=torch.bool)
                    node_scores = self.gnn(H_m, adj_m)
                    node_scores = node_scores.masked_fill(~mask_t, float('-inf'))
                    probs       = torch.softmax(node_scores, dim=0)
                    dist        = torch.distributions.Categorical(
                        probs=probs, validate_args=False)
                    new_lp      = dist.log_prob(torch.tensor(int(a)))
                    old_lp_t    = torch.tensor(float(old_lp))
                    ratio       = torch.exp(new_lp - old_lp_t)
                    adv         = advs_t[i]
                    loss_p      = -torch.min(
                        ratio * adv,
                        torch.clamp(ratio, 1-self.EPS, 1+self.EPS) * adv)
                else:
                    loss_p = torch.tensor(0.0)

                loss_v = F.mse_loss(
                    critic_out.squeeze(),
                    torch.tensor(values[i], dtype=torch.float32))
                loss   = loss_p + 0.5 * loss_v

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.parameters(), 0.5)
                self.optimizer.step()

        self.buf.clear()
        return ep_r

    def is_converged(self):
        if len(self.ep_rewards) < self.CONV_WINDOW * 2:
            return False
        recent = np.mean(self.ep_rewards[-self.CONV_WINDOW:])
        prev   = np.mean(self.ep_rewards[-self.CONV_WINDOW*2:-self.CONV_WINDOW])
        return abs(recent - prev) < self.CONV_THRESHOLD

    def save(self, path=POLICY_PATH, verbose=True):
        torch.save({
            'model_state': self.state_dict(),
            'ep_rewards' : self.ep_rewards,
            'ep_rewards_decomp': self.ep_rewards_decomp,
        }, path)
        if verbose:
            print(f'정책 저장: {path}')

    def load(self, path=POLICY_PATH):
        ckpt = torch.load(path, map_location='cpu')
        self.load_state_dict(ckpt['model_state'])
        self.ep_rewards = ckpt.get('ep_rewards', [])
        self.ep_rewards_decomp = ckpt.get('ep_rewards_decomp', [])
        print(f'정책 불러오기: {path} (학습 에피소드:{len(self.ep_rewards)})')

class ManufacturingEnv:
    W_DEFAULT = (0.30, 0.25, 0.15, 0.10, 0.10, 0.10)

    def __init__(self, data, order, weight_vec=None):
        self.data   = data
        self.order  = order
        self.W      = tuple(weight_vec) if weight_vec else self.W_DEFAULT
        self.graphs = {m: ProcessKnowledgeGraph(data, m) for m in order}
        self._H_cache = {
            m: torch.tensor(kg.get_feat_matrix()[1], dtype=torch.float32)
            for m, kg in self.graphs.items()
        }
        self._adj_cache = {
            m: torch.tensor(kg.get_adj(), dtype=torch.float32)
            for m, kg in self.graphs.items()
        }
        self._init_sim()

    def _init_sim(self):
        _EVENT_BUF.clear()
        self.env         = simpy.Environment()
        self.wh          = Warehouse(self.data, self.order)
        self.energy      = EnergyLogger(self.data)
        self.idle        = IdleTracker()
        self.wip         = WIPTracker(self.order)
        self.rma         = simpy.Store(self.env)
        self.stats       = defaultdict(int)
        self.progress    = {m: (0, q) for m, q in self.order.items()}
        self.wres = {}
        for _g, _c in self.data.workers.items():
            if _g == 'WORKER_SET':
                _cap = max(int(_c) - SET_INSP_HEADCOUNT, 1)
            else:
                _cap = int(_c)
            self.wres[_g] = simpy.Resource(self.env, capacity=_cap)
        self.aoi_res     = simpy.Resource(self.env, capacity=1)
        self.smt_broken  = defaultdict(bool)
        self.smt_lines   = {}
        self.outsource_pool = OutsourceTruckPool(
            self.env, self.wh, self.stats, self.smt_lines)
        for sid in SMT_LINE_IDS:
            line = SMTLine(self.env, sid, self.data, self.wh,
                           self.aoi_res, self.rma, self.energy,
                           self.idle, self.wip, self.stats, self.smt_broken,
                           outsource_pool=self.outsource_pool)
            self.smt_lines[sid] = line
        self.plogger     = ProcessActivityLogger()
        self.unit_states     = {}
        self.agent           = None
        self._prev_reward_t    = 0.0
        self._prev_reward_kwh  = 0.0
        self._prev_wip_viol    = 0
        self._prev_stock_pen   = 0
        self._prev_done        = 0
        self._prev_idle_pen    = 0.0

        self.idle.configure({g: r.capacity for g, r in self.wres.items()})
        self._compute_idle_targets()

    def _compute_idle_targets(self):
        target = defaultdict(int)
        for mid, qty in self.order.items():
            try:
                procs = self.data.get_model_procs(mid)
            except Exception:
                continue
            for _, r in procs.iterrows():
                wgrp = str(r.get('worker_group', '') or '')
                grp  = str(r.get('process_group', '') or '')
                pc   = str(r['process_code'])
                if wgrp == 'WORKER_SET' and grp == 'SET' \
                        and pc.rsplit('_', 1)[-1].upper() == 'INSP':
                    wgrp = 'WORKER_SET_INSP'
                if wgrp:
                    target[wgrp] += qty
        for g, t in target.items():
            self.idle.set_target(g, t)

    def get_state(self) -> np.ndarray:
        comp  = [self.stats.get(f'{m}_done', 0) / max(q, 1)
                 for m, q in self.order.items()]
        wutil = [1 - (r.count / max(r.capacity, 1))
                 for r in self.wres.values()]
        t_max = MAX_DAYS * (
            _active_schedule['work_end_sec']
            - _active_schedule['work_start_sec']
            - _active_schedule['break_duration_sec']
        )
        return np.array(
            comp + wutil + [
                self.energy.total / max(self.env.now + 1, 1),
                self.env.now / t_max,
                self.wh.stock_penalty() / max(sum(self.order.values()), 1),
                self.wip.violations() / max(len(self.wres), 1),
                self.idle.worker_idle_penalty() / max(self.env.now + 1, 1),
                sum(self.smt_broken.values()) / max(len(self.smt_broken) + 1, 1),
            ], dtype=np.float32)

    def reward(self) -> float:
        total = sum(self.order.values())
        cur   = sum(self.stats.get(f'{m}_done', 0) for m in self.order)
        w1, w2, w3, w4, w5, w6 = self.W

        t_max  = MAX_DAYS * (
            _active_schedule['work_end_sec']
            - _active_schedule['work_start_sec']
            - _active_schedule['break_duration_sec']
        )
        t_now  = float(self.env.now)
        prev_t = getattr(self, '_prev_reward_t', 0.0)
        dt_wall   = t_now - prev_t
        dt_work   = _work_seconds_between(prev_t, t_now)

        r1 = -dt_wall / max(t_max, 1)

        kwh_now  = self.energy.total
        prev_kwh = getattr(self, '_prev_reward_kwh', 0.0)
        d_kwh    = kwh_now - prev_kwh
        r2       = -d_kwh / max(kwh_now + 1, 1)

        wip_v_now  = self.wip.violations()
        d_wip      = wip_v_now - getattr(self, '_prev_wip_viol', 0)
        r3         = -d_wip / max(len(self.wres), 1)

        stock_now  = self.wh.stock_penalty()
        d_stock    = stock_now - getattr(self, '_prev_stock_pen', 0)
        r4         = -d_stock / max(total * 10, 1)

        d_done = cur - getattr(self, '_prev_done', 0)
        r5 = d_done / max(total, 1)
        if cur >= total and getattr(self, '_prev_done', 0) < total:
            r5 += 1.0

        self.idle.flush_all(self.env)
        idle_now  = self.idle.worker_idle_penalty()
        d_idle    = idle_now - getattr(self, '_prev_idle_pen', 0.0)
        total_cap = sum(self.idle._capacity.get(g, 0) for g in WORKER_GROUPS)
        r6_denom  = max(total_cap * dt_work, 1.0)
        r6        = -d_idle / r6_denom

        self._prev_reward_t   = t_now
        self._prev_reward_kwh = kwh_now
        self._prev_wip_viol   = wip_v_now
        self._prev_stock_pen  = stock_now
        self._prev_done       = cur
        self._prev_idle_pen   = idle_now

        contribs = (w1*r1, w2*r2, w3*r3, w4*r4, w5*r5, w6*r6)
        if not hasattr(self, '_reward_decomp_sum'):
            self._reward_decomp_sum = [0.0] * 6
        for i, c in enumerate(contribs):
            self._reward_decomp_sum[i] += c

        return sum(contribs)

    def _event_smt_breakdown(self, env):
        smt_pcs = [pc for sid in self.smt_lines
                   for pc in self.smt_lines[sid]._res]
        while True:
            yield env.timeout(600)
            if not _is_work_time(env.now):
                continue
            for pc in smt_pcs:
                if random.random() < SMT_BREAKDOWN_PROB:
                    self.smt_broken[pc] = True
                    mttr_sec   = self.data.get_mttr(pc)
                    repair_sec = max(random.normalvariate(mttr_sec, mttr_sec * 0.2),
                                     mttr_sec * 0.1)
                    _log_event(env.now,
                               f'SMT 설비 고장: {pc} MTTR={mttr_sec/3600:.1f}h '
                               f'수리예정 {repair_sec/3600:.1f}h')
                    yield env.timeout(repair_sec)
                    self.smt_broken[pc] = False
                    _log_event(env.now, f'SMT 설비 복구: {pc}')

    def _event_worker_absent(self, env):
        work_day_sec = (
            _active_schedule['work_end_sec']
            - _active_schedule['work_start_sec']
            - _active_schedule['break_duration_sec']
        )
        while True:
            yield env.timeout(_next_work_start(env.now) - env.now)
            for wgrp in self.data.worker_skill:
                if random.random() < WORKER_ABSENT_PROB:
                    self.idle.absent_groups.add(wgrp)
                    cur_skill = self.data.worker_skill.get(wgrp, 2)
                    _log_event(env.now,
                               f'작업자 결근: {wgrp} '
                               f'(숙련도 {cur_skill} -> {max(1, cur_skill - 1)})')
                    yield env.timeout(work_day_sec)
                    self.idle.absent_groups.discard(wgrp)
                    
    def _event_replenishment(self, env):
        while True:
            yield env.timeout(3600)
            if not _is_work_time(env.now):
                continue
            for item_code in list(self.wh._pending_orders):
                self.wh._pending_orders.discard(item_code)
                env.process(self._deliver(env, item_code,
                                           order_time=env.now,
                                           stock_at_order=int(self.wh.stock.get(item_code, 0))))

    def _deliver(self, env, item_code, order_time=None, stock_at_order=None):
        yield env.timeout(REPLENISH_LEAD_DAY * DAY_SEC)
        self.wh.replenish(item_code, env.now,
                          order_time=order_time, stock_at_order=stock_at_order)

    def _next_model_for_line(self):
        remaining = [m for m in self.order
                     if self.stats.get(f'smt_done_{m}', 0) < self.order[m]]
        if not remaining:
            return None

        def _shortage(m):
            order_qty = self.order[m]
            codes = [self.data.pcb_map[m]] + self.data.tht_pcb_by_model.get(m, [])
            stock = sum(self.wh.stock.get(c, 0) for c in codes)
            completed = self.stats.get(f'{m}_done', 0)
            return order_qty - stock - completed

        choice = max(remaining, key=_shortage)
        self.wh.smt_model_choices.append((float(self.env.now), choice))
        return choice

    def _smt_schedule(self):
        def _run_line(env, sid):
            line = self.smt_lines[sid]
            while True:
                model = self._next_model_for_line()
                if model is None:
                    break
                active = {l.assigned_model for l in self.smt_lines.values()
                          if l.assigned_model is not None}
                if model in active:
                    remaining = [m for m in self.order
                                 if self.stats.get(f'smt_done_{m}', 0) < self.order[m]
                                 and m not in active]
                    if not remaining:
                        yield env.timeout(300)
                        continue
                    model = remaining[0]
                line.assigned_model = model
                pcb_codes = ([self.data.pcb_map[model]] +
                             self.data.tht_pcb_by_model.get(model, []))
                target_total = self.order[model]
                target_make = target_total - int(target_total * PCB_INITIAL_RATIO)
                while True:
                    boards = []
                    for pcb_code in pcb_codes:
                        flow = self.wh.pcb_flow.get(pcb_code, {})
                        arrived = int(flow.get('restore_from_smt_or_outsource', 0))
                        in_flight = (int(flow.get('outsource_in', 0))
                                     - int(flow.get('outsource_returned', 0)))
                        in_mag = int(line.mag_buf.get(pcb_code, 0))
                        committed = arrived + in_flight + in_mag
                        if committed >= target_make:
                            continue
                        shortage = target_make - committed
                        for board_id in range(shortage):
                            p = env.process(
                                line.process_board(pcb_code, board_id, model))
                            boards.append(p)
                    if not boards:
                        break
                    yield simpy.AllOf(env, boards)
                    for pcb_code in pcb_codes:
                        remainder = line.mag_buf.get(pcb_code, 0)
                        if remainder > 0:
                            line.mag_buf[pcb_code] = 0
                            line.wh.restore(pcb_code, remainder, env.now)
                            line.pcb_count[pcb_code] += remainder
                    all_supplied = True
                    for pcb_code in pcb_codes:
                        flow = self.wh.pcb_flow.get(pcb_code, {})
                        arrived = int(flow.get('restore_from_smt_or_outsource', 0))
                        in_flight = (int(flow.get('outsource_in', 0))
                                     - int(flow.get('outsource_returned', 0)))
                        in_mag = int(line.mag_buf.get(pcb_code, 0))
                        if arrived + in_flight + in_mag < target_make:
                            all_supplied = False
                            break
                    if all_supplied:
                        break
                self.stats[f'smt_done_{model}'] = self.order[model]
                line.assigned_model = None

        line_procs = [self.env.process(_run_line(self.env, sid))
                      for sid in SMT_LINE_IDS]

        def _flush_outsource_after_lines_done(env):
            yield simpy.AllOf(env, line_procs)
            self.outsource_pool.flush_now()
        self.env.process(_flush_outsource_after_lines_done(self.env))

    def _report(self, elapsed):
        done = sum(self.stats.get(f'{m}_done', 0) for m in self.order)
        print('\n' + '=' * 60)
        print(f'makespan:{self.env.now/3600:.2f}h | 실행:{elapsed:.2f}s | '
              f'완성:{done}/{sum(self.order.values())}')
        for m, (d, t) in self.progress.items():
            pct = d / max(t, 1) * 100
            bar = '#' * int(pct/5) + '.' * (20-int(pct/5))
            print(f'  {m}: [{bar}] {d}/{t} ({pct:.0f}%)')
        print(f'  불량: SMT={self.stats.get("smt_defect",0)} '
              f'AOI={self.stats.get("aoi_defect",0)} '
              f'조립={self.stats.get("assy_defect",0)} '
              f'수리={self.stats.get("rma_repaired",0)}')
        print(f'  재고부족:{self.wh.stock_penalty()} | 재고품초과:{self.wip.violations()}')
        self.energy.report()
        self.idle.flush_all(self.env)
        self.idle.report()
        print('=' * 60)

    def _summary(self):
        done = sum(self.stats.get(f'{m}_done', 0) for m in self.order)
        return {
            'total_done'  : done,
            'total_order' : sum(self.order.values()),
            'makespan_hr' : self.env.now / 3600,
            'total_kwh'   : self.energy.total,
            '재고품초과'  : self.wip.violations(),
            'stock_pen'   : self.wh.stock_penalty(),
            'total_defect': (self.stats.get('smt_defect', 0) +
                             self.stats.get('aoi_defect', 0) +
                             self.stats.get('assy_defect', 0)),
            'oqc_inspected': self.stats.get('oqc_inspected', 0),
            'by_grp_kwh'  : dict(self.energy.by_grp),
        }
    
    def run(self, training=False):
        t_sec = MAX_DAYS * (
            _active_schedule['work_end_sec']
            - _active_schedule['work_start_sec']
            - _active_schedule['break_duration_sec']
        )
        total_need = sum(self.order.values())
        t0         = time.time()
        stop_event = self.env.event()
        mon_interval = TRAIN_MONITOR_INTERVAL if training else INFER_MONITOR_INTERVAL

        def _check_done(env):
            while True:
                yield env.timeout(30)
                done = sum(self.stats.get(f'{m}_done', 0) for m in self.order)
                if done >= total_need or env.now >= t_sec:
                    if done >= total_need:
                        for wgrp in self.data.workers:
                            self.idle.mark_completed(wgrp, float(env.now))
                    if not stop_event.triggered:
                        stop_event.succeed()
                    return

        self.env.process(run_rma(self.env, self.rma, self.wres, self.wh,
                                 self.energy, self.idle, self.wip,
                                 self.stats, self.data,
                                 progress=self.progress,
                                 plogger=self.plogger))

        if not training:
            self.env.process(monitor(self.env, self.progress, self.energy,
                                     self.wh, self.idle, self.wip, self.stats,
                                     self.smt_lines, interval=mon_interval,
                                     plogger=self.plogger, menv=self))
        self.env.process(_check_done(self.env))
        self.env.process(self._event_smt_breakdown(self.env))
        self.env.process(self._event_worker_absent(self.env))
        self.env.process(self._event_replenishment(self.env))
        self.env.process(self.wh.snapshot_loop(self.env, interval=3600))
        self.env.process(self.wip.snapshot_loop(self.env, interval=3600))
        self._smt_schedule()

        for m in self.order:
            for uid in range(self.order[m]):
                self.env.process(
                    produce_unit(self.env, m, uid, self.data, self.graphs[m],
                                 self.wres, self.wh, self.rma,
                                 self.energy, self.idle, self.wip,
                                 self.stats, self.progress, menv=self,
                                 plogger=self.plogger))

        self.env.run(until=stop_event)
        if not training:
            self._report(time.time() - t0)
        else:
            self._train_elapsed = time.time() - t0
        return self._summary()

class ExperimentRunner:
    def __init__(self, data, order: dict):
        self.data  = data
        self.order = order

    def _state_dim(self):
        n_models  = len(self.order)
        n_workers = len(self.data.workers)
        return n_models + n_workers + 6

    def _build_tensors(self, kg: ProcessKnowledgeGraph):
        _, H_np = kg.get_feat_matrix()
        adj_np  = kg.get_adj()
        return (torch.tensor(H_np, dtype=torch.float32),
                torch.tensor(adj_np, dtype=torch.float32))

    def run_ppo_training(self, max_episodes=5000):
        print(f'\n[PPO+GNN 학습] 상한 {max_episodes} 에피소드, 수렴 시 조기 종료')
        s_dim = self._state_dim()
        gnn = ProcessGNN(in_dim=6, hidden=32, out_dim=16)
        agent = PPOAgent(s_dim, gnn)

        if os.path.exists(POLICY_PATH):
            agent.load()
            start_ep = len(agent.ep_rewards)
            print(f'  이전 학습 이어서 진행 (이미 {start_ep} 에피소드 완료)')
        else:
            start_ep = 0

        CKPT_EVERY = 5
        train_t0 = time.time()
        ep = 0
        try:
            for ep in range(1, max_episodes + 1):
                ep_t0 = time.time()
                menv = ManufacturingEnv(self.data, self.order)
                menv._init_sim()
                menv.agent = agent

                menv.run(training=True)

                graphs_cache = {
                    m: self._build_tensors(kg)
                    for m, kg in menv.graphs.items()
                }
                ep_r = agent.update(graphs_cache=graphs_cache)

                decomp = list(getattr(menv, '_reward_decomp_sum', [0.0]*6))
                agent.ep_rewards_decomp.append(decomp)

                ep_dur   = time.time() - ep_t0
                elapsed  = time.time() - train_t0
                avg_dur  = elapsed / ep
                remain   = max_episodes - ep
                eta_min  = avg_dur * remain / 60
                avg_r    = float(np.mean(agent.ep_rewards[-min(100, len(agent.ep_rewards)):])) \
                           if agent.ep_rewards else 0.0
                done_now = sum(menv.stats.get(f'{m}_done', 0) for m in menv.order)
                tot_need = sum(menv.order.values())
                ms_h     = menv.env.now / 3600
                print(f'  ep {start_ep+ep:4d}/{start_ep+max_episodes:<4d} '
                      f'| sim={ms_h:6.2f}h done={done_now}/{tot_need} '
                      f'| R={ep_r:+8.3f} avg={avg_r:+8.3f} '
                      f'| {ep_dur:5.1f}s | ETA {eta_min:5.1f}m',
                      flush=True)

                if ep % CKPT_EVERY == 0:
                    agent.save(verbose=False)

                if agent.is_converged():
                    print(f'  수렴 (ep{start_ep + ep}). 학습 종료.')
                    break
        except KeyboardInterrupt:
            print(f'\n  [학습 중단됨] ep{start_ep + ep} 까지 완료. 현재 상태 저장.')

        agent.save()
        self._last_agent = agent
        total_min = (time.time() - train_t0) / 60
        print(f'\n[학습 완료] 총 {start_ep + ep} 에피소드 ({total_min:.1f}분)')
        return agent

    def run_inference(self, agent=None):
        print('\n[추론 실행]')
        menv = ManufacturingEnv(self.data, self.order)

        if agent is not None:
            agent.eval()
            menv.agent = agent
            self._last_agent = agent
            print('  학습된 정책 적용.')
        elif os.path.exists(POLICY_PATH):
            try:
                gnn   = ProcessGNN(in_dim=6, hidden=32, out_dim=16)
                s_dim = len(menv.get_state())
                loaded = PPOAgent(s_dim, gnn)
                loaded.load()
                loaded.eval()
                menv.agent = loaded
                self._last_agent = loaded
                print(f'  저장된 정책 로드: {POLICY_PATH}')
            except Exception as e:
                print(f'  [경고] 정책 로드 실패 -> greedy 모드: {e}')
                menv.agent = None
        else:
            print('  저장된 정책 없음 -> greedy 모드로 진행.')
            menv.agent = None

        summary = menv.run()
        self._last_menv = menv
        return summary

    def save_results(self, inference_summary=None, path=RESULT_PATH):
        from cpro_visualization import save_results as _impl
        _impl(runner=self, inference_summary=inference_summary, path=path,
              min_stock=MIN_STOCK, pcb_map=self.data.pcb_map,
              tht_pcb_by_model=self.data.tht_pcb_by_model)

    def save_figures(self, inference_summary=None, ep_rewards=None):
        from cpro_visualization import save_figures as _impl
        _impl(runner=self, inference_summary=inference_summary, ep_rewards=ep_rewards,
              base_dir=BASE_DIR, location_order=LOCATION_ORDER,
              location_label=LOCATION_LABEL, day_sec=DAY_SEC,
              schedule=_active_schedule, is_work_time=_is_work_time,
              next_work_start=_next_work_start)

def main():
    if os.name == 'nt':
        os.system('')

    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    torch.manual_seed(RANDOM_SEED)

    print('=== CPRO 제조 공정 시뮬레이션 (재고·공정 추적판) ===')

    static_data = FallbackDataLoader()
    print(f'  [Fallback] SMT/RMA PROCESS_FLOW:{len(static_data.pf)}공정 | '
          f'MTTR 설비:{len(static_data._mttr)}개')

    aas_models = {}
    for model_id, json_path in AAS_JSON_PATHS.items():
        if not os.path.exists(json_path):
            print(f'  [AAS]  {model_id}: JSON 없음 — 시뮬에서 제외')
            continue
        aas = load_aas(model_id, json_path)
        if aas.ManufacturingProcess:
            aas_models[model_id] = aas
            print(f'  [AAS]  {model_id}: {len(aas.ManufacturingProcess)}공정 | '
                  f'InputBOM:{sum(len(n.InputBOM) for n in aas.ManufacturingProcess.values())}건')
        else:
            print(f'  [AAS]  {model_id}: ManufacturingProcess 미파싱 — 시뮬에서 제외')

    common_path = os.path.join(BASE_DIR, 'WorkstationWorkerMatchingDataAAS.json')
    if os.path.exists(common_path):
        common = load_aas('COMMON', common_path)
        if common.schedule or common.WorkstationWorkerMatchingData:
            aas_models['COMMON'] = common
            print(f'  [AAS]  COMMON: workstations:{len(common.WorkstationWorkerMatchingData)} | '
                  f'schedule:{"OK" if common.schedule else "missing"}')

    data = CombinedDataLoader(static_data, aas_models)
    if not data.schedule:
        raise RuntimeError(
            'AAS 가 근무 스케줄을 제공하지 않음. '
            '적어도 1개 모델의 AAS JSON 이 WorkstationWorkerMatchingData 를 포함해야 함.')
    _apply_schedule(data.schedule)
    print(f'  [통합] 총 process_code:{len(data._pc_map)}개 | '
          f'workers:{len(data.workers)}그룹 | '
          f'schedule: {data.schedule.get("work_start_sec",0)//3600:02d}h~'
          f'{data.schedule.get("work_end_sec",0)//3600:02d}h '
          f'(break {data.schedule.get("break_duration_sec",0)//60}min)')

    model_ids = [m for m in aas_models if m != 'COMMON']
    order = {}
    if not model_ids:
        print('  [경고] AAS 로드된 모델이 없어 주문 입력을 건너뜁니다.')
    for m in model_ids:
        while True:
            try:
                qty = int(input(f'{m} 주문 수량: '))
                if qty > 0:
                    order[m] = qty
                    break
                print('  1 이상의 정수를 입력하세요.')
            except ValueError:
                print('  숫자를 입력하세요.')

    max_eps = 5000
    while True:
        s = input('학습 에피소드 최대 개수 (엔터=5000, 0=학습건너뛰기): ').strip()
        if not s:
            max_eps = 5000
            break
        try:
            v = int(s)
            if v >= 0:
                max_eps = v
                break
            print('  0 이상의 정수를 입력하세요.')
        except ValueError:
            print('  숫자를 입력하세요.')

    runner = ExperimentRunner(data, order)
    if max_eps == 0:
        print('\n[학습 생략] 기존 ppo_policy.pt 가 있으면 그대로 추론에 사용합니다.')
        agent = None
    else:
        agent = runner.run_ppo_training(max_episodes=max_eps)

    if agent is not None:
        print(f'\n[학습 완료 요약]')
        print(f'  총 에피소드     : {len(agent.ep_rewards)}')
        if agent.ep_rewards:
            print(f'  최종 보상 평균  : {float(np.mean(agent.ep_rewards[-100:])):.4f}')
            print(f'  최고 에피소드 보상: {max(agent.ep_rewards):.4f}')

    s = runner.run_inference(agent=agent)
    runner.save_results(inference_summary=s)
    runner.save_figures(inference_summary=s,
                        ep_rewards=(agent.ep_rewards if agent else None))

if __name__ == '__main__':
    main()