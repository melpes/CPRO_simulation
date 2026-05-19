# -*- coding: utf-8 -*-
"""⚠️ [임시 실험] 재고 ×10 ablation — qty10 / qty100 짧은 학습.

목적: STOCK=0(=재고가 한 번도 안 막힘) 진단이 맞는지 경험적 검증.
재고를 10배로 키워도 makespan/throughput 이 그대로면 → 재고는 병목 아님 확정.
바뀌면 → PREC 에 가려진 부분적 자재부족이 있었던 것.

AAS 불변. simulation_ver0_mod._TEMP_STOCK_MULT 를 10 으로 세팅(Warehouse.build
의 들어오는 present/Min/Max 에만 곱함). 결과는 result/*_stock10_* 로 별도 저장
(qty10/qty100 baseline 아카이브 rl_log_qty10/qty100.jsonl 는 안 건드림).
★실험용 일회성 스크립트. 끝나면 _TEMP_STOCK_MULT 는 코드상 1.0 으로 되돌릴 것.★
"""
import os, sys, shutil, time

EP_QTY10  = 40       # ~10s/ep → ~7분 (control)
EP_QTY100 = 30       # ~266s/ep → ~2.2h (학습 추세 보이게 ep 상향)

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
_RES  = os.path.join(_DIR, 'result')
sys.path.insert(0, _DIR); sys.path.insert(0, _ROOT)

import simulation_ver0_mod as svm
svm._TEMP_STOCK_MULT = 10.0                                  # ★임시 주입★
import _timeit as T

_LOG = open(os.path.join(_RES, 'exp_stock10_console.log'), 'a', encoding='utf-8', buffering=1)
def say(m):
    line = f'[{time.strftime("%m-%d %H:%M:%S")}] {m}'
    print(line); print(line, file=_LOG, flush=True)


def _clear_signals():
    # 직전 phase2 종료 때 남은 result/STOP 등이 있으면 train() 이 ep0 에서 즉시 종료됨 → 제거
    for m in ('STOP', 'SWITCH_TO', 'ALL_DONE'):
        p = os.path.join(_RES, m)
        if os.path.exists(p):
            os.remove(p); say(f'잔존 신호 제거: {m}')


def run(qty, ep):
    say(f'=== [임시 재고×{svm._TEMP_STOCK_MULT:g}] qty={qty} ep={ep} build/train 시작 ===')
    _clear_signals()
    sv, env, agent = T.build('simulation_ver0_mod', qty, ep)
    assert svm._TEMP_STOCK_MULT == 10.0, 'TEMP mult lost'
    sv.train(env, agent, ep)                                 # result/rl_log.jsonl, agent_mod.pt 갱신
    for src, dst in (('rl_log.jsonl', f'rl_log_stock10_qty{qty}.jsonl'),
                     ('agent_mod.pt', f'agent_stock10_qty{qty}.pt')):
        s = os.path.join(_RES, src)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(_RES, dst))
    say(f'=== qty={qty} 완료 → result/rl_log_stock10_qty{qty}.jsonl 보존 ===')


if __name__ == '__main__':
    say('################ 임시 재고×10 ablation 시작 ################')
    try:
        run(10, EP_QTY10)
        run(100, EP_QTY100)
        open(os.path.join(_RES, 'EXP_STOCK10_DONE'), 'w').write(time.strftime('%Y-%m-%d %H:%M:%S'))
        say('################ EXP_STOCK10_DONE ################')
    except Exception as e:
        import traceback
        say('FATAL ' + repr(e)); traceback.print_exc(file=_LOG)
        open(os.path.join(_RES, 'EXP_STOCK10_DONE'), 'w').write('ERROR ' + repr(e))
