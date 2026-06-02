
## 요약 테이블 (main 기준)

| file | SM | SME(main) | CD | descrMiss | descrAction | semMiss | dangProj | dangExt | cdInc | dupId |
|---|---|---|---|---|---|---|---|---|---|---|
| MODEL_A | 2 | 571 | 287 | 13 | 2 | 1 | 2 | 1 | 159 | 16 |
| MODEL_B | 2 | 797 | 437 | 396 | 112 | 1 | 0 | 1 | 198 | 39 |
| MODEL_C | 2 | 642 | 305 | 134 | 1 | 1 | 0 | 1 | 2 | 0 |
| wwm | 1 | 240 | 74 | 15 | 1 | 0 | 1 | 1 | 5 | 0 |
| psm | 1 | 450 | 186 | 258 | 45 | 10 | 1 | 1 | 58 | 1 |
| psm_smt | 2 | 571 | 284 | 258 | 45 | 10 | 77 | 1 | 156 | 1 |

# AAS JSON 완전성 감사 리포트

대상: MODEL_A, MODEL_B, MODEL_C, wwm, psm, psm_smt
dangling 판정 = 6개 파일 CD id 글로벌 union 기준. (smart-factory.kr = 프로젝트 CD = 실제 / 그 외 = 외부 표준 = 예상)


## MODEL_A  (`MODEL_A.json`)
- Submodel 2개 · SME 569개(main) · CD 287개
- **중복 CD id**: `HasPart_10100285/1/0` ×2; `HasPart_10200041/1/0` ×3; `HasPart_10200440/1/0` ×2; `HasPart_10200476/1/0` ×3; `HasPart_10300577/1/0` ×2; `HasPart_10500048/1/0` ×2; `HasPart_10500067/1/0` ×2; `HasPart_11200008/1/0` ×2; `HasPart_11200009/1/0` ×2; `HasPart_11200013/1/0` ×2; `HasPart_11200020/1/0` ×2; `HasPart_11200091/1/0` ×2; `HasPart_11200010/1/0` ×2; `HasPart_11200148/1/0` ×2; `HasPart_10600097/1/0` ×2; `HasPart_11200036/1/0` ×2

### [main (시뮬 모델 본체)]
**A. description 누락**: 총 13 (actionable 2 / CD로 커버 11)
  - actionable (CD 정의도 없음) modelType×parent: Entity@Entity×1, SubmodelElementCollection@SubmodelElementCollection×1
    - `HierarchicalStructures/MODEL_A_VD7/PCB_03903424` (Entity, parent=Entity, idShort=PCB_03903424)
    - `HierarchicalStructures/BOMCategory/IC_REGULATOR` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=IC_REGULATOR)
**B. semanticId 누락**: 1
  - modelType×parent×(idShort없음): Submodel@env×1
    - `ManufacturingProcess` (Submodel, parent=env, idShort=ManufacturingProcess)
**C. dangling CD (참조하나 CD 없음)**: project 2 / external 1
  - project(실제 누락): 고유 2종
    - `https://www.smart-factory.kr/ids/cd/VD7FwInput/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/VD7GimbalAssembly/1/0` ×1
  - external(예상): 고유 1종
    - `https://admin-shell.io/idta/HierarchicalStructures/1/1/Submodel` ×1

### [CD 불완전] hard 159 / soft(unit만) 126
  - 결함 조합 분포: no dataType×133; no embeddedDataSpecifications×18; no definition+no dataType×6; no preferredName+no definition+no dataType×1; no definition×1
    - `PCB_03203204` (PCB_03203204/1/0): no dataType [+soft no unit]
    - `MODEL_A_VD7` (MODEL_A_VD7/1/0): no definition, no dataType [+soft no unit]
    - `HasPart_10100285` (HasPart_10100285/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200032` (HasPart_10200032/1/0): no dataType
    - `CAPACITOR_10200037` (HasPart_10200037/1/0): no dataType
    - `CAPACITOR_10200041` (HasPart_10200041/1/0): no dataType
    - `CAPACITOR_10200066` (HasPart_10200066/1/0): no dataType
    - `CAPACITOR_10200244` (HasPart_10200244/1/0): no dataType
    - `CAPACITOR_10200301` (HasPart_10200301/1/0): no dataType
    - `CAPACITOR_10200319` (HasPart_10200319/1/0): no dataType
    - `CAPACITOR_10200368` (HasPart_10200368/1/0): no dataType
    - `CAPACITOR_10200403` (HasPart_10200403/1/0): no definition, no dataType
    - `CAPACITOR_10200440` (HasPart_10200440/1/0): no dataType
    - `CAPACITOR_10200476` (HasPart_10200476/1/0): no dataType
    - `CONNECTOR_10300456` (HasPart_10300456/1/0): no dataType [+soft no unit]
    - `RESISTOR_11200757` (HasPart_11200757/1/0): no dataType
    - `CONNECTOR_10300577` (HasPart_10300577/1/0): no dataType [+soft no unit]
    - `DIODE_10500048` (HasPart_10500048/1/0): no dataType
    - `DIODE_10500067` (HasPart_10500067/1/0): no dataType [+soft no unit]
    - `INDUCTOR_FILTER_CHIP_10600184` (HasPart_10600184/1/0): no dataType
    - `IC_REGULATOR_10700331` (HasPart_10700331/1/0): no dataType [+soft no unit]
    - `IC_REGULATOR_10700679` (HasPart_10700679/1/0): no definition, no dataType [+soft no unit]
    - `IC_REGULATOR_10700893` (HasPart_10700893/1/0): no dataType [+soft no unit]
    - `IC_REGULATOR_10701571` (HasPart_10701571/1/0): no dataType
    - `IC_REGULATOR_10701572` (HasPart_10701572/1/0): no dataType
    - `IC_REGULATOR_10701573` (HasPart_10701573/1/0): no dataType
    - `RESISTOR_11200008` (HasPart_11200008/1/0): no dataType
    - `RESISTOR_11200009` (HasPart_11200009/1/0): no dataType
    - `RESISTOR_11200013` (HasPart_11200013/1/0): no dataType
    - `RESISTOR_11200020` (HasPart_11200020/1/0): no dataType
    - `RESISTOR_11200021` (HasPart_11200021/1/0): no dataType
    - `RESISTOR_11200062` (HasPart_11200062/1/0): no dataType
    - `RESISTOR_11200091` (HasPart_11200091/1/0): no dataType
    - `RESISTOR_11200585` (HasPart_11200585/1/0): no dataType
    - `RESISTOR_11200647` (HasPart_11200647/1/0): no dataType
    - `RESISTOR_11200737` (HasPart_11200737/1/0): no dataType
    - `RESISTOR_11200808` (HasPart_11200808/1/0): no dataType
    - `TRANSISTOR_11600061` (HasPart_11600061/1/0): no dataType [+soft no unit]
    - `PCB_SUB_11102327` (HasPart_11102327/1/0): no dataType [+soft no unit]
    - `CCD_10100285` (HasPart_10100285/1/0): no dataType [+soft no unit]
    - … 외 119개

## MODEL_B  (`MODEL_B.json`)
- Submodel 2개 · SME 795개(main) · CD 437개
- **중복 CD id**: `HasPart_11200008/1/0` ×4; `HasPart_10200037/1/0` ×2; `HasPart_10200042/1/0` ×3; `HasPart_10200041/1/0` ×4; `HasPart_11200091/1/0` ×2; `HasPart_10200319/1/0` ×3; `HasPart_11200009/1/0` ×2; `HasPart_10200301/1/0` ×3; `HasPart_10200403/1/0` ×2; `HasPart_10200032/1/0` ×2; `HasPart_10200477/1/0` ×3; `HasPart_10200801/1/0` ×3; `HasPart_10600180/1/0` ×2; `HasPart_10300577/1/0` ×2; `HasPart_10600329/1/0` ×2; `HasPart_10300287/1/0` ×3; `HasPart_10300222/1/0` ×2; `HasPart_10500048/1/0` ×2; `HasPart_10200137/1/0` ×2; `HasPart_10300255/1/0` ×2; `HasPart_10200213/1/0` ×3; `HasPart_11200148/1/0` ×2; `HasPart_11200013/1/0` ×2; `HasPart_11200585/1/0` ×2; `HasPart_11200062/1/0` ×2; `HasPart_10200028/1/0` ×2; `HasPart_10200029/1/0` ×2; `HasPart_10200455/1/0` ×2; `HasPart_10200476/1/0` ×2; `HasPart_10300537/1/0` ×2; `HasPart_10300538/1/0` ×2; `HasPart_11200010/1/0` ×2; `HasPart_11200011/1/0` ×2; `HasPart_11200034/1/0` ×2; `HasPart_11200036/1/0` ×2; `HasPart_11200041/1/0` ×3; `HasPart_11200078/1/0` ×2; `HasPart_11200610/1/0` ×2; `HasPart_10300272/1/0` ×2

### [main (시뮬 모델 본체)]
**A. description 누락**: 총 396 (actionable 112 / CD로 커버 284)
  - actionable (CD 정의도 없음) modelType×parent: Entity@Entity×63, SubmodelElementCollection@SubmodelElementCollection×35, SubmodelElementCollection@Submodel×12, Entity@Submodel×1, Submodel@env×1
    - `HierarchicalStructures/MODEL_B_BT5` (Entity, parent=Submodel, idShort=MODEL_B_BT5)
    - `HierarchicalStructures/MODEL_B_BT5/PCB_03902607` (Entity, parent=Entity, idShort=PCB_03902607)
    - `HierarchicalStructures/MODEL_B_BT5/PCB_03902727` (Entity, parent=Entity, idShort=PCB_03902727)
    - `HierarchicalStructures/MODEL_B_BT5/PCB_03902730` (Entity, parent=Entity, idShort=PCB_03902730)
    - `HierarchicalStructures/MODEL_B_BT5/PCB_03902835` (Entity, parent=Entity, idShort=PCB_03902835)
    - `HierarchicalStructures/MODEL_B_BT5/P10200041` (Entity, parent=Entity, idShort=P10200041)
    - `HierarchicalStructures/MODEL_B_BT5/P20502144` (Entity, parent=Entity, idShort=P20502144)
    - `HierarchicalStructures/MODEL_B_BT5/P20901531` (Entity, parent=Entity, idShort=P20901531)
    - `HierarchicalStructures/MODEL_B_BT5/P10800475` (Entity, parent=Entity, idShort=P10800475)
    - `HierarchicalStructures/MODEL_B_BT5/P21001088` (Entity, parent=Entity, idShort=P21001088)
    - `HierarchicalStructures/MODEL_B_BT5/P21201135` (Entity, parent=Entity, idShort=P21201135)
    - `HierarchicalStructures/MODEL_B_BT5/P21600245` (Entity, parent=Entity, idShort=P21600245)
    - `HierarchicalStructures/MODEL_B_BT5/P21200982` (Entity, parent=Entity, idShort=P21200982)
    - `HierarchicalStructures/MODEL_B_BT5/P21600550` (Entity, parent=Entity, idShort=P21600550)
    - `HierarchicalStructures/MODEL_B_BT5/P21201312` (Entity, parent=Entity, idShort=P21201312)
    - `HierarchicalStructures/MODEL_B_BT5/P20500680` (Entity, parent=Entity, idShort=P20500680)
    - `HierarchicalStructures/MODEL_B_BT5/P20901192` (Entity, parent=Entity, idShort=P20901192)
    - `HierarchicalStructures/MODEL_B_BT5/P20200931` (Entity, parent=Entity, idShort=P20200931)
    - `HierarchicalStructures/MODEL_B_BT5/P20501505` (Entity, parent=Entity, idShort=P20501505)
    - `HierarchicalStructures/MODEL_B_BT5/P20502118` (Entity, parent=Entity, idShort=P20502118)
    - `HierarchicalStructures/MODEL_B_BT5/P21200352` (Entity, parent=Entity, idShort=P21200352)
    - `HierarchicalStructures/MODEL_B_BT5/P21200974` (Entity, parent=Entity, idShort=P21200974)
    - `HierarchicalStructures/MODEL_B_BT5/P20500904` (Entity, parent=Entity, idShort=P20500904)
    - `HierarchicalStructures/MODEL_B_BT5/P20500682` (Entity, parent=Entity, idShort=P20500682)
    - `HierarchicalStructures/MODEL_B_BT5/P20500681` (Entity, parent=Entity, idShort=P20500681)
    - `HierarchicalStructures/MODEL_B_BT5/P30300573` (Entity, parent=Entity, idShort=P30300573)
    - `HierarchicalStructures/MODEL_B_BT5/P21001040` (Entity, parent=Entity, idShort=P21001040)
    - `HierarchicalStructures/MODEL_B_BT5/P21800011` (Entity, parent=Entity, idShort=P21800011)
    - `HierarchicalStructures/MODEL_B_BT5/P21201067` (Entity, parent=Entity, idShort=P21201067)
    - `HierarchicalStructures/MODEL_B_BT5/P21101219` (Entity, parent=Entity, idShort=P21101219)
    - … 외 82개
**B. semanticId 누락**: 1
  - modelType×parent×(idShort없음): Submodel@env×1
    - `ManufacturingProcess` (Submodel, parent=env, idShort=ManufacturingProcess)
**C. dangling CD (참조하나 CD 없음)**: project 0 / external 1
  - external(예상): 고유 1종
    - `https://admin-shell.io/idta/HierarchicalStructures/1/1/Submodel` ×1

### [CD 불완전] hard 198 / soft(unit만) 106
  - 결함 조합 분포: no definition×140; no preferredName+no definition+no dataType×38; no embeddedDataSpecifications×14; no definition+no dataType×2; no dataType×2; no preferredName×2
    - `MODEL_B_BT5` (MODEL_B_BT5/1/0): no definition, no dataType [+soft no unit]
    - `PCB_03203145` (PCB_03203145/1/0): no definition [+soft no unit]
    - `PCB_03902607` (PCB_03902607/1/0): no definition [+soft no unit]
    - `None` (HasPart_10200042/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `DIODE_10500048` (HasPart_10500048/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `PCB_03902608` (PCB_03902608/1/0): no definition [+soft no unit]
    - `PCB_SUB_11102059` (HasPart_11102059/1/0): no definition [+soft no unit]
    - `PCB_03902690` (PCB_03902690/1/0): no definition [+soft no unit]
    - `CONNECTOR_10300255` (HasPart_10300255/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `PCB_03902727` (PCB_03902727/1/0): no definition [+soft no unit]
    - `None` (HasPart_10200041/1/0): no embeddedDataSpecifications
    - `RESISTOR_11200008` (HasPart_11200008/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `RESISTOR_11200013` (HasPart_11200013/1/0): no dataType
    - `CAPACITOR_10200032` (HasPart_10200032/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `None` (HasPart_10200037/1/0): no embeddedDataSpecifications
    - `CAPACITOR_10200301` (HasPart_10200301/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `None` (HasPart_10200319/1/0): no embeddedDataSpecifications
    - `CAPACITOR_10200403` (HasPart_10200403/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200477` (HasPart_10200477/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200801` (HasPart_10200801/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `PCB_03902730` (PCB_03902730/1/0): no definition [+soft no unit]
    - `CAPACITOR_10200028` (HasPart_10200028/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200041` (HasPart_10200041/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200042` (HasPart_10200042/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200137` (HasPart_10200137/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200213` (HasPart_10200213/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200301` (HasPart_10200301/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200319` (HasPart_10200319/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200424` (HasPart_10200424/1/0): no dataType
    - `CAPACITOR_10200455` (HasPart_10200455/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200476` (HasPart_10200476/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200477` (HasPart_10200477/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CAPACITOR_10200801` (HasPart_10200801/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `None` (HasPart_10300222/1/0): no embeddedDataSpecifications
    - `None` (HasPart_10300287/1/0): no embeddedDataSpecifications
    - `CONNECTOR_10300537` (HasPart_10300537/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `CONNECTOR_10300538` (HasPart_10300538/1/0): no embeddedDataSpecifications
    - `CONNECTOR_10300577` (HasPart_10300577/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - `DIODE_10500243` (HasPart_10500243/1/0): no preferredName [+soft no unit]
    - `INDUCTOR_FILTER_CHIP_10600180` (HasPart_10600180/1/0): no preferredName, no definition, no dataType [+soft no unit]
    - … 외 158개

## MODEL_C  (`MODEL_C.json`)
- Submodel 2개 · SME 640개(main) · CD 305개

### [main (시뮬 모델 본체)]
**A. description 누락**: 총 134 (actionable 1 / CD로 커버 133)
  - actionable (CD 정의도 없음) modelType×parent: SubmodelElementCollection@SubmodelElementCollection×1
    - `HierarchicalStructures/BOMCategory/IC_REGULATOR` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=IC_REGULATOR)
**B. semanticId 누락**: 1
  - modelType×parent×(idShort없음): Submodel@env×1
    - `ManufacturingProcess` (Submodel, parent=env, idShort=ManufacturingProcess)
**C. dangling CD (참조하나 CD 없음)**: project 0 / external 1
  - external(예상): 고유 1종
    - `https://admin-shell.io/idta/HierarchicalStructures/1/1/Submodel` ×1

### [CD 불완전] hard 2 / soft(unit만) 159
  - 결함 조합 분포: no definition+no dataType×1; no definition×1
    - `ArcheType` (https://admin-shell.io/idta/HierarchicalStructures/ArcheType/1/0): no definition, no dataType [+soft no unit]
    - `IC_REGULATOR` (IC_REGULATOR/1/0): no definition [+soft no unit]

## wwm  (`WorkstationWorkerMatchingDataAAS.json`)
- Submodel 1개 · SME 239개(main) · CD 74개

### [main (시뮬 모델 본체)]
**A. description 누락**: 총 15 (actionable 1 / CD로 커버 14)
  - actionable (CD 정의도 없음) modelType×parent: SubmodelElementCollection@SubmodelElementCollection×1
    - `WorkstationWorkerMatchingData/GeneralWorkstationData/WorkstationInformation/WWM_RMALine` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=WWM_RMALine)
**B. semanticId 누락**: 0
**C. dangling CD (참조하나 CD 없음)**: project 1 / external 1
  - project(실제 누락): 고유 1종
    - `https://www.smart-factory.kr/ids/cd/UnitsPerWorker/1/0` ×1
  - external(예상): 고유 1종
    - `https://admin-shell.io/idta/sm/workstationworkermatchingdata` ×1

### [CD 불완전] hard 5 / soft(unit만) 68
  - 결함 조합 분포: no definition×3; no definition+no dataType×2
    - `GeneralWorkstationData` (https://admin-shell.io/idta/smc/generalworkstationdata/1/0): no definition, no dataType [+soft no unit]
    - `WorkstationInformation` (https://admin-shell.io/idta/smc/workstationinformation/1/0): no definition, no dataType [+soft no unit]
    - `WWM_RMALine` (WWM_RMALine/1/0): no definition [+soft no unit]
    - `LHWorkerRecord_02` (LHWorkerRecord_02/1/0): no definition [+soft no unit]
    - `LHWorkerRecord_03` (LHWorkerRecord_03/1/0): no definition [+soft no unit]

## psm  (`ProvisionOfSimulationModel.json`)
- Submodel 1개 · SME 449개(main) · CD 186개
- **중복 CD id**: `RatedPowerKw/1/0` ×2

### [main (시뮬 모델 본체)]
**A. description 누락**: 총 258 (actionable 45 / CD로 커버 213)
  - actionable (CD 정의도 없음) modelType×parent: SubmodelElementCollection@SubmodelElementCollection×41, Property@SubmodelElementCollection×2, ReferenceElement@SubmodelElementList×1, ReferenceElement@SubmodelElementCollection×1
    - `SimulationModels/SimulationModel/KnowledgeGraph` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=KnowledgeGraph)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_10` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_10)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_11` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_11)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_12A` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_12A)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_12B` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_12B)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_13A` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_13A)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_13B` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_13B)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_14A` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_14A)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_14B` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_14B)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_20` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_20)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_30` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_30)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_31` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_31)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_40` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_40)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_41` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_41)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_42` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_42)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_50` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_50)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_51` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_51)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_52` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_52)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_60` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_60)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_61` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_61)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_62` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_62)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_70` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_70)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_71` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_71)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_72` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_72)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_73` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_73)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_74` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_74)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_75` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_75)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_80` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_80)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_90` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_90)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_100` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_100)
    - … 외 15개
**B. semanticId 누락**: 10
  - modelType×parent×(idShort없음): ReferenceElement@SubmodelElementList(익명)×10
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/IndependentSequence/[0]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/IndependentSequence/[1]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/IndependentSequence/[2]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentSequence/[0]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentSequence/[1]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentSequence/[2]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentSequence/[3]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentJoin/[0]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentJoin/[1]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentJoin/[2]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
**C. dangling CD (참조하나 CD 없음)**: project 1 / external 1
  - project(실제 누락): 고유 1종
    - `https://www.smart-factory.kr/ids/cd/DepNext/1/0` ×1
  - external(예상): 고유 1종
    - `https://example.com/ids/cd/0445_8041_5062_7858` ×1

### [CD 불완전] hard 58 / soft(unit만) 115
  - 결함 조합 분포: no definition×50; no dataType×5; no definition+no dataType×3
    - `SimulationModel` (https://admin-shell.io/idta/SimulationModels/SimulationModel/1/1): no dataType [+soft no unit]
    - `TypeOfModel` (https://admin-shell.io/idta/SimulationModels/TypeOfModel/1/0): no definition [+soft no unit]
    - `BT5_10` (BT5_10/1/0): no definition [+soft no unit]
    - `BT5_11` (BT5_11/1/0): no definition [+soft no unit]
    - `BT5_12` (BT5_12/1/0): no definition [+soft no unit]
    - `BT5_13` (BT5_13/1/0): no definition [+soft no unit]
    - `BT5_14` (BT5_14/1/0): no definition [+soft no unit]
    - `BT5_20` (BT5_20/1/0): no definition [+soft no unit]
    - `BT5_30` (BT5_30/1/0): no definition [+soft no unit]
    - `BT5_31` (BT5_31/1/0): no definition [+soft no unit]
    - `BT5_40` (BT5_40/1/0): no definition [+soft no unit]
    - `BT5_41` (BT5_41/1/0): no definition [+soft no unit]
    - `BT5_42` (BT5_42/1/0): no definition [+soft no unit]
    - `BT5_50` (BT5_50/1/0): no definition [+soft no unit]
    - `BT5_51` (BT5_51/1/0): no definition [+soft no unit]
    - `BT5_52` (BT5_52/1/0): no definition [+soft no unit]
    - `BT5_60` (BT5_60/1/0): no definition [+soft no unit]
    - `BT5_61` (BT5_61/1/0): no definition [+soft no unit]
    - `BT5_62` (BT5_62/1/0): no definition [+soft no unit]
    - `BT5_70` (BT5_70/1/0): no definition [+soft no unit]
    - `BT5_71` (BT5_71/1/0): no definition [+soft no unit]
    - `BT5_72` (BT5_72/1/0): no definition [+soft no unit]
    - `BT5_73` (BT5_73/1/0): no definition [+soft no unit]
    - `BT5_74` (BT5_74/1/0): no definition [+soft no unit]
    - `BT5_75` (BT5_75/1/0): no definition [+soft no unit]
    - `BT5_80` (BT5_80/1/0): no definition [+soft no unit]
    - `BT5_90` (BT5_90/1/0): no definition [+soft no unit]
    - `BT5_100` (BT5_100/1/0): no definition [+soft no unit]
    - `BT5_110` (BT5_110/1/0): no definition [+soft no unit]
    - `BT5_120` (BT5_120/1/0): no definition [+soft no unit]
    - `BT5_121` (BT5_121/1/0): no definition [+soft no unit]
    - `BT5_122` (BT5_122/1/0): no definition [+soft no unit]
    - `BT5_123` (BT5_123/1/0): no definition [+soft no unit]
    - `ProcessOQC` (ProcessOQC/1/0): no definition [+soft no unit]
    - `OQC` (OQC/1/0): no definition [+soft no unit]
    - `SamplingRate` (SamplingRate/1/0): no definition [+soft no unit]
    - `ProcessRMA` (ProcessRMA/1/0): no definition [+soft no unit]
    - `RMA` (RMA/1/0): no definition [+soft no unit]
    - `W4_StockShortage` (W4_StockShortage/1/0): no definition [+soft no unit]
    - `ShelftLife` (ShelfLife/1/0): no dataType
    - … 외 18개

## psm_smt  (`ProvisionOfSimulationModel_smt.json`)
- Submodel 2개 · SME 570개(main) · CD 284개
- **중복 CD id**: `RatedPowerKw/1/0` ×2

### [main (시뮬 모델 본체)]
**A. description 누락**: 총 258 (actionable 45 / CD로 커버 213)
  - actionable (CD 정의도 없음) modelType×parent: SubmodelElementCollection@SubmodelElementCollection×41, Property@SubmodelElementCollection×2, ReferenceElement@SubmodelElementList×1, ReferenceElement@SubmodelElementCollection×1
    - `SimulationModels/SimulationModel/KnowledgeGraph` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=KnowledgeGraph)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_10` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_10)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_11` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_11)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_12A` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_12A)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_12B` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_12B)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_13A` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_13A)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_13B` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_13B)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_14A` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_14A)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_14B` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_14B)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_20` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_20)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_30` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_30)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_31` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_31)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_40` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_40)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_41` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_41)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_42` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_42)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_50` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_50)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_51` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_51)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_52` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_52)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_60` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_60)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_61` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_61)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_62` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_62)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_70` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_70)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_71` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_71)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_72` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_72)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_73` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_73)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_74` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_74)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_75` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_75)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_80` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_80)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_90` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_90)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Node/SIM_MODEL_B/BT5_100` (SubmodelElementCollection, parent=SubmodelElementCollection, idShort=BT5_100)
    - … 외 15개
**B. semanticId 누락**: 10
  - modelType×parent×(idShort없음): ReferenceElement@SubmodelElementList(익명)×10
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/IndependentSequence/[0]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/IndependentSequence/[1]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/IndependentSequence/[2]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentSequence/[0]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentSequence/[1]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentSequence/[2]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentSequence/[3]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentJoin/[0]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentJoin/[1]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
    - `SimulationModels/SimulationModel/KnowledgeGraph/Action/DependentJoin/[2]` (ReferenceElement, parent=SubmodelElementList, idShort=None)
**C. dangling CD (참조하나 CD 없음)**: project 77 / external 1
  - project(실제 누락): 고유 20종
    - `https://www.smart-factory.kr/ids/cd/CycleTime/1/0` ×14
    - `https://www.smart-factory.kr/ids/cd/Materials/1/0` ×14
    - `https://www.smart-factory.kr/ids/cd/PCB/1/0` ×9
    - `https://www.smart-factory.kr/ids/cd/SolderPastedPCB/1/0` ×8
    - `https://www.smart-factory.kr/ids/cd/ReflowedPCB/1/0` ×8
    - `https://www.smart-factory.kr/ids/cd/ChipMountedPCB/1/0` ×4
    - `https://www.smart-factory.kr/ids/cd/SolderCream/1/0` ×3
    - `https://www.smart-factory.kr/ids/cd/n_modules/1/0` ×2
    - `https://www.smart-factory.kr/ids/cd/Chips/1/0` ×2
    - `https://www.smart-factory.kr/ids/cd/GoodPCB/1/0` ×2
    - `https://www.smart-factory.kr/ids/cd/DefectPCB/1/0` ×2
    - `https://www.smart-factory.kr/ids/cd/DepNext/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/SMTProcess/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/SMTLines/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/Line_1/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/Line_2/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/SMTMaterials/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/MODEL_A/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/MODEL_B/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/MODEL_C/1/0` ×1
  - external(예상): 고유 1종
    - `https://example.com/ids/cd/0445_8041_5062_7858` ×1

### [Models3D 서브트리 — 방금 import 한 IDTA 3D 템플릿 (미비는 예상됨)]
**A. description 누락**: 총 0 (actionable 0 / CD로 커버 0)
**B. semanticId 누락**: 0
**C. dangling CD (참조하나 CD 없음)**: project 7 / external 0
  - project(실제 누락): 고유 7종
    - `https://www.smart-factory.kr/ids/cd/LoaderModel3D/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/SPIModel3D/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/ScreenPrinterModel3D/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/MounterModel3D/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/ReflowModel3D/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/UnloaderModel3D/1/0` ×1
    - `https://www.smart-factory.kr/ids/cd/AOIModel3D/1/0` ×1

### [CD 불완전] hard 156 / soft(unit만) 115
  - 결함 조합 분포: no dataType×103; no definition×50; no definition+no dataType×3
    - `SimulationModel` (https://admin-shell.io/idta/SimulationModels/SimulationModel/1/1): no dataType [+soft no unit]
    - `TypeOfModel` (https://admin-shell.io/idta/SimulationModels/TypeOfModel/1/0): no definition [+soft no unit]
    - `BT5_10` (BT5_10/1/0): no definition [+soft no unit]
    - `BT5_11` (BT5_11/1/0): no definition [+soft no unit]
    - `BT5_12` (BT5_12/1/0): no definition [+soft no unit]
    - `BT5_13` (BT5_13/1/0): no definition [+soft no unit]
    - `BT5_14` (BT5_14/1/0): no definition [+soft no unit]
    - `BT5_20` (BT5_20/1/0): no definition [+soft no unit]
    - `BT5_30` (BT5_30/1/0): no definition [+soft no unit]
    - `BT5_31` (BT5_31/1/0): no definition [+soft no unit]
    - `BT5_40` (BT5_40/1/0): no definition [+soft no unit]
    - `BT5_41` (BT5_41/1/0): no definition [+soft no unit]
    - `BT5_42` (BT5_42/1/0): no definition [+soft no unit]
    - `BT5_50` (BT5_50/1/0): no definition [+soft no unit]
    - `BT5_51` (BT5_51/1/0): no definition [+soft no unit]
    - `BT5_52` (BT5_52/1/0): no definition [+soft no unit]
    - `BT5_60` (BT5_60/1/0): no definition [+soft no unit]
    - `BT5_61` (BT5_61/1/0): no definition [+soft no unit]
    - `BT5_62` (BT5_62/1/0): no definition [+soft no unit]
    - `BT5_70` (BT5_70/1/0): no definition [+soft no unit]
    - `BT5_71` (BT5_71/1/0): no definition [+soft no unit]
    - `BT5_72` (BT5_72/1/0): no definition [+soft no unit]
    - `BT5_73` (BT5_73/1/0): no definition [+soft no unit]
    - `BT5_74` (BT5_74/1/0): no definition [+soft no unit]
    - `BT5_75` (BT5_75/1/0): no definition [+soft no unit]
    - `BT5_80` (BT5_80/1/0): no definition [+soft no unit]
    - `BT5_90` (BT5_90/1/0): no definition [+soft no unit]
    - `BT5_100` (BT5_100/1/0): no definition [+soft no unit]
    - `BT5_110` (BT5_110/1/0): no definition [+soft no unit]
    - `BT5_120` (BT5_120/1/0): no definition [+soft no unit]
    - `BT5_121` (BT5_121/1/0): no definition [+soft no unit]
    - `BT5_122` (BT5_122/1/0): no definition [+soft no unit]
    - `BT5_123` (BT5_123/1/0): no definition [+soft no unit]
    - `ProcessOQC` (ProcessOQC/1/0): no definition [+soft no unit]
    - `OQC` (OQC/1/0): no definition [+soft no unit]
    - `SamplingRate` (SamplingRate/1/0): no definition [+soft no unit]
    - `ProcessRMA` (ProcessRMA/1/0): no definition [+soft no unit]
    - `RMA` (RMA/1/0): no definition [+soft no unit]
    - `W4_StockShortage` (W4_StockShortage/1/0): no definition [+soft no unit]
    - `ShelftLife` (ShelfLife/1/0): no dataType
    - … 외 116개