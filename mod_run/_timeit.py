# -*- coding: utf-8 -*-
"""학습 wall-time 실측 → qty/MaxEpisodes 사이징.

ver1(워커 디스패처) 작은 qty 로 N ep train 시간 측정.
분리된 MODEL_B(12A/B..) 반영 상태에서 측정. build() 는 ver1 도구 공유 env+agent 빌더.
"""
import os, sys, time, importlib, io, contextlib

DIR   = os.path.dirname(os.path.abspath(__file__))        # mod_run/
_ROOT = os.path.dirname(DIR)                               # 패키지 루트 — AAS JSON·root 모듈
sys.path.insert(0, _ROOT)
import path_extractor as pe

for f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
          'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
    pe.load(os.path.join(_ROOT, 'aas_data', f))
PSM = pe.ProvisionofSimulationModelsAAS
SM  = PSM.SimulationModels.SimulationModel
A   = SM.KnowledgeGraph.Action
DP  = SM.DefaultParameters
RW  = SM.RewardWeights
GNN = SM.ModelArchitecture.GNN
PPO = SM.ModelArchitecture.PPO
TC  = PPO.TrainingConfig


def build(modname, qty, ep):
    sv = importlib.import_module(modname)                     # 'simulation_ver1'
    MPs = {mp.model_id: mp for mp in SM.Warehouse.InputBOM.target}
    KG  = sv.KnowledgeGraph.build(MPs, PSM.workers,
            {name: g for name, g in SM.KnowledgeGraph.Node.value.items() if name in ('ProcessOQC',)})
    WH  = sv.Warehouse.build(PSM.CoManagedBOM, SM.Warehouse.MinStock.target)
    rw = {k: float(RW[k].value) for k in
          ['W1_TimeElapsed', 'W2_Energy', 'W3_StockOverflow',
           'W4_StockShortage', 'W5_Throughput', 'W6_IdleWorker']}
    kw = dict(
        KnowledgeGraph=KG, warehouse=WH, workers=PSM.workers,
        IndependentSequence=[n.idShort for r in A.IndependentSequence for n in r.target if n is not None],
        DependentSequence=[n.idShort for r in A.DependentSequence for n in r.target if n is not None],
        DependentJoin=[n.idShort for r in A.DependentJoin for n in r.target if n is not None],
        RewardWeights=rw, ReplenishLeadDay=int(DP.ReplenishLeadDay.value) * 3600,
        target_qty={'MODEL_A': qty, 'MODEL_B': qty, 'MODEL_C': qty}, MaxEpisodes=ep,
        WarehouseManagedBOM=PSM.CoManagedBOM, BOMCategory=SM.Warehouse.MinStock.target,
        WorkStartTime=DP.WorkStartTime.target.value, WorkEndTime=DP.WorkEndTime.target.value,
        break_start_sec=DP.BreakDurationMin.target.min,
        break_end_sec=DP.BreakDurationMin.target.max,
        IdleWorkerThreshold=int(DP.IdleWorkerThreshold.value),
        RuntimeVariables=SM.RuntimeVariables,
        IdleProcessRatedPowerKw=float(DP.IdleProcessRatedPowerKw.value),
        IdlePowerRatio=0.10,
        SelfManagedBOM=PSM.SelfManagedBOM)
    env = sv.CproSimEnv(**kw)
    agent_kw = dict(
        NodeFeatureDim=int(GNN.NodeFeatureDim.value), HiddenDim=int(GNN.HiddenDim.value),
        OutputDim=int(GNN.OutputDim.value), NumLayers=int(GNN.NumLayers.value),
        GNNEmbeddingDim=int(GNN.OutputDim.value),
        LearningRate=float(TC.LearningRate.value), ClipEpsilon=float(TC.ClipEpsilon.value),
        Gamma=float(TC.Gamma.value), GaeLambda=float(TC.GaeLambda.value),
        EntropyCoef=float(TC.EntropyCoef.value), ValueLossCoef=float(TC.ValueLossCoef.value),
        UpdateEpochs=TC.UpdateEpochs.value, BatchSize=int(TC.BatchSize.value),
        RuntimeVariables=SM.RuntimeVariables)
    if hasattr(env, 'state_dim'):                             # ver1: 동적 관측 state_vec 주입
        agent_kw['StateDim'] = env.state_dim
    agent = sv.PPOAgent(**agent_kw)
    return sv, env, agent


def measure(modname, qty, ep):
    sv, env, agent = build(modname, qty, ep)
    t = time.perf_counter()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sv.train(env, agent, ep)
    dt = time.perf_counter() - t
    last = [l for l in buf.getvalue().splitlines() if l.strip()][-1:]
    return dt, dt / ep, last[0] if last else ''


if __name__ == '__main__':
    target = float(sys.argv[1]) if len(sys.argv) > 1 else 7200.0
    for mod in ['simulation_ver1']:
        print(f'\n==== {mod} ====')
        rows = []
        for qty in (2, 4):
            dt, per, last = measure(mod, qty, 2)
            rows.append((qty, per))
            print(f'qty A/B/C={qty:>2}  2ep total={dt:6.1f}s  per-ep={per:6.2f}s  | {last[:90]}')
        # 선형 외삽: per-ep ≈ a + b·qty
        (q1, p1), (q2, p2) = rows
        b = (p2 - p1) / (q2 - q1)
        a = p1 - b * q1
        print(f'  per-ep(qty) ≈ {a:.2f} + {b:.3f}·qty')
        for q in (10, 30, 50, 100):
            per = a + b * q
            print(f'  qty={q:>3} → per-ep≈{per:7.1f}s  → {target/per:6.1f} ep / {target/3600:.0f}h')
