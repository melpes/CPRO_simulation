# ════════════════════════════════════════════════════════════════════════
# 시간 / 진입점
# ════════════════════════════════════════════════════════════════════════

RANDOM_SEED = 42
DAY_SEC     = 24 * 3600
MAX_DAYS    = 365


# ════════════════════════════════════════════════════════════════════════
# 시뮬 정책 상수
# ════════════════════════════════════════════════════════════════════════

PCB_PER_UNIT = 1
MAG_SIZE     = 15
TRUCK_SIZE   = 30

SOLDER_G         = 500
SOLDER_VALID_SEC = 24 * 3600
SOLDER_USE_G     = 0.07

CT_STD_RATIO = 0.10
DEFECT_FLOOR = 0.00001

MIN_STOCK          = 100
CRITICAL_STOCK     = 5
REPLENISH_LEAD_DAY = 1
REPLENISH_QTY_MULT = 10
WIP_CAP_RATIO      = 1.5

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

PCB_INITIAL_RATIO          = 0.8
BOM_INITIAL_RATIO          = 0.6
BOM_LOT_RATIO              = 0.5
WAREHOUSE_BOM_INIT_FLOOR   = 50
WAREHOUSE_BOM_LOT_FLOOR    = 50
WAREHOUSE_NONBOM_INIT_MULT = 10

SET_INSP_HEADCOUNT = 3


# ════════════════════════════════════════════════════════════════════════
# PCB / SMT 라인 매핑
# ════════════════════════════════════════════════════════════════════════

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

SMT_STAGE_KEYS   = ['LOADER', 'PRINTER', 'SPI', 'MOUNTER_H',
                    'MOUNTER_M', 'REFLOW', 'UNLOADER']
SMT_STAGE_LABELS = ['LD', 'PR', 'SP', 'MH', 'MM', 'RF', 'UL']

SMT_AOI_CODE      = 'SMT_AOI'
SMT_COMPLETE_CODE = 'SMT_COMPLETE'
SMT_THT_CODE      = 'SMT_THT'
SMT_VIRTUAL_DONE_CODES = {SMT_COMPLETE_CODE, SMT_THT_CODE}

def smt_stage_pc(stage: str, suffix: str) -> str:
    return f'SMT_{stage}_{suffix}'

def smt_line_sequence(suffix: str) -> list:
    return [smt_stage_pc(s, suffix) for s in SMT_STAGE_KEYS]

KG_EXCLUDED_PROCESS_GROUPS = {'SMT', 'LOGISTICS', 'SMT_SHARED', 'RMA'}
WIP_TRACKED_GROUPS         = ['SMT', 'MODULE', 'SEMI', 'SET', 'INSP', 'PACK', 'RMA']

PROCESS_GROUP_DEFAULT_KW = {
    'SMT': 5.0, 'MODULE': 1.0, 'SEMI': 2.0, 'SET': 2.0,
    'INSP': 0.5, 'OQC': 0.2, 'PACK': 1.0, 'RMA': 0.1,
}


# ════════════════════════════════════════════════════════════════════════
# 워커 그룹 / 라벨 매핑
# ════════════════════════════════════════════════════════════════════════

WWM_LINE_TO_WORKER = {
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


# ════════════════════════════════════════════════════════════════════════
# 정격 전력
# ════════════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════════════
# SMT / RMA 정적 공정 데이터 (AAS 미반영)
# ════════════════════════════════════════════════════════════════════════

PF_COLS = (
    'process_code', 'process_group', 'dep_type', 'dep_prev_codes',
    'worker_group', 'worker_count', 'cycle_time_sec', 'defect_rate',
    'transfer_qty', 'transport_mode', 'transfer_time_sec',
)

PF_ALL_ROWS = [
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

RESOURCE_MTTR_HR = {
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
