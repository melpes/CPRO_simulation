# 프로젝트 규칙

CPRO 조립공정 시뮬레이션 패키지.

## 입력 데이터 contract

- 시뮬레이션의 유일한 외부 입력은 **AAS 템플릿을 따르는 JSON 파일들** 이다.
- AAS JSON 접근은 **`path_extractor.py` 단일 진입점**만 사용한다. 시뮬 코드(예: `cpro_simulation_ver3.py`)는 `load_aas()` 가 반환하는 `AASModel` dataclass 의 필드만 읽는다. JSON 을 직접 파싱하지 말 것.
- 같은 AAS 템플릿을 따르는 어떤 입력 데이터든 동일한 코드로 동작해야 한다. 특정 모델 ID, 특정 코드값, 특정 idShort 키워드에 종속된 분기가 있으면 안 된다.

## `path_extractor` (AAS 접근 계층) 구조 규칙

### 외부 노출
- 클래스 `AssetAdministrationShell` (범용 AAS 타입) 과 **모듈 레벨 인스턴스 `ProvisionofSimulationModelsAAS`** 가 외부 진입점.
- `__all__` 에는 인스턴스 `ProvisionofSimulationModelsAAS` 만 둔다 (모듈 import 의 자연스러운 싱글톤).
- 시뮬 코드: `from aas_architecture import ProvisionofSimulationModelsAAS` → `ProvisionofSimulationModelsAAS.submodels[...]....` 로 모든 AAS 데이터 접근.
- 인스턴스명은 실제 AAS 의 idShort 와 동일. 다른 AAS 가 필요해지면 같은 클래스 `AssetAdministrationShell` 로 새 인스턴스 추가.

### 클래스 인스턴스 = 값 그 자체 (JSON lazy parse 금지)
- 클래스는 dataclass 로 선언하고, 인스턴스 생성 시점에 각 필드에 **이미 값이 채워져 있어야** 한다.
- `sme.idShort` 같은 접근은 dict lookup 이 아니라 이미 대입된 값을 반환. raw JSON dict 를 들고 다니며 lazy 파싱하는 구조 금지.
- AAS 에 존재하더라도 시뮬에서 사용하지 않을 필드는 **dataclass 에 선언하지 않는다** (예: `category`, 미사용 valueType 등). 사용 결정된 필드만 가져옴.

### dataclass 컨벤션
- 모든 dataclass 는 **`@dataclass(kw_only=True)`** 로 선언. 모든 필드가 키워드 전용이 되어 상속 시 필드 순서 제약이 사라지고, 인스턴스화 시 의도가 명확해진다.
- 항상 존재해야 하는 필드는 **default 를 주지 않는다** (필수 표시). `Optional[X] = None` 은 진짜로 없을 수 있는 값에만 사용. AAS 스펙상 반드시 있는 필드(예: `Entity.entityType`, `RelationshipElement.first/second`, `ReferenceElement.value`, `SubmodelElement.semanticId`)는 default 없이 선언.
- 두 개 이하로 값이 제한된 문자열 필드는 **`Enum` 으로 표현** (예: `EntityType(str, Enum)` — `SelfManagedEntity` / `CoManagedEntity`).

### 자식 접근 통일 규칙
- `container.idShort` — 자식 idShort 가 고정일 때 (idShort 그대로 속성명)
- `container[idShort]` — 자식 idShort 가 다양 (SMC)
- `container[i]` — 정수 인덱스 (SML, 순서 의미)
- `container[...]` — 모든 자식 (list 반환)
- `container[predicate]` — callable 필터  ex) `BOMCategory[lambda x: x.idShort == c]`
- `for x in container` — 순회

### SME 자체 필드
- `.idShort`, `.modelType`, `.semanticId`, `.value`, `.entityType`, `.first`, `.second`, `.min`, `.max` 등 SME 종류별 표준 필드만.

### Qualifier
- `Qualifier` 클래스는 `dict` 를 상속한 `{type: value}` dict. 추후 qualifier 관련 메서드 부착 위치.
- `SubmodelElement.Qualifier` 필드의 타입이자 값. 별도 wrapper/변환 없이 dict 자체.
- 접근: `sme.Qualifier` → 전체 Qualifier dict. `sme.Qualifier['SMT_Side']` → value 직접. 누락 시 dict 표준 KeyError.

### Reference / 경로
- `semanticId` 는 `str` 서브클래스 — 인스턴스 자체가 CD URL 문자열.
- `SubmodelElement.semanticId` 는 단일 `semanticId` (CD URL 하나).
- `ReferenceElement.value` 와 `RelationshipElement.first/second` 는 `List[semanticId] | SMEPath` (체인 또는 SME 경로).
- `ReferenceElement.target` 은 경로가 가리키는 대상의 특정 속성값 (구현 TBD). `value` 의 실제 타입 보고 분기.

### 이름 규약
- 클래스/필드명은 **AAS 상의 실제 이름과 대소문자·표기 완전히 동일**. 차이는 리스트일 때 `s` 접미 정도만 허용.

### 파일 구조 (region)
- 섹션 구분은 `# region` / `# endregion` 으로 감싼다 (IDE 접기 지원).
- 클래스 내부도 `# region [구조]` (dataclass 필드) 와 `# region [로직]` (메서드) 으로 분리한다.

### 방어 코드 / 추상화 자제
- `raise` / `RuntimeError` / `TypeError` 같은 런타임 에러는 **가급적 사용 금지**. 일어나지 않을 케이스에 대한 방어적 type guard, defensive check 등은 추가하지 말 것. 분기 끝에서 처리할 게 없으면 그냥 `return ...` 또는 자연스러운 실패에 맡긴다. (단 입력 데이터 누락 raise 는 별개 — "fallback 금지" 절 참조. 그리고 `__getattr__` 의 `AttributeError` 등 Python 프로토콜이 요구하는 raise 는 예외.)
- **한 번만 쓰일 함수/메서드는 분리하지 않는다.** 헬퍼 추출은 두 번 이상 재사용되거나 길이가 정말로 부담스러울 때만. 분기 안에 인라인으로 두는 게 더 명확하면 그대로 둔다.

### 변수명 풀네임
- 변수명은 **줄여쓰지 않는다**. `val` X → `value` O. `subs` X → `submodels` O. `sm` X → `submodel` O.
- 클래스 필드명과 지역변수명이 겹치면 그대로 둔다 (Python scope 분리). 정말 모호하면 접사 (`value_dict`, `child_value`, `submodels_dict` 등) 를 붙인다.

### Multi-collection join / lookup 패턴
SME 트리에서 "A 컬렉션의 각 요소에 대해 B 컬렉션을 찾아 짝짓고 값 추출" 같은 vectorized join 이 필요한 경우 (예: `Warehouse[item_code].OrderRatio` 채우기 — 엔티티의 Category qualifier 와 BOMCategory 의 idShort 매칭) 다음 원칙을 따른다.

- **명시적 loop + 작은 헬퍼**로 처리한다. pandas DataFrame 변환이나 query DSL 구축 같은 추상화는 **만들지 않는다**.
- 이유:
  - pandas 는 외부 의존 — 패키지 의존성을 늘리지 않는다.
  - DataFrame 으로 변환하면 SME 트리의 구조적 의미가 사라진다. SME / Qualifier / semanticId 의 도메인 표현을 그대로 유지해야 한다.
  - 사람이 작성한 AAS 규모의 데이터라 O(m·n) 도 문제없음 — vectorized 가 필요한 성능 임계가 아니다.
  - join 패턴이 시뮬 코드 전반에서 많지 않음. 추상화 비용이 회수되지 않는다.
- 공통 헬퍼는 필요해질 때 모듈 레벨로 두 개 정도만 만든다 — 예: `_flatten(sme)` (트리를 모든 후손 SME 리스트로), `_tail(semanticId)` (URL 끝의 idShort 추출). 그 이상의 query API 는 추가하지 말 것.
- 예시 형태:
  ```python
  flat_entities = list(_flatten(Hs.MODEL_A.statements))
  bom_lookup = {_tail(bc.semanticId): bc for bc in Hs.MODEL_A.BOMCategory.value.values()}
  for entity in flat_entities:
      bom = bom_lookup[entity.Qualifier['Category']]
      Warehouse[_tail(entity.semanticId)].OrderRatio = bom.OrderRatio.value
  ```

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

## `simulation_ver0.py` 구동 진행률

`cpro_simulation_ver3.py` 의 동작을 ver0 에서 재구현 중. 구성요소별 구현률은 작업 시 갱신. **% 갱신 규칙**: 새 항목 구현·확장 직후 같은 커밋에서 본 표를 수정. 상태는 `0% → ~50%(부분) → 100%(완료)` 단순 단계로 본다.

**총 진행률: 9%** (가중평균 — 도메인 모델 40%, simpy 코어 40%, RL 20%)

### 도메인 모델 / 상태 추적자

| # | 컴포넌트 | 진행률 | 비고 |
|---|---|---:|---|
| 1 | 시간/근무 글로벌 (`_active_schedule`, `_is_work_time`, `_next_work_start`, `work_timeout`, `_work_seconds_between`) | 10% | `CproSimEnv._is_work_time` 부분만. 글로벌 `_active_schedule` 없음 |
| 2 | `_log_event` / `_EVENT_BUF` | 0% |  |
| 3 | `GraphNode` / `GraphEdge` / `KnowledgeGraph` | 40% | `build`/`ready_queue`/`_bom_satisfied` ✓. `dep_type`/`worker_group`/`rated_kw`/`transfer_time`/`feat`/`get_adj`/`get_feat_matrix` 미구현 |
| 4 | `ReadyContext` + `ReadyStatus` + `is_process_ready` | 0% | 현재 `_bom_satisfied` 만 |
| 5 | `StockItem` / `Warehouse` | 30% | `consume`/`replenish` ✓. `wait_stock`/`restore`/`snapshot_loop`/`pcb_flow`/`outsource_log`/demand 기반 초기재고 ✗ |
| 6 | `WIPTracker` | 0% |  |
| 7 | `EnergyLogger` | 5% | `total_energy_kwh: list[float]` 한 개 |
| 8 | `IdleTracker` | 0% |  |
| 9 | `SolderCream` | 0% |  |
| 10 | `OutsourceTruckPool` | 0% |  |
| 11 | `SMTLine` | 0% |  |
| 12 | `ProcessActivityLogger` | 0% |  |

### simpy 코어 (env.process 등록 코루틴 / 메인 컨테이너)

| # | 컴포넌트 | 진행률 | 비고 |
|---|---|---:|---|
| 13 | `CproSimEnv.__init__` / `_init_sim` (자원·프로세스 등록 컨테이너) | 15% | 필드 받기만. `wres`/`aoi_res`/`rma`/`smt_lines`/`outsource_pool` 미생성 |
| 14 | `CproSimEnv.reset` | 20% | 부분 — `Warehouse.build` 호출 ✓, simpy.Environment 생성 ✓. 나머지 자원 미생성 |
| 15 | `CproSimEnv.step` / `run` | 10% | step 골격만. `run(until=stop_event)` 미구현 |
| 16 | `process_job` / `run_process` | 10% | `process_job` 단순형만. 근무시간/BOM wait/skill/JOIN-AnyOf/defect 분기 ✗ |
| 17 | `produce_unit` (KG 워크플로우) | 0% |  |
| 18 | `run_rma` (RMA 큐 핸들러) | 0% |  |
| 19 | `_smt_schedule` / `_run_line` (SMT 보드 발사) | 0% |  |
| 20 | `_event_smt_breakdown` / `_event_worker_absent` / `_event_replenishment` / `_deliver` | 0% |  |
| 21 | `monitor` (콘솔 대시보드) | 0% |  |
| 22 | `wh.snapshot_loop` / `wip.snapshot_loop` / `_check_done` | 0% |  |

### RL (옵션 — greedy 모드 동작 후 추가)

| # | 컴포넌트 | 진행률 | 비고 |
|---|---|---:|---|
| 23 | `ProcessGNN` (2-layer GCN + score head) | 0% |  |
| 24 | `PPOAgent` (encoder + actor/critic + GAE + clip) | 0% |  |
| 25 | `ManufacturingEnv.get_state` / `reward` (6항 분해) | 0% |  |
| 26 | `ExperimentRunner.run_ppo_training` / `run_inference` | 0% |  |

### 보조

| # | 컴포넌트 | 진행률 | 비고 |
|---|---|---:|---|
| 27 | `cpro_visualization.py` 위임 (`save_results`/`save_figures`) | 0% | ver3 코드 그대로 재사용 가능 |

## GNN / PPO 아키텍처 명세

ver3 의 `ProcessGNN` / `PPOAgent` 를 ver0 에 그대로 옮길 때의 spec. **forward 계산 흐름과 차원**을 박아놓아 재구현 시 차원 불일치를 막는다.

### ProcessGNN — 노드 임베딩 + per-node score

학습 파라미터를 가진 모듈은 `Linear` 3개. mp(인접행렬 곱)는 파라미터 없는 텐서 연산이라 별도 모듈 아님.

```
입력  H   : (N, in_dim=6)         # 노드 피처 (정규화된 ct, dr, worker_count/20, kw/100, fork_flag, join_flag)
입력  adj : (N, N)                # 인접행렬 (KG.edges 에서 빌드)

A_n = adj / row_degree.clamp(min=1e-6)        # row-normalized adjacency

H1 = ReLU( conv1( A_n @ H  ) )    # (N, 32)   ← GCN layer 1  (1-hop)
H2 = ReLU( conv2( A_n @ H1 ) )    # (N, 16)   ← GCN layer 2  (2-hop)

score(H2) : (N, 1) → squeeze → (N,)            # forward() 의 출력 = per-node logit
graph_embed = H2.mean(dim=0) : (16,)           # graph_embed() / act() 에서 사용
```

| 모듈 | shape | 역할 |
|---|---|---|
| `conv1 = nn.Linear(6, 32)` | (6→32) | GCN layer 1 의 W |
| `conv2 = nn.Linear(32, 16)` | (32→16) | GCN layer 2 의 W |
| `score = nn.Linear(16, 1)` | (16→1) | per-node action score (PPO actor 의 logit) |

**"layer 몇 개냐"**: PyTorch 모듈 관점 = Linear 3개. GCN 논문 관점 = 2 GCN layer + 1 readout (mp 는 학습 파라미터 없는 sub-step). 코드상 mp 는 `A_n @ H` 한 줄로만 등장.

### PPOAgent — actor/critic 공유 인코더 + GNN per-node score

```
state_vec   : (state_dim,)             # state_dim = n_models + n_workers + 6
graph_embed : (16,)                    # GNN.graph_embed() 의 출력

x   = concat(state_vec, graph_embed) : (state_dim + 16,)
enc = encoder(x) : (64,)               # Linear(_, 128) → ReLU → Linear(128, 64) → ReLU
                                        # ← actor/critic 공유 trunk

critic_head(enc) : (1,)                # value V(s)
                                        # actor 의 logit 은 head 가 아니라
                                        # GNN.score(H2) 를 ready_mask 로 마스킹해서 사용
```

학습 흐름 (`act` → `store` → `update`):
```
act(state, H, adj, ready_mask):
    H2          = GNN forward (위 다이어그램)
    emb         = H2.mean(0)
    _, value    = self.forward(state, emb)
    node_scores = GNN.score(H2).squeeze(-1)
                  .masked_fill(~ready_mask, -inf)
    probs       = softmax(node_scores)
    action      = Categorical(probs).sample()
    → return (action, log_prob, value, emb, mask_bytes)

store(s, emb, a, r, lp, v, mask, model_id):
    self.buf.append(...)               # 에피소드 끝까지 누적

update(graphs_cache):
    rewards, values, model_ids ← buf
    advs = GAE(λ=0.95, γ=0.99) over reversed(buf[:-1])
    advs = (advs - mean) / (std + 1e-8)

    for epoch in range(EPOCHS=4):
        for entry in buf[:-1]:
            new_lp = log_prob(a) under fresh GNN forward (mask 복원)
            ratio  = exp(new_lp - old_lp)
            loss_p = -min(ratio*adv, clip(ratio, 1-ε, 1+ε)*adv)   # PPO-clip, ε=0.2
            loss_v = MSE(critic_out, old_value)
            loss   = loss_p + 0.5 * loss_v
            backward → clip_grad_norm_(0.5) → optimizer.step()
    buf.clear()
```

| 하이퍼파라미터 | 값 |
|---|---:|
| LR (Adam) | 3e-4 |
| GAMMA (γ) | 0.99 |
| LAM (λ, GAE) | 0.95 |
| EPS (PPO clip) | 0.2 |
| EPOCHS (per update) | 4 |
| value loss weight | 0.5 |
| grad clip norm | 0.5 |
| CONV_WINDOW / THRESHOLD (조기종료) | 100 / 0.01 |

### state_vec / reward 구성 (`ManufacturingEnv`)

```
state_vec (n_models + n_workers + 6 차원):
    completion_per_model        : n_models      # done/total per model
    worker_utilization          : n_workers     # 1 - count/capacity per group
    energy_per_sec              : 1             # energy.total / (env.now+1)
    time_progress               : 1             # env.now / t_max
    stock_penalty_norm          : 1             # wh.stock_penalty() / total_order
    wip_violation_norm          : 1             # wip.violations() / n_workers
    idle_penalty_norm           : 1             # idle.worker_idle_penalty() / (env.now+1)
    smt_breakdown_ratio         : 1             # broken / (n_smt_pcs+1)

reward = w1·r1 + w2·r2 + w3·r3 + w4·r4 + w5·r5 + w6·r6
   W_DEFAULT = (0.30, 0.25, 0.15, 0.10, 0.10, 0.10)
   r1 = -dt_wall / t_max                       # 시간 페널티
   r2 = -d_kwh / (kwh_now+1)                   # 전력 증가분 페널티
   r3 = -d_wip / n_workers                     # WIP 위반 증가
   r4 = -d_stock / (total_order * 10)          # 재고 부족 증가
   r5 =  d_done / total_order  (+1.0 if 완성)   # 생산 보상
   r6 = -d_idle / (total_cap * dt_work)        # 유휴 증가
```
