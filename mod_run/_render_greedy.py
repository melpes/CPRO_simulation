# -*- coding: utf-8 -*-
"""미학습 그리디(agent=None, B2 디스패처 FIFO)로 qty=100/100/100 제한시간 없이 풀생산 + 영상.
_render_trained.py 와 동일 셋업·동일 env 빌더 사용 → 직접 비교 가능.
출력: factory_greedy_b2.mp4
"""
import os, sys, time

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
sys.path.insert(0, _DIR); sys.path.insert(0, _ROOT)

import cpro_ver1_viz as viz

envs = viz.make_envs()
name, env, mode = next(e for e in envs if e[0] == 'ver1')
print(f'[{time.strftime("%H:%M:%S")}] greedy env 준비 (qty={dict(env.target_qty)}), mode={mode}')
print(f'[{time.strftime("%H:%M:%S")}] 렌더 시작(=env.run+영상) → factory_greedy_b2.mp4')
t0 = time.time()
viz.render('greedy_b2', env, mode, agent=None)                   # 사전 run 제거(이중실행 버그 fix)
print(f'[{time.strftime("%H:%M:%S")}] 완료 dt={time.time()-t0:.1f}s')
