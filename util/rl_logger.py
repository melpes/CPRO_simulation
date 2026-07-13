from __future__ import annotations
import json, math, os, time, statistics
from typing import Optional


class RLLogger:
    def __init__(self, path: str, entropy_window: int = 10, resume: bool = False):
        self.path             = path
        self.entropy_window   = entropy_window
        self._R_history       = []
        self._length_history  = []
        self._entropy_history = []
        self._best_R          = None
        self.next_episode     = 0
        if resume and os.path.exists(path):
            for line in open(path, encoding='utf-8'):
                try: entry = json.loads(line)
                except Exception: continue
                if 'train/rollout_reward' in entry:  self._R_history.append(float(entry['train/rollout_reward']))
                if 'sanity/episode_length' in entry: self._length_history.append(int(entry['sanity/episode_length']))
                if entry.get('exploration/entropy') is not None: self._entropy_history.append(float(entry['exploration/entropy']))
                if entry.get('eval/return_best_so_far') is not None:
                    best = float(entry['eval/return_best_so_far'])
                    self._best_R = best if self._best_R is None else max(self._best_R, best)
                self.next_episode = int(entry.get('episode', self.next_episode - 1)) + 1
        else:
            open(self.path, 'w', encoding='utf-8').close()

    def log_episode(self, episode: int, *, R: float, makespan: float,
                     energy: float, throughput: dict, target_qty: dict,
                     decisions: int, metrics: Optional[dict],
                     violations: Optional[dict] = None,
                     reward_terms: Optional[dict] = None,
                     line_energy: Optional[dict] = None,
                     idle_energy: Optional[float] = None,
                     smt_energy: Optional[float] = None,
                     smt_equip_energy: Optional[dict] = None,
                     completion_sec: Optional[dict] = None,
                     idle_time_total: Optional[float] = None,
                     line_idle_time: Optional[dict] = None,
                     extra: Optional[dict] = None) -> bool:
        self._R_history.append(float(R))
        self._length_history.append(int(decisions))
        is_best = self._best_R is None or R > self._best_R
        if is_best:
            self._best_R = float(R)

        produced = sum(throughput.values())
        ordered  = sum(target_qty.values()) or 1
        feasible = all(throughput[m] >= target_qty[m] for m in target_qty)

        row = {
            'episode'                     : episode,
            'wall_time'                   : round(time.time(), 3),

            'train/rollout_reward'        : float(R),
            'train/rollout_reward_mean'   : statistics.fmean(self._R_history),
            'sanity/reward_std'           : (statistics.pstdev(self._R_history)
                                             if len(self._R_history) > 1 else 0.0),
            'sanity/episode_length'       : int(decisions),
            'sanity/episode_length_mean'  : statistics.fmean(self._length_history),

            'eval/return_best_so_far'     : self._best_R,
            'is_best'                     : is_best,

            'task/primary_metric'         : float(makespan),
            'task/energy_kwh'             : float(energy),
            'task/throughput'             : produced,
            'task/throughput_ratio'       : produced / ordered,
            'task/feasibility_rate'       : 1.0 if feasible else produced / ordered,
            **{f'task/throughput/{m}': throughput[m] for m in throughput},
        }
        if violations:
            row.update({f'task/{k}': v for k, v in violations.items()})
        if reward_terms:
            row.update({f'reward/{k}': v for k, v in reward_terms.items()})
        if line_energy:
            row.update({f'energy/line/{k}': v for k, v in line_energy.items()})
        if idle_energy is not None:
            row['energy/idle'] = idle_energy
        if smt_energy is not None:
            row['energy/smt'] = smt_energy
        if smt_equip_energy:
            row.update({f'energy/smt/{line}/{name}': v
                        for line, equipment in smt_equip_energy.items() for name, v in equipment.items()})
        if completion_sec:
            row.update({f'task/completion_sec/{m}': v for m, v in completion_sec.items()})
        if idle_time_total is not None:
            row['idle_sec/total'] = idle_time_total
        if line_idle_time:
            row.update({f'idle_sec/line/{k}': v for k, v in line_idle_time.items()})
        if extra:
            row.update(extra)

        if metrics:
            row.update({k: (None if isinstance(v, float) and not math.isfinite(v) else v)
                        for k, v in metrics.items()})
            entropy = metrics.get('exploration/entropy')
            if entropy is not None:
                self._entropy_history.append(float(entropy))
                row['exploration/entropy_slope'] = self._entropy_slope()

        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return is_best

    def _entropy_slope(self) -> float:
        window = self._entropy_history[-self.entropy_window:]
        if len(window) < 2:
            return 0.0
        xs = list(range(len(window)))
        mean_x, mean_y = statistics.fmean(xs), statistics.fmean(window)
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if denominator == 0:
            return 0.0
        return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, window)) / denominator
