# -*- coding: utf-8 -*-
"""자율 학습 오케스트레이터 (단일 백그라운드 프로세스).

phase1: qty=10 학습 (train() 이 result/ 에 매 ep 로깅 + best ckpt).
  외부(모니터링 에이전트)가 result/STOP 을 쓰면 train() 이 그 ep 에서 graceful 종료.
phase2: STOP 후 result/SWITCH_TO 내용이 '100' 이면 → phase1 산출물을 *_qty10.* 로
  아카이브하고 qty=100 으로 재학습. SWITCH_TO 없으면 그대로 종료.
모든 단계 표시는 result/ 의 마커 파일 + train_console.log 로 남긴다.
프로세스 kill / 재기동 없음 — 이 한 프로세스가 두 phase 를 끝까지 처리.
"""
import os, sys, json, time, shutil

_DIR    = os.path.dirname(os.path.abspath(__file__))
_ROOT   = os.path.dirname(_DIR)                            # 패키지 루트 — path_extractor·AAS
_RESULT = os.path.join(_DIR, 'result')
os.makedirs(_RESULT, exist_ok=True)
sys.path.insert(0, _DIR)
sys.path.insert(0, _ROOT)

_LOG = open(os.path.join(_RESULT, 'train_console.log'), 'a', encoding='utf-8', buffering=1)


def _say(msg):
    line = f'[{time.strftime("%m-%d %H:%M:%S")}] {msg}'
    print(line, file=_LOG, flush=True)
    print(line, flush=True)


def _orch(phase, **kw):
    kw['phase'] = phase
    kw['ts'] = time.strftime('%Y-%m-%d %H:%M:%S')
    json.dump(kw, open(os.path.join(_RESULT, '_orch.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


def run_phase(qty, max_ep):
    import _timeit as T
    _say(f'PHASE qty={qty} build 시작 (MaxEpisodes={max_ep})')
    sv, env, agent = T.build('simulation_ver0_mod', qty, max_ep)
    _orch(f'qty{qty}', qty=qty, max_ep=max_ep, state='running')
    _say(f'PHASE qty={qty} train 시작')
    sv.train(env, agent, max_ep)                       # result/ 로깅·ckpt·STOP 협조중단
    _say(f'PHASE qty={qty} train 반환 (STOP 또는 {max_ep}ep 완료)')


def _archive(tag):
    for f in ('rl_log.jsonl', 'agent_mod.pt', 'train_console.log'):
        src = os.path.join(_RESULT, f)
        if os.path.exists(src):
            base, ext = os.path.splitext(f)
            shutil.copy2(src, os.path.join(_RESULT, f'{base}_{tag}{ext}'))
    _say(f'아카이브 완료: *_{tag}.*')


if __name__ == '__main__':
    import path_extractor as pe
    for _f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
               'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
        pe.load(os.path.join(os.path.dirname(_DIR), _f))
    MAX_EP = int(pe.ProvisionofSimulationModelsAAS.SimulationModels
                 .SimulationModel.SimulationConfig.MaxEpisodes.value)   # AAS=5000

    # 새 run: 이전 신호/마커 정리 (옛 rl_log 는 train() RLLogger 가 truncate)
    for m in ('STOP', 'SWITCH_TO', 'ALL_DONE'):
        p = os.path.join(_RESULT, m)
        if os.path.exists(p):
            os.remove(p)

    try:
        run_phase(10, MAX_EP)                                          # ── phase1
        sw = os.path.join(_RESULT, 'SWITCH_TO')
        target = open(sw, encoding='utf-8').read().strip() if os.path.exists(sw) else ''
        if target == '100':
            _archive('qty10')
            for m in ('STOP', 'SWITCH_TO'):                            # phase2 위해 신호 해제
                p = os.path.join(_RESULT, m)
                if os.path.exists(p):
                    os.remove(p)
            run_phase(100, MAX_EP)                                     # ── phase2
            _archive('qty100')
        else:
            _say('SWITCH_TO 없음 — phase1 종료로 마감')
        open(os.path.join(_RESULT, 'ALL_DONE'), 'w').write(time.strftime('%Y-%m-%d %H:%M:%S'))
        _say('ALL_DONE')
    except Exception as e:
        import traceback
        _say('FATAL: ' + repr(e))
        traceback.print_exc(file=_LOG)
        open(os.path.join(_RESULT, 'ALL_DONE'), 'w').write('ERROR ' + repr(e))
