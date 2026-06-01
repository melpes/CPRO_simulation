# -*- coding: utf-8 -*-
"""고정 horizon 실험 — qty=N, 제한시간 T 로 throughput 비포화 학습.

배경: 전량완료 regime 에선 throughput 항상 100% → 순서 leverage 0(학습 평탄).
→ 시간 제한 시 순서/우선순위가 throughput 에 큰 영향 → 학습 신호 기대.

1일 학습이 본 도입(`simulation_ver1.EPISODE_DURATION_SEC=86400`)된 이후 본 스크립트는
임의 horizon (T ≠ 86400) 실험 전용. 일반 학습은 simulation_ver1.train() 의
episode_max_sec 기본값(=86400) 으로 진행.

AAS 불변. train() 의 episode_max_sec 인자로 horizon 주입. 결과 result/runs/<run_name>/ 저장.
"""
import os, sys, time

HORIZON_SEC = 52200      # 임의 horizon. None 또는 86400 이면 기본 1일 학습과 동일.
QTY         = 100
EP          = 60

_DIR  = os.path.dirname(os.path.abspath(__file__))
_RES  = os.path.join(_DIR, 'result')
sys.path.insert(0, _DIR); sys.path.insert(0, os.path.dirname(_DIR))

import _timeit as T

_LOG = open(os.path.join(_RES, 'exp_horizon_console.log'), 'a', encoding='utf-8', buffering=1)
def say(m):
    line = f'[{time.strftime("%m-%d %H:%M:%S")}] {m}'
    print(line); print(line, file=_LOG, flush=True)


if __name__ == '__main__':
    say(f'###### 고정 horizon 실험: qty={QTY} T={HORIZON_SEC}s({HORIZON_SEC/3600:.1f}h) ep={EP} ######')
    for m in ('STOP', 'SWITCH_TO', 'ALL_DONE', 'HORIZON_DONE'):       # 잔존 신호 제거
        p = os.path.join(_RES, m)
        if os.path.exists(p):
            os.remove(p); say(f'잔존 신호 제거: {m}')
    run_name = f'horizon_qty{QTY}_T{HORIZON_SEC}_ep{EP}_' + time.strftime('%Y-%m-%d_%H-%M-%S')
    try:
        sv, env, agent = T.build('simulation_ver1', QTY, EP)
        say(f'build 완료, train 시작 → result/runs/{run_name}/')
        sv.train(env, agent, EP, run_name=run_name, episode_max_sec=HORIZON_SEC)
        open(os.path.join(_RES, 'runs', run_name, 'HORIZON_DONE'),
             'w').write(time.strftime('%Y-%m-%d %H:%M:%S'))
        say(f'###### HORIZON_DONE → result/runs/{run_name}/ ######')
    except Exception as e:
        import traceback
        say('FATAL ' + repr(e)); traceback.print_exc(file=_LOG)
        os.makedirs(os.path.join(_RES, 'runs', run_name), exist_ok=True)
        open(os.path.join(_RES, 'runs', run_name, 'HORIZON_DONE'),
             'w').write('ERROR ' + repr(e))
