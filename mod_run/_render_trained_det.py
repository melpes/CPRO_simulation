# -*- coding: utf-8 -*-
"""결정론(eval=argmax) 학습 가중치 풀실행 + 렌더 → factory_trained_det.mp4

NOTE: 체크포인트는 StateDim=0 시절(아키텍처 변경 전) 가중치. 현재 코드는 StateDim>0
지원이 추가됐지만, 학습본 호환 위해 agent 를 명시적으로 StateDim=0 으로 빌드.
"""
import os, sys, time, torch
_DIR=os.path.dirname(os.path.abspath(__file__)); _ROOT=os.path.dirname(_DIR)
sys.path.insert(0,_DIR); sys.path.insert(0,_ROOT)

import simulation_ver1 as svm
import cpro_ver1_viz as viz          # AAS load 트리거(path_extractor 캐시 채움)
import path_extractor as pe
PSM = pe.ProvisionofSimulationModelsAAS
SM  = PSM.SimulationModels.SimulationModel
GNN = SM.ModelArchitecture.GNN
TC  = SM.ModelArchitecture.PPO.TrainingConfig

ag = svm.PPOAgent(
    NodeFeatureDim   = int(GNN.NodeFeatureDim.value),
    HiddenDim        = int(GNN.HiddenDim.value),
    OutputDim        = int(GNN.OutputDim.value),
    NumLayers        = int(GNN.NumLayers.value),
    GNNEmbeddingDim  = int(GNN.OutputDim.value),
    LearningRate     = float(TC.LearningRate.value),
    ClipEpsilon      = float(TC.ClipEpsilon.value),
    Gamma            = float(TC.Gamma.value),
    GaeLambda        = float(TC.GaeLambda.value),
    EntropyCoef      = float(TC.EntropyCoef.value),
    ValueLossCoef    = float(TC.ValueLossCoef.value),
    UpdateEpochs     = TC.UpdateEpochs.value,
    BatchSize        = int(TC.BatchSize.value),
    RuntimeVariables = SM.RuntimeVariables,
    StateDim         = 0,                                # ← 체크포인트 학습 당시 arch
)
CKPT = os.path.join(_DIR,'result','runs','b2_horizon_60ep_orig_05-19_StateDim0','agent_horizon_qty100_baseline.pt')
ag.load_state_dict(torch.load(CKPT))
ag.eval(); ag.reset_buffer()
print(f'[{time.strftime("%H:%M:%S")}] agent eval(deterministic argmax) 로드 (StateDim=0)')

envs = viz.make_envs()
_, env, mode = next(e for e in envs if e[0]=='ver1')
print(f'[{time.strftime("%H:%M:%S")}] env qty={dict(env.target_qty)} mode={mode}')
print(f'[{time.strftime("%H:%M:%S")}] 렌더 시작(=env.run+영상) → factory_trained_det.mp4')
t0=time.time()
viz.render('trained_det', env, mode, agent=ag)            # agent 전달, 사전 run 없음 (이중실행 fix)
print(f'[{time.strftime("%H:%M:%S")}] 완료 dt={time.time()-t0:.1f}s')
