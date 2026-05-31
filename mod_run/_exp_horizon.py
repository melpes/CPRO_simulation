# -*- coding: utf-8 -*-
"""⚠️ [임시 실험] 고정 horizon — qty=100, 제한시간 T 로 throughput 비포화 학습.

배경: 전량완료 regime 에선 throughput 항상 100% → 순서 leverage 0(학습 평탄).
greedy probe: T=52,200s(14.5h) 에서 총 ~50/300, MODEL_B=0 (greedy 가 B 기아).
→ 시간 제한 시 순서/우선순위가 throughput 에 큰 영향 → 학습 신호 기대.

AAS 불변. svm._TEMP_EP_MAX_SEC=HORIZON_SEC 주입(train 이 env.run(max_sec=T)).
재고는 기본(×1). 결과 result/rl_log_horizon_qty100.jsonl 별도 저장.
★실험 일회성. 끝나면 _TEMP_EP_MAX_SEC 는 코드상 None 으로.★
"""
import os, sys, shutil, time

HORIZON_SEC = 52200      # greedy 기준 총 ~50개 시점(14.5h). 조정 가능.
QTY         = 100
EP          = 60         # 본 학습(체크 통과 후 스케일) ~2.5h

_DIR  = os.path.dirname(os.path.abspath(__file__))
_RES  = os.path.join(_DIR, 'result')
sys.path.insert(0, _DIR); sys.path.insert(0, os.path.dirname(_DIR))

import simulation_ver1 as svm
svm._TEMP_EP_MAX_SEC = HORIZON_SEC                          # ★임시 주입★
import _timeit as T

_LOG = open(os.path.join(_RES, 'exp_horizon_console.log'), 'a', encoding='utf-8', buffering=1)
def say(m):
    line = f'[{time.strftime("%m-%d %H:%M:%S")}] {m}'
    print(line); print(line, file=_LOG, flush=True)


if __name__ == '__main__':
    say(f'###### 고정 horizon 실험: qty={QTY} T={HORIZON_SEC}s({HORIZON_SEC/3600:.1f}h) ep={EP} ######')
    for m in ('STOP', 'SWITCH_TO', 'ALL_DONE', 'HORIZON_DONE'):       # 잔존 신호 제거(즉시종료 방지)
        p = os.path.join(_RES, m)
        if os.path.exists(p):
            os.remove(p); say(f'잔존 신호 제거: {m}')
    run_name = f'horizon_qty{QTY}_T{HORIZON_SEC}_ep{EP}_' + time.strftime('%Y-%m-%d_%H-%M-%S')
    try:
        sv, env, agent = T.build('simulation_ver1', QTY, EP)
        assert svm._TEMP_EP_MAX_SEC == HORIZON_SEC, 'horizon lost'
        say(f'build 완료, train 시작 → result/runs/{run_name}/')
        sv.train(env, agent, EP, run_name=run_name)              # 자체 subfolder 에 저장
        open(os.path.join(_RES, 'runs', run_name, 'HORIZON_DONE'),
             'w').write(time.strftime('%Y-%m-%d %H:%M:%S'))
        say(f'###### HORIZON_DONE → result/runs/{run_name}/ ######')
    except Exception as e:
        import traceback
        say('FATAL ' + repr(e)); traceback.print_exc(file=_LOG)
        os.makedirs(os.path.join(_RES, 'runs', run_name), exist_ok=True)
        open(os.path.join(_RES, 'runs', run_name, 'HORIZON_DONE'),
             'w').write('ERROR ' + repr(e))
