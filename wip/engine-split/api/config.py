# -*- coding: utf-8 -*-
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CKPT_PATH       = os.getenv('CPRO_CKPT', str(ROOT / 'agent_mod.pt'))
AAS_DIR         = os.getenv('CPRO_AAS_DIR', str(ROOT / 'aas_data'))
RUNS_DIR        = Path(os.getenv('CPRO_RUNS_DIR', str(ROOT / 'result' / 'api_runs')))
WORKERS         = int(os.getenv('CPRO_WORKERS', '0')) or max(1, min(4, (os.cpu_count() or 2) // 2))
JOB_TIMEOUT_SEC = int(os.getenv('CPRO_JOB_TIMEOUT_SEC', '900'))
QUEUE_MAX       = int(os.getenv('CPRO_QUEUE_MAX', '16'))
DEFAULT_SEED    = int(os.getenv('CPRO_SEED', '42'))
