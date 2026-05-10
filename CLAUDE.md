# 프로젝트 규칙

CPRO 조립공정 시뮬레이션 패키지.

## 입력 데이터 contract

- 시뮬레이션의 유일한 외부 입력은 **AAS 템플릿을 따르는 JSON 파일들** 이다.
- AAS JSON 접근은 **`path_extractor.py` 단일 진입점**만 사용한다. 시뮬 코드(예: `cpro_simulation_ver3.py`)는 `load_aas()` 가 반환하는 `AASModel` dataclass 의 필드만 읽는다. JSON 을 직접 파싱하지 말 것.
- 같은 AAS 템플릿을 따르는 어떤 입력 데이터든 동일한 코드로 동작해야 한다. 특정 모델 ID, 특정 코드값, 특정 idShort 키워드에 종속된 분기가 있으면 안 된다.

## 금지 사항

### AAS 에 명시되지 않은 패턴 의존 금지

다음과 같은 추론은 금지한다 — 데이터가 바뀌면 조용히 깨진다:

- PCB 코드 prefix(`0320` vs `0390`) 로 main/THT 구분
- `GroupIdShort` 키워드(`FwInput`, `Gimbal` 등) 로 공정 분류
- `InputBOM` 의 위치/순서로 의미 추론
- pcb_entries 의 `components` 유무로 종류 구분

위 패턴이 필요한 로직이라면, **먼저 AAS 템플릿에 해당 정보를 명시적 qualifier 또는 property 로 추가**하고 `path_extractor` 가 그 필드를 추출하도록 수정한 뒤, 시뮬 코드에서 그 필드를 읽는다.

### fallback 금지

- AAS 누락 시 글로벌 default 값으로 떨어지는 fallback 을 두지 말 것 (`dict.get(key, default)` 의 default, `if not x: x = HARDCODED_DICT` 등).
- 누락은 입력 데이터 문제이므로 `raise RuntimeError` 로 즉시 실패시켜 원인을 드러낸다.

## 정책 상수와 정적 데이터

AAS 템플릿에 미반영된 데이터는 모두 **`cpro_config.py`** 한 파일에 섹션 구분으로 모은다. 시뮬 코드(`cpro_simulation_ver3.py`)는 `from cpro_config import *` 한 줄로 사용한다.

`cpro_config.py` 의 섹션 구성:

- 시간 / 진입점 (`RANDOM_SEED`, `DAY_SEC`, `MAX_DAYS`)
- 시뮬 정책 상수 (`MIN_STOCK`, `RMA_*`, `THT_*` 등 — AAS qualifier 로 옮긴 항목은 제거)
- PCB / SMT 라인 매핑 (`PCB_MAP`, `THT_PCB_BY_MODEL`, `SMT_LINE_IDS`)
- 워커 그룹 / 라벨 매핑 (`WWM_LINE_TO_WORKER`, `PROCESS_GROUP_TO_WORKER_GROUP`, `LOCATION_*`)
- 정격 전력 (`RATED_POWER_KW`, `get_rated_power_kw`)
- SMT / RMA 정적 공정 데이터 (`PF_COLS`, `PF_ALL_ROWS`, `RESOURCE_MTTR_HR`)

규칙:
- 시뮬 코드 본문(클래스/함수 안)에는 정책 상수나 정적 데이터 dict 를 정의하지 않는다.
- 새 항목은 적절한 섹션에 추가.
- AAS 템플릿이 확장되어 어떤 항목이 AAS 에서 추출 가능해지면 `cpro_config.py` 에서 제거하고 `path_extractor` 가 추출하도록 수정.
- 임시 글로벌을 **AAS 에서 가져온 것처럼 위장하기 위한 prefix 추론 등 우회 로직은 만들지 말 것**.

## TODO: 시뮬레이션 분기 일반화 (그룹 이름 hardcoding 제거)

시뮬 코드가 `'SMT'`, `'RMA'`, `'OQC'`, `'PACK'`, `'INSP'` 등 특정 ProcessGroup 라벨에 매칭해서 분기하는 곳들이 다수 남아 있다. 다른 공장의 AAS 가 자유 형식 라벨(`'GHT_MEI'`, 숫자 코드 등)을 보내도 동작해야 한다는 contract 위반. 라벨 매칭 대신 **AAS qualifier 또는 그래프 토폴로지** 같은 데이터 기반 식별로 옮길 것.

### A. 흐름 자체가 일반 KG 와 다른 경우 (시뮬 핸들러 분기)

1. **SMT 컨베이어 라인** (`'SMT'`/`'SMT_SHARED'`): `SMTLine` 클래스, `KG_EXCLUDED_PROCESS_GROUPS`, `wip.enter('SMT')`, `energy.record(_,'SMT',_)` 다수.
   → AAS qualifier `LineType: SmtConveyor` 또는 토폴로지(stage chain) 로 식별.
2. **RMA 재투입** (`'RMA'`/`'RMA_REPAIR'`): `run_rma`, `_rma_repair_and_reinsert`, `energy.record('RMA_REPAIR','RMA',_)`, `KG_EXCLUDED_PROCESS_GROUPS` 의 `'RMA'`.
   → AAS qualifier `LineType: ReworkLine`.
3. **THT 외주**: `OutsourceTruckPool`, `PCB_MAP`/`THT_PCB_BY_MODEL`, `THT_DELAY_*`.
   → AAS qualifier `PcbType: Main/Tht` + `LineType: OutsourceShipment`.

### B. 일반 KG 흐름 안의 노드별 변형 (qualifier 로 옮기기 가장 쉬움)

4. **OQC 5% 샘플링** — ✅ 처리 완료 (`ProcessNode.SamplingRate` qualifier).
5. **AOI defect action** (`'repair'`/`'scrap'`): `AOI_DEFECT_ACTION` 글로벌.
   → ProcessNode qualifier `DefectAction`.
6. **SET_INSP 분리**: `resolve_worker_group` 의 `wgrp=='WORKER_SET' & grp=='SET' & pc.endswith('_INSP')` 하드코딩.
   → ProcessNode qualifier `RequiresInspector` 또는 별도 워커 매핑 명시.

### C. PACK 진입 식별

7. **`_find_pack_entry`**: `process_group=='PACK'` + INSP 합류 검사.
   → ProcessNode qualifier `IsPackEntry` 또는 토폴로지 (`DepNext` 없는 합류 노드).

### D. 모니터링 / 통계

8. **`WIP_TRACKED_GROUPS` 고정 7개 그룹**.
   → 동적 (`for grp in self.wip:`). 라벨 자유.
9. **`PROCESS_GROUP_DEFAULT_KW`**: `RATED_POWER_KW` 못 찾을 때 group 기본값.
   → 검증기에서 `RATED_POWER_KW` 누락 raise. fallback 자체 제거.
10. **`PCB_MAP` / `THT_PCB_BY_MODEL`**: 모델별 main/THT PCB 코드.
    → AAS `pcb_entries` 의 qualifier `PcbType: Main/Tht` 도입.

### 진행 원칙

- **B 부터** (4의 OQC 패턴 그대로 적용 가능).
- **A** 는 핸들러 자체는 도메인 특화로 유지하되, AAS qualifier 로 식별만 옮김.
- 새 qualifier 도입 = AAS 템플릿 확장 + `path_extractor` 추출 + 시뮬 사용.


## 시각화 분리

- 시각화(엑셀 저장, PNG 저장) 코드는 `cpro_visualization.py` 에 격리되어 있다. `cpro_simulation_ver3.py` 의 `ExperimentRunner.save_results` / `save_figures` 가 thin wrapper 로 위임한다.
- `cpro_visualization.py` 는 시뮬 모듈을 import 하지 않는다 (단방향 의존). 필요한 상수는 keyword argument 로 주입한다.
