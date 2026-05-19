# -*- coding: utf-8 -*-
"""RL 학습 진단 로거 — rl_logger_spec.py 항목을 매 에피소드 JSONL 로 기록.

`simulation_ver0_mod.py:train()` 에서 에피소드마다 1회 호출. PPOAgent.learn 이
반환하는 진단 dict(B/C/D 패널) + 도메인 결과(E) + rollout/길이(F) + running
best(A 부분) 를 한 줄(JSON) 로 누적 append. 별도 eval rollout/baseline 이
필요한 A·F 일부(eval/return_mean, vs_random, vs_baseline, train_eval_gap)는
이번 범위 밖(Tier 3) — 추후 deterministic eval set 도입 시 추가.

순수 표준 라이브러리만 사용 (json/time/statistics). torch 의존 없음.
"""
from __future__ import annotations
import json, math, time, statistics
from typing import Optional


def _finite(v):
    # NaN/Inf → None (유효 JSON 유지; ev 정의불가 케이스를 null 로 표기)
    return None if isinstance(v, float) and not math.isfinite(v) else v


class RLLogger:
    def __init__(self, path: str, entropy_window: int = 10):
        self.path           = path
        self.entropy_window = entropy_window
        self._R_hist        = []        # 에피소드별 train rollout reward
        self._len_hist      = []        # 에피소드별 결정점 수
        self._ent_hist      = []        # 에피소드별 policy entropy
        self._best_R        = None
        open(self.path, 'w', encoding='utf-8').close()    # 새 run = 새 파일

    def log_episode(self, episode: int, *, R: float, makespan: float,
                     energy: float, throughput: dict, target_qty: dict,
                     decisions: int, metrics: Optional[dict]) -> bool:
        """한 에피소드 기록 후 is_best 반환 (best 갱신 시 train 이 .pt 저장)."""
        self._R_hist.append(float(R))
        self._len_hist.append(int(decisions))
        is_best = self._best_R is None or R > self._best_R
        if is_best:
            self._best_R = float(R)

        produced = sum(throughput.values())
        ordered  = sum(target_qty.values()) or 1
        feasible = all(throughput[m] >= target_qty[m] for m in target_qty)

        row = {
            'episode'                     : episode,
            'wall_time'                   : round(time.time(), 3),

            # [F] SANITY & DEBUGGING — 단독 신뢰 금지, eval 와 함께만 의미
            'train/rollout_reward'        : float(R),
            'train/rollout_reward_mean'   : statistics.fmean(self._R_hist),
            'sanity/reward_std'           : (statistics.pstdev(self._R_hist)
                                             if len(self._R_hist) > 1 else 0.0),
            'sanity/episode_length'       : int(decisions),
            'sanity/episode_length_mean'  : statistics.fmean(self._len_hist),

            # [A] LEARNING SIGNAL — running max (진동해도 monotonic). eval_* 는 Tier3.
            'eval/return_best_so_far'     : self._best_R,
            'is_best'                     : is_best,

            # [E] TASK-SPECIFIC — reward 설계와 무관한 도메인 품질
            'task/primary_metric'         : float(makespan),     # makespan(sec)
            'task/energy_kwh'             : float(energy),
            'task/throughput'             : produced,
            'task/throughput_ratio'       : produced / ordered,
            'task/feasibility_rate'       : 1.0 if feasible else produced / ordered,
        }

        # [B] CRITIC / [C] STABILITY / [D] EXPLORATION — learn() 진단 dict
        if metrics:
            row.update({k: _finite(v) for k, v in metrics.items()})
            ent = metrics.get('exploration/entropy')
            if ent is not None:
                self._ent_hist.append(float(ent))
                row['exploration/entropy_slope'] = self._entropy_slope()

        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return is_best

    def _entropy_slope(self) -> float:
        # 최근 window entropy 의 단순 선형회귀 기울기 (collapse 속도). <2 → 0.
        w = self._ent_hist[-self.entropy_window:]
        if len(w) < 2:
            return 0.0
        xs = list(range(len(w)))
        mx, my = statistics.fmean(xs), statistics.fmean(w)
        den = sum((x - mx) ** 2 for x in xs)
        if den == 0:
            return 0.0
        return sum((x - mx) * (y - my) for x, y in zip(xs, w)) / den
