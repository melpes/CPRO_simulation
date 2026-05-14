# -*- coding: utf-8 -*-
"""aas_architecture 가 외부에 노출하는 모든 경로 한눈에 보기.

실행:  python test_paths.py

규약: 외부 진입점은 `ProvisionofSimulationModelsAAS` (alias `psm`) + `load` 만.
WWM / ProductAAS 는 직접 import 하지 않고 ref.target / psm.workers / psm.WarehouseManagedBOM 으로 우회.
"""
from path_extractor import ProvisionofSimulationModelsAAS, load


# region 데이터 로드 — 필요한 AAS JSON 모두 호출
load('ProvisionOfSimulationModel.json')
load('WorkstationWorkerMatchingDataAAS.json')
load('MODEL_A.json')
load('MODEL_B.json')
load('MODEL_C.json')
# endregion


# region alias
psm = ProvisionofSimulationModelsAAS
SM  = psm.SimulationModels.SimulationModel
dp  = SM.DefaultParameters
# endregion


# region 0. AAS root
print('# 0. AAS root')
print(psm.idShort)                                              # 'ProvisionofSimulationModelsAAS'
print(list(psm.submodels.keys()))                               # ['SimulationModels']
# endregion


# region 1. SimulationConfig — 단순 Property scalar
print('\n# 1. SimulationConfig')
print(SM.SimulationConfig.TypeOfModel.value)                    # str
print(SM.SimulationConfig.MaxEpisodes.value)                    # int
# endregion


# region 2. Node — ProcessNodePropertyRef (CycleTime/Defect/RatedPower) auto-deref
print('\n# 2. Node (PSM ref → MP Property)')
print(SM.Node.SIM_MODEL_A.VD7_10.CycleTimeSec.target.value)     # int (sec)
print(SM.Node.SIM_MODEL_A.VD7_10.CycleTimeSec.target)           # Property 객체
print(SM.Node.SIM_MODEL_A.VD7_10.DefectRate.target.value)       # float
print(SM.Node.SIM_MODEL_A.VD7_10.RatedPowerKw.target.value)     # float
print(SM.Node.SIM_MODEL_B.BT5_10.CycleTimeSec.target.value)
print(SM.Node.SIM_MODEL_C.NVD_20.CycleTimeSec.target.value)

# OQC / RMA — PSM 직접 Property (ref 아님)
print(SM.Node.ProcessOQC.OQC.CycleTimeSec.value)                # int
print(SM.Node.ProcessOQC.OQC.SamplingRate.value)                # float
print(SM.Node.ProcessOQC.OQC.RatedPowerKw.value)
print(SM.Node.ProcessRMA.RMA.CycleTimeSec.value)
print(SM.Node.ProcessRMA.RMA.RatedPowerKw.value)
# endregion


# region 3. Action — SML of ReferenceElement (ProcessNodeListRef)
print('\n# 3. Action sequences (ref → list of ProcessNode)')
# IndependentSequence: 각 ref 가 ProcessNode 들의 list 를 가리킴
print(len(SM.Action.IndependentSequence))                       # SML 원소 수
print([node.idShort for node in SM.Action.IndependentSequence[0].target])
print([node.idShort for node in SM.Action.DependentSequence[0]])    # ref.__getitem__ → target[i]
print([node.idShort for node in SM.Action.DependentJoin[0]])
# 평탄화 (test_kg.py 가 사용하는 패턴)
flat = [n.idShort for ref in SM.Action.IndependentSequence for n in ref]
print(len(flat), flat[:5])
# AssignedProcessGroups (PSM 안 — 같은 ProcessNodeListRef 타입)
print([n.idShort for n in SM.Action.AssignedProcessGroups[0]][:5])
# endregion


# region 4. RewardWeights — Property 6 개
print('\n# 4. RewardWeights')
for w in SM.RewardWeights.values():                             # SMC.values() → dict_values
    print(w.idShort, w.value)
# 또는 dict comprehension
print({c.idShort: c.value for c in SM.RewardWeights.values()})
# endregion


# region 5. DefaultParameters — 직접 Property + WWMPropertyRef
print('\n# 5. DefaultParameters')

# 5-1. SolderCreamParam (SMC of Property)
print(dp.SolderCreamParam.DailyUsagePerLine.value)
print(dp.SolderCreamParam.ContainerCapacity.value)
print(dp.SolderCreamParam.ShelfLife.value)

# 5-2. SMTParam (SMC of Property)
print(dp.SMTParam.SMTLineCount.value)
print(dp.SMTParam.LoaderRepairTime.value)
print(dp.SMTParam.PrinterRepairTime.value)
print(dp.SMTParam.ChipMounterRepairTime.value)
print(dp.SMTParam.ReflowRepairTime.value)
print(dp.SMTParam.UnlaoderRepairTime.value)
print(dp.SMTParam.SMTBreakdownProb.value)
print(dp.SMTParam.MagazineCapacity.value)

# 5-3. 직접 Property
print(dp.MinOutsourcing.value)
print(dp.ReplenishLeadDay.value)
print(dp.IdleWorkerThreshold.value)

# 5-4. WWMPropertyRef → WWM 의 Property (xs:time → sec 자동 변환)
print(dp.WorkStartTime.target.value)                            # sec
print(dp.WorkEndTime.target.value)                              # sec
print(dp.BreakDurationMin.target.min)                           # Range.min (sec)
print(dp.BreakDurationMin.target.max)                           # Range.max (sec)
# endregion


# region 6. Warehouse — MPSubmodelListRef + BOMCategoryRef
print('\n# 6. Warehouse')

# 6-1. InputBOM → list of ManufacturingProcess Submodel
mps = SM.Warehouse.InputBOM.target                              # [MP_A, MP_B, MP_C]
print([mp.model_id for mp in mps])
print(mps[0].idShort)                                           # 'ManufacturingProcess'
# 또는 ref __getitem__ 위임
print(SM.Warehouse.InputBOM[0].model_id)

# 6-2. ManufacturingProcess.groups → {group_idShort: ProcessGroup}
mp_a = mps[0]
print(list(mp_a.groups.keys()))                                 # [VD7FwInput, ...]
group = mp_a.groups['VD7FwInput']                               # ProcessGroup (SMC of ProcessNode)
print(list(group.keys()))                                       # ProcessNode idShort 들

# 6-3. ProcessNode (MP 안) — @property 로 자식 자동 deref
node = group['VD7_10']                                          # ProcessNode
print(node.CycleTimeSec.value)
print(node.DefectRate.value)
print(node.RatedPowerKw.value)
print(node.DepPrev.value)                                       # ';' 구분 문자열
print(node.DepType.value)                                       # SEQUENCE / JOIN / FORK
# InputBOM (있을 수도 없을 수도)
if node.InputBOM:
    print(list(node.InputBOM.items()))                          # [(item_code, qty), ...]
    print(list(node.InputBOM.keys()))
    print(len(node.InputBOM))

# 6-4. BOMCategoryRef → BOMCategory SMC (MinStock/MaxStock/OrderRatio 동일 target)
bom_cat = SM.Warehouse.MinStock.target                          # BOMCategory
print(len(bom_cat), list(bom_cat.keys())[:5])                   # entries
entry = bom_cat['RESISTOR']                                     # BOMCategoryEntry
print(entry.MinStock, entry.MaxStock, entry.OrderRatio)         # int, int, float
# ref __getitem__ 위임 — 직접 entry 접근
print(SM.Warehouse.MaxStock['RESISTOR'].MaxStock)
print(SM.Warehouse.OrderRatio['CAPACITOR'].OrderRatio)
# endregion


# region 7. AAS 전체 단위 property (psm.workers / psm.WarehouseManagedBOM)
print('\n# 7. AAS-level aggregated property')
workers = psm.workers                                           # {ws_id: {worker_count, ProcessCode}}
print(len(workers), list(workers.keys()))
ws = workers['WWM_FwInputLine']
print(ws['worker_count'], ws['ProcessCode'][:5])

wmb = psm.WarehouseManagedBOM                                   # {Category: [item_code, ...]}
print(len(wmb), list(wmb.keys())[:5])
sample_cat = next(iter(wmb))
print(sample_cat, len(wmb[sample_cat]), wmb[sample_cat][:3])
# endregion


# region 8. SME 공통 위임 (Submodel/SMC dict-like, SML list-like, Qualifier)
print('\n# 8. SME 공통 위임')
# Submodel/SMC dict-like
print(len(SM))                                                  # SMC 자식 수
print('Node' in SM)
print(list(SM.keys()))

# SML list-like (Action 의 IndependentSequence)
print(len(SM.Action.IndependentSequence))
print(SM.Action.IndependentSequence[0].idShort)

# Qualifier (InputBOM ref 들이 Qualifier['Quantity'] 가짐)
if node.InputBOM:
    first_ref = node.InputBOM.value[0]                          # 내부 SML 의 첫 ref
    print(first_ref.Qualifier)                                  # {Quantity: N, ...}

# semanticId 직접 비교 (str 의 일종)
print(SM.semanticId)
print(isinstance(SM.semanticId, str))
# endregion
