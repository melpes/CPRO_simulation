# -*- coding: utf-8 -*-
"""임시 보상 개편 override (EXP13) — simulation.py 불가침 원칙 하에 env_cls 를 감싸
reward_terms() 의 W2·W5 두 항만 super() 위에 덮어쓴다. 커밋 대상 아님(실험용 임시).

개편 정의(사람 확정 2026-07-07):
  [W5] 완료수 rate → 표준작업량 가중 rate
       W5 = Σ_m Throughput[m]·std[m] / Σ_m target[m]·std[m],  std[m]=Σ CycleTimeSec(모델 m 공정)
  [W2] 총에너지 예산(E_max, 기저·SMT를 makespan 지평에 곱한 값) 비율 → 고정 생산에너지 E_prod 비율
       E_prod = 조립 active(Σ_모델 노드 per-unit 에너지 × 유닛수) + SMT 생산에너지(PCB목표 × per-pcb)
              = active_max + smt.plan_energy_kwh  = E_max − 기저(idle base) 항
       W2 = -(실제총에너지 / E_prod) × RW = base_W2 × (MaxEpisodeEnergyKwh / E_prod)   ← carbon 선형이라 정확
       makespan·기저 무관 고정 기준 → 실제/생산 비율(오버헤드 반영), baseline 실행 불필요.
  나머지 항(W1·W3·W4·W6·W7·W8)은 super() 그대로.
"""
from __future__ import annotations


def _model_stdwork(env) -> dict:
    """모델별 표준작업량(초) = 해당 모델 공정들의 CycleTimeSec 합."""
    std: dict = {m: 0.0 for m in env.target_qty}
    for node in env.KnowledgeGraph.nodes.values():
        m = getattr(node, 'model_id', None)
        if m in std:
            std[m] += float(node.CycleTimeSec)
    return std


def _active_max(env) -> float:
    """전량 생산 시 조립 active 총작업에너지(kWh) = Σ target×cycle×rated/3600.
    EpisodeEnergyKwh(공정완료 누적 active)와 같은 단위 → 완료율 분모."""
    tq = env.target_qty
    return max(1e-6, sum(tq[m] * float(n.CycleTimeSec) * float(n.RatedPowerKw) / 3600.0
                         for n in env.KnowledgeGraph.nodes.values()
                         if (m := getattr(n, 'model_id', None)) in tq))


def _prod_energy(env) -> float:
    """고정 생산에너지 E_prod(kWh) = 조립 active(모델별 노드 per-unit 에너지 × 유닛수)
    + SMT 생산에너지(계획생산이면 plan_energy_kwh). 기저·makespan 무관."""
    tq = env.target_qty
    active = sum(tq[m] * float(node.CycleTimeSec) * float(node.RatedPowerKw) / 3600.0
                 for node in env.KnowledgeGraph.nodes.values()
                 if (m := getattr(node, 'model_id', None)) in tq)
    smt_prod = 0.0
    plan = getattr(env, 'SmtPlanEffective', None)
    if plan:
        import smt
        smt_prod = smt.plan_energy_kwh(env, plan)
    return max(1e-6, active + smt_prod)


def wrap_env_cls(env_cls, cfg=None):
    """env_cls 를 상속해 reward_terms 의 W2·W5 만 교체한 서브클래스 반환."""

    rmode = (cfg or {}).get('mode', 'w2rate_w5rate')

    class RewardV2Env(env_cls):
        _reward_mode = rmode

        def _reward_tmp_cache(self):
            if not hasattr(self, '_tmp_std'):
                self._tmp_std = _model_stdwork(self)
                self._tmp_eprod = _prod_energy(self)
                self._tmp_amax = _active_max(self)
            return self._tmp_std, self._tmp_eprod, self._tmp_amax

        def reward_terms(self) -> dict:
            terms = super().reward_terms()
            RW = self.RewardWeights
            std, eprod, amax = self._reward_tmp_cache()
            mode = self._reward_mode

            if mode == 'w5partial':
                # W5 — 공정단위 부분작업 완료 rate(계단·사각지대 해소): 완료 active 작업에너지 / 전량 active
                terms['W5_Throughput'] = (self.EpisodeEnergyKwh / amax) * RW['W5_Throughput']
                # W2·기타는 현행 그대로 (W5만 격리 시험)
                return terms

            # 기본: w2rate_w5rate (완료유닛 std가중 rate + W2 E_prod비율) — 균일 std에선 사실상 no-op
            num = sum(self.Throughput[m] * std[m] for m in self.target_qty)
            den = sum(self.target_qty[m] * std[m] for m in self.target_qty)
            terms['W5_Throughput'] = (num / den if den > 0 else 0.0) * RW['W5_Throughput']
            terms['W2_Energy'] = terms['W2_Energy'] * (self.MaxEpisodeEnergyKwh / eprod)
            return terms

    RewardV2Env.__name__ = f'{env_cls.__name__}_RewardV2'
    return RewardV2Env
