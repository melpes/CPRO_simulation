# -*- coding: utf-8 -*-
# 워커 프로세스 격리 — 시뮬 코드의 프로세스 전역 상태(AAS 싱글턴·난수·정책)를 주소공간 분리로 차단.
# 워커마다 구동부(TrainedModel)를 1회 만들고, 실행은 프로세스 내에서 순차 처리한다.
import json
import os
import sys

_MODEL = None


def _package_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def init_worker(ckpt_path: str, aas_dir: str) -> None:
    global _MODEL
    root = _package_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    import torch
    torch.set_num_threads(1)          # 워커 N개 × torch 스레드 = 오버서브스크립션 방지
    import engine
    _MODEL = engine.TrainedModel(checkpoint=ckpt_path, aas_dir=aas_dir)


def _atomic_json(path: str, obj) -> None:
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(obj, fp, ensure_ascii=False)
    os.replace(tmp, path)


def execute(request: dict, seed: int, run_dir: str) -> dict:
    """이 패키지의 시나리오를 실행하고 산출물을 run_dir 에 직접 쓴다.
    결과(수 MB)를 부모 프로세스로 되돌리지 않고 파일로 넘긴다."""
    import scenario
    result, summary_line = scenario.run(_MODEL, request, seed)

    candidates = result.get('candidates', [])
    candidates_dir = os.path.join(run_dir, 'candidates')
    os.makedirs(candidates_dir, exist_ok=True)

    index = []
    for candidate in candidates:
        _atomic_json(os.path.join(candidates_dir, f"{candidate['candidate_id']}.json"), candidate)
        index.append({'candidate_id': candidate['candidate_id'],
                      'condition'   : candidate['condition'],
                      'flags'       : candidate['flags'],
                      'metric'      : candidate['metric']})
    _atomic_json(os.path.join(run_dir, 'candidates.json'), index)
    _atomic_json(os.path.join(run_dir, 'result.json'),
                 {k: v for k, v in result.items() if k != 'candidates'})

    return {'summary_line'   : summary_line,
            'candidate_count': len(candidates),
            'scenario'       : result.get('scenario')}


def model_info() -> dict:
    """이 패키지의 시나리오·모델셋·AAS 기본 입력. 워커 워밍업 겸용."""
    import scenario
    return {'scenario': scenario.NAME,
            'objective': scenario.OBJECTIVE,
            'models': sorted(_MODEL.model_set),
            'aas_defaults': {
                'purchase_order': _MODEL.purchase_order(),
                'aging_equipment': _MODEL.aging_equipment(),
            }}
