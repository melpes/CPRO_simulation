# -*- coding: utf-8 -*-
"""실험 스크립트 — ver3 패턴 (env.run(agent)) 모델의 주요 항 변동 / 신호 추적.

추적 항목:
    A. greedy 완주 baseline (TARGET 9/30/300) — deterministic 여부
    B. random vs greedy 정책 비교 — makespan / kwh 변동
    C. choose 시점 시계열 — t / kwh / throughput / ready_size
    D. reward 항 분해 — r_time (W1) / r_kwh (W2) / r_done (W5) 누적
    E. PPO 학습 곡선 — episode 별 reward / kwh / makespan
    F. 워커 utilization — 라인별 dispatch 분포

실행: python redesign/_experiments.py
"""
import os
import sys
import time
import random
import statistics
from collections import Counter

import numpy as np

_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_DIR not in sys.path:
    sys.path.append(_PKG_DIR)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import path_extractor
import cpro_config as C


def _load():
    for f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
              'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
        path_extractor.load(os.path.join(_PKG_DIR, f))


#========추적 agent (mock) — 정책 + 시계열 기록========

class TrackingAgent:
    """choose 시점의 env 누적 state 기록. policy: 'greedy' | 'random' | 'last'."""

    def __init__(self, factory, weights, policy='greedy', seed=0):
        self.factory = factory
        self.W       = weights
        self.policy  = policy
        self.rng     = random.Random(seed)
        self.history = []                              # [{t, kwh, throughput, ready_size}]
        self.r_time_sum = 0.0
        self.r_kwh_sum  = 0.0
        self.r_done_sum = 0.0
        self._prev_t    = 0.0
        self._prev_kwh  = 0.0
        self._prev_done = 0
        self.ws_dispatch = Counter()

    def choose(self, ready_pcs, model_id, done_set, env):
        t    = float(env.env.now)
        kwh  = float(env.EpisodeEnergyKwh[0])
        thru = int(env._throughput_counter[0])

        # reward 항 분해 (PPOAgent._delta_reward 와 동일 식)
        dt_wall = t    - self._prev_t
        d_kwh   = kwh  - self._prev_kwh
        d_done  = thru - self._prev_done
        r_time  = -dt_wall / max(self.factory.total_work_seconds, 1.0)
        r_kwh   = -d_kwh   / max(self.factory.total_expected_kwh, 1.0)
        r_done  =  d_done  / max(self.factory.total_target_qty,   1)
        self.r_time_sum += self.W.get('W1_TimeElapsed', 0.2) * r_time
        self.r_kwh_sum  += self.W.get('W2_Energy',      0.2) * r_kwh
        self.r_done_sum += self.W.get('W5_Throughput',  0.25) * r_done
        self._prev_t, self._prev_kwh, self._prev_done = t, kwh, thru

        self.history.append({'t': t, 'kwh': kwh, 'throughput': thru,
                              'ready_size': len(ready_pcs)})

        if self.policy == 'random':
            pc = self.rng.choice(ready_pcs)
        elif self.policy == 'last':
            pc = ready_pcs[-1]
        else:
            pc = ready_pcs[0]
        for ws, info in env.workers.items():
            if pc in info['ProcessCode']:
                self.ws_dispatch[ws] += 1
                break
        return pc


#========Exp A/B: 정책별 완주 baseline========

def exp_policies(build_env, sizes=(9, 30, 300)):
    print('\n' + '=' * 78)
    print('# Exp A/B: 정책별 완주 (greedy / random×3seed / last)')
    print('=' * 78)
    for total in sizes:
        per = total // 3
        C.TARGET_QTY = {'MODEL_A': per, 'MODEL_B': per, 'MODEL_C': per}
        print(f'\n[TARGET={total} ({per}/{per}/{per})]')
        for policy, seeds in [('greedy', [0]), ('last', [0]),
                              ('random', [0, 1, 2])]:
            results = []
            for seed in seeds:
                env = build_env()
                agent = TrackingAgent(env.factory, env.RewardWeights, policy, seed)
                t0 = time.time()
                r  = env.run(agent=agent, max_sec=60 * 86400)
                dt = time.time() - t0
                results.append((r, agent, dt))
            ms   = [r['makespan_sec'] / 86400 for r, _, _ in results]
            kwh  = [r['EpisodeEnergyKwh']     for r, _, _ in results]
            thru = [r['Throughput']           for r, _, _ in results]
            steps= [len(a.history)            for _, a, _ in results]
            print(f'  {policy:<8s} T={thru[0]}/{total}  '
                  f'makespan={statistics.mean(ms):.3f}d(±{statistics.pstdev(ms):.4f})  '
                  f'kwh={statistics.mean(kwh):.2f}(±{statistics.pstdev(kwh):.3f})  '
                  f'choose#={statistics.mean(steps):.0f}')


#========Exp C/D: choose 시점 시계열 + reward 항 분해========

def exp_signal_decomp(build_env, total=30):
    print('\n' + '=' * 78)
    print(f'# Exp C/D: choose 시점 시계열 + reward 항 분해 (greedy, TARGET={total})')
    print('=' * 78)
    per = total // 3
    C.TARGET_QTY = {'MODEL_A': per, 'MODEL_B': per, 'MODEL_C': per}
    env = build_env()
    agent = TrackingAgent(env.factory, env.RewardWeights, 'greedy', 0)
    r = env.run(agent=agent, max_sec=60 * 86400)
    h = agent.history
    print(f'  choose 횟수: {len(h)}  완주: {r["Throughput"]}/{total}')
    print(f'  makespan: {r["makespan_sec"]/86400:.3f}d   최종 kwh: {r["EpisodeEnergyKwh"]:.2f}')
    print(f'\n  [reward 항 누적] (episode 전체 합)')
    print(f'    W1 r_time  합: {agent.r_time_sum:+.4f}')
    print(f'    W2 r_kwh   합: {agent.r_kwh_sum:+.4f}')
    print(f'    W5 r_done  합: {agent.r_done_sum:+.4f}')
    print(f'    합계           {agent.r_time_sum + agent.r_kwh_sum + agent.r_done_sum:+.4f}')
    # 시계열 샘플 (10 구간)
    print(f'\n  [시계열 — choose # 기준 10 구간]')
    n = len(h)
    print(f'    {"idx":>6s} {"t(d)":>8s} {"kwh":>9s} {"thru":>5s} {"ready":>6s}')
    for k in range(0, n, max(n // 10, 1)):
        e = h[k]
        print(f'    {k:>6d} {e["t"]/86400:>8.3f} {e["kwh"]:>9.2f} '
              f'{e["throughput"]:>5d} {e["ready_size"]:>6d}')


#========Exp F: 워커 utilization========

def exp_worker_util(build_env, total=30):
    print('\n' + '=' * 78)
    print(f'# Exp F: 워커 dispatch 분포 (greedy vs random, TARGET={total})')
    print('=' * 78)
    per = total // 3
    C.TARGET_QTY = {'MODEL_A': per, 'MODEL_B': per, 'MODEL_C': per}
    for policy in ('greedy', 'random'):
        env = build_env()
        agent = TrackingAgent(env.factory, env.RewardWeights, policy, 0)
        env.run(agent=agent, max_sec=60 * 86400)
        total_d = sum(agent.ws_dispatch.values())
        print(f'\n  [{policy}] WS dispatch (top 6 / {len(agent.ws_dispatch)} WS):')
        for ws, c in agent.ws_dispatch.most_common(6):
            print(f'    {ws:<28s} {c:>6d}  ({100*c/total_d:>5.1f}%)')


#========Exp E: PPO 학습 곡선========

def exp_ppo(build_env, build_agent, total=30, episodes=15):
    print('\n' + '=' * 78)
    print(f'# Exp E: PPO 학습 곡선 (TARGET={total}, {episodes} epi)')
    print('=' * 78)
    per = total // 3
    C.TARGET_QTY = {'MODEL_A': per, 'MODEL_B': per, 'MODEL_C': per}
    env   = build_env()
    agent = build_agent(env)
    print(f'  params={sum(p.numel() for p in agent.parameters()):,}')
    print(f'  {"ep":>3s} {"reward":>9s} {"makespan(d)":>11s} {"kwh":>9s} {"wall":>6s}')
    rewards = []
    for ep in range(episodes):
        t0 = time.time()
        agent.reset_episode()
        r = env.run(agent=agent, max_sec=60 * 86400)
        agent.finalize_episode(env)
        ep_r = agent.update()
        rewards.append(ep_r)
        if ep % max(episodes // 10, 1) == 0 or ep == episodes - 1:
            print(f'  {ep:>3d} {ep_r:>+9.4f} {r["makespan_sec"]/86400:>11.3f} '
                  f'{r["EpisodeEnergyKwh"]:>9.2f} {time.time()-t0:>5.1f}s')
    print(f'\n  ep0 vs ep{episodes-1} reward: {rewards[0]:+.4f} → {rewards[-1]:+.4f} '
          f'(Δ {rewards[-1]-rewards[0]:+.4f})')


if __name__ == '__main__':
    _load()
    from runner import build_env, build_agent

    exp_policies(build_env, sizes=(9, 30, 300))
    exp_signal_decomp(build_env, total=30)
    exp_worker_util(build_env, total=30)
    exp_ppo(build_env, build_agent, total=30, episodes=15)
