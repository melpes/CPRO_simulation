# 프로젝트 규칙

CPRO 조립공정 시뮬레이션 패키지.

## 입력 데이터 contract

- 시뮬레이션의 유일한 외부 입력은 **AAS 템플릿을 따르는 JSON 파일들** 이다.
- AAS JSON 접근은 **`path_extractor.py` 단일 진입점**만 사용한다. 시뮬 코드(예: `simulation_ver1.py`)는 `path_extractor` 가 노출하는 `ProvisionofSimulationModelsAAS` 의 필드만 읽는다. JSON 을 직접 파싱하지 말 것.
- 같은 AAS 템플릿을 따르는 어떤 입력 데이터든 동일한 코드로 동작해야 한다. 특정 모델 ID, 특정 코드값, 특정 idShort 키워드에 종속된 분기가 있으면 안 된다.

## `path_extractor` (AAS 접근 계층) 구조 규칙

### 외부 노출
- 클래스 `AssetAdministrationShell` (범용 AAS 타입) 과 **모듈 레벨 인스턴스 `ProvisionofSimulationModelsAAS`** 가 외부 진입점.
- `__all__` 에는 인스턴스 `ProvisionofSimulationModelsAAS` 만 둔다 (모듈 import 의 자연스러운 싱글톤).
- 시뮬 코드: `from aas_architecture import ProvisionofSimulationModelsAAS` → `ProvisionofSimulationModelsAAS.submodels[...]....` 로 모든 AAS 데이터 접근.
- 인스턴스명은 실제 AAS 의 idShort 와 동일. 다른 AAS 가 필요해지면 같은 클래스 `AssetAdministrationShell` 로 새 인스턴스 추가.

### AAS 명시 연산의 단일 구현처 (path_extractor 가 연산도 보유)

- **AAS 에 정의된 변수·연산은 모두 path_extractor 에 함수(메서드)로 구현한다.** 시뮬 코드(ver1)는 그 메서드를 **호출만** 하고 같은 로직을 다시 작성하지 않는다. AAS 의 `description` 은 참고용이며 진실의 원천은 그 메서드 본문이다.
- 대상은 특히 **`RuntimeVariables`** — 에피소드 중 동적으로 변해 AAS 에 `value=None` 으로 정의만 있는 변수들. 각 변수의 description 이 명시하는 산출/누적 규칙을 해당 위치 바인딩 도메인 클래스(`RuntimeVariables`, `_positions` 로 `('SimulationModels','SimulationModel','RuntimeVariables')` 바인딩)의 메서드로 구현한다.
- 메서드 규약: **순수 산출형**은 런타임 입력만 받아 값 반환, **누적형**은 마지막 인자로 현재값을 받아 다음값 반환 (path_extractor 는 에피소드 상태를 보유하지 않는다 — 순수 함수).
- path_extractor 는 **torch 등 시뮬/ML 의존성을 import 하지 않는다**. 순수 파이썬으로 구현하고 tensor 화는 시뮬 코드가 한다.
- 동명 메서드가 자식 Property(value=None)를 shadow 한다. raw Property 가 필요하면 `rv['CycleCompleted']` (`__getitem__`) 로 접근.
- 이 절은 아래 "클래스 인스턴스 = 값 그 자체 / 방어·추상화 자제 / 시뮬은 필드만 읽는다" 규칙의 **명시적 예외**다. 그 규칙들은 여전히 데이터 필드 접근의 기본값이고, 본 절은 AAS 가 description 으로 연산을 규정한 항목에 한해 적용된다.

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

ver1 은 정책 상수·하이퍼파라미터를 **AAS 에서 직접 추출**한다 (`DefaultParameters`, `RewardWeights`, `ModelArchitecture.GNN`/`PPO.TrainingConfig`, `Warehouse.MinStock` 등). 별도 `cpro_config.py` 는 두지 않는다 (ver0/ver3 시절의 정책상수 모음 파일로, 현재 미사용·삭제됨).

규칙:
- AAS 에 있는 값은 `path_extractor` 메서드/필드로 추출해 시뮬·도구 코드가 읽는다. 본문에 정책상수 dict 를 정의하지 않는다.
- AAS 미반영 정책값(예: `IdlePowerRatio=0.10`)은 **도구의 env 빌더(`make_env`/`make_envs`/`_timeit.build`) 호출부에서 키워드 인자로 주입**한다 (코딩 스타일 12번 — 본문에서 글로벌 import 금지).
- 새 정책값이 생기면 우선 AAS 템플릿 확장 + `path_extractor` 추출을 검토하고, 불가피할 때만 도구 주입.
- 임시 글로벌을 **AAS 에서 가져온 것처럼 위장하기 위한 prefix 추론 등 우회 로직은 만들지 말 것**.

## 시뮬레이션 분기 일반화 (라벨 hardcoding 제거) — ver1 에서 대부분 해소

ver3 가 `'SMT'`/`'RMA'`/`'OQC'`/`'PACK'` 등 ProcessGroup 라벨로 분기하던 문제(`SMTLine`/`run_rma`/`OutsourceTruckPool`/`resolve_worker_group` 등)는 ver1 에서 **`KnowledgeGraph` + `shared_groups`(AAS `ProcessOQC`/`ProcessRMA` 공용 노드, `model_id='ALL'`) 기반**으로 재설계되며 거의 제거됐다. OQC 확률 게이트는 `ProcessNode.SamplingRate` qualifier 로 처리(`produce_unit`).

- 새 공장 AAS 의 자유 라벨도 그래프 토폴로지·qualifier 로 식별하므로 **라벨 매칭 분기를 새로 추가하지 말 것**.
- 새 노드별 변형이 필요하면 AAS 템플릿에 qualifier 추가 → `path_extractor` 추출 → 시뮬 사용 (`SamplingRate` 패턴 그대로).


## 시각화 분리

- ver1 시각화(영상·간트·히트맵)는 `mod_run/cpro_ver1_viz.py`(공유 렌더 유틸 + `make_envs` env 진입점)와 `mod_run/` 의 도구들(`_render_*`, `_capture_*`, `cpro_worker_util` 등)에 둔다.
- `cpro_ver1_viz` 는 `simulation_ver1` 을 함수 내부에서만 lazy import 하고, AAS·정책값은 호출부에서 주입한다 (단방향 의존).

## `redesign/` 패키지 (legacy 아카이브)

`redesign/`(ver0 의 모듈분할 프리뷰: `kg.py`/`sim_env.py`/`factory.py`/`networks.py`/`runner.py`)는 ver1 이 단일파일 메인이 되며 역할을 다했다. `legacy/redesign/` 으로 아카이브됨(`.gitignore` 비추적). ver1 작업에는 참조하지 않는다.

## ver1 코딩 스타일

`simulation_ver1.py` 의 스타일을 시뮬·도구 코드 전체의 기준으로 삼는다. (구 ver3 의 매니저 객체 분산 / 깊은 분기 / 다층 헬퍼는 이식하지 않는다.)

### 메타 원칙

**가독성과 코드의 실제 흐름 순서가 최우선.** 아래 세부 규칙이 이 원칙과 충돌하면 메타 원칙을 따른다. 애매한 케이스는 작성 중에 물어본다.

### 세부 규칙

1. **명명 — AAS 변수는 idShort CamelCase 그대로, 비-AAS 변수는 snake_case**.
   - AAS 데이터에 존재하는 변수는 idShort 가 CamelCase 이므로 코드에서도 **줄이지 않고 동일한 CamelCase** 로 쓴다 (`Quantity`, `Category`, `WorkstationId`, `ProcessConsumedBOM`). AAS 표기와 코드 표기가 1:1.
   - AAS 에 정의되지 않았으나 코드에서 필요해 만든 파생/순수 로컬 변수는 **Python 기본 권장대로 `_` snake_case** (`model_id`, `present_stock`, `completed`, `in_progress`).
   - **AAS 미정의 변수는 최소화**한다 — 가능하면 AAS 추출값을 직접 쓰고, 임시 파생 변수를 남발하지 않는다.
2. **dataclass + `@classmethod build(cls, <raw>)` 단일 진입점**. 외부 raw 데이터로부터 인스턴스 한 번에 완성. lazy parse / 부분 초기화 / 나중 setter 금지.
3. **Visual alignment**. dataclass 필드 콜론, `__init__` 의 `self.X = X` 대입, kwarg 호출의 `=` 모두 세로 정렬. 멀티라인 함수 호출 인자도 정렬해 펼침.
4. **`#← <AAS 경로>` 인라인 주석** 으로 필드 출처 못박기. 별도 문서/TypedDict 만들지 않음.
5. **타입 힌트는 적극적·명시적**. 모든 함수/메서드 인자·반환, dataclass generic 인자 (`Dict[str, GraphNode]`, `List[GraphEdge]`) 까지. 누락은 "여기 미확정" 의 신호로만 사용.
6. **방어 코드 / `raise` / `try-except` 자제**. 일어나지 않을 케이스 보호 X. AAS 입력 누락은 즉시 fail (fallback 금지 절 참조).
7. **인라인 우선**. 3 회 이상 재사용 OR 인라인이 가독성을 진짜로 해칠 때만 헬퍼 분리. 같은 줄이 두 번 나와도 인라인.
8. **메서드 짧게 (5\~20 줄)**. 한 화면 안에서 위→아래 한 번에 읽혀야 함.
9. **섹션 구분은 `#========이름========`**. `# region` 미사용 (path_extractor 와 의도적으로 다름 — 시뮬 코드는 한눈에 펼침).
10. **simpy 의존은 도메인 dataclass 에 넣지 않는다.** 핵심 제약은 "**도메인 dataclass (`KnowledgeGraph`, `Warehouse`) 에 simpy 결합 금지**" — 이들은 시뮬 외 용도(RL state 추출, AAS round-trip) 로 재사용 가능해야 하므로 simpy coroutine 을 멤버로 두지 않고, 필요한 simpy process 는 자유 함수로 작성해 `env.process(fn(env, ...))` 로 등록한다. 단 **시뮬 컨트롤러(`CproSimEnv`)는 이미 `simpy.Environment` 를 보유한 시뮬 전용 객체**이므로, 그 객체에서만 쓰이는 simpy coroutine 은 `CproSimEnv` 의 제너레이터 **메서드**로 둔다(자유 함수 + `self` 전달 우회 금지). `env.process(self.process_job(...))` 형태. (알려진 잔존 위배: `Warehouse.replenish` — 도메인 dataclass 에 `yield env.timeout` 결합. 별도 후속으로 자유 함수/주입 형태로 분리 검토.)
11. **상태 변경 패턴 (mutating container vs event hook) 은 케이스별 결정**. 새 케이스 만나면 작성 중에 물어본다.
12. **외부 입력은 `__init__` 인자로 주입**. 클래스/함수 본문에서 정책상수 글로벌을 직접 import 하지 않는다 (별도 `cpro_config` 없음 — "정책 상수와 정적 데이터" 절 참조). 결합은 도구 진입점(env 빌더 호출부) 한 곳.
13. **`reset()` 에서 에피소드 상태 재생성**. `simpy.Environment`, `Warehouse`, `completed`, `in_progress`, 트래커들 모두 reset 안에서 새로 만든다. 외부 입력 (`self.X`, `__init__` 에서 받은 것) 은 건드리지 않는다.
14. **변수명 풀네임** (CLAUDE.md 의 path_extractor 규칙과 동일). `Quantity`, `Category`, `ProcessConsumedBOM`, `WorkstationId`. 작은 루프 임시 변수 (`mp`, `ref`, `pn`) 만 약식 허용.
15. **dict 내부 스키마는 필드 옆 inline 주석으로 못박기**. `workers : Dict[str, dict] #{WorkstationId: {'worker_count': int, 'ProcessCode': [...]}}`. TypedDict / dataclass wrapper 만들지 않음.

### 옛 코드(legacy) 발췌 시

legacy(ver0/ver3) 코드를 참고·발췌하더라도 위 규칙으로 다시 쓴다. 매니저 클래스 / 이벤트 핸들러 / util 모듈 / hardcoded 매핑은 그대로 옮기지 않고, 흐름이 한 방향으로 읽히도록 재배치한다.

## ver1 GNN / PPO 참조

ver1 은 도메인 모델·simpy 코어·RL(GNN/PPO) 전부 `simulation_ver1.py` 단일 파일에 구현·검증 완료. 아키텍처의 **진실의 원천은 코드 본문**이다 — 차원·수식을 이 문서에 옮겨 적지 않는다 (다음 리팩터에서 또 stale 해진다).

- **GNN/PPO**: `GNNEncoder`(torch_geometric `GCNConv` ×`NumLayers`) + `Actor`/`Critic` **분리** 모듈 + `PPOAgent`. (ver3 의 수동 GCN·공유 trunk·`GNN.score` 마스킹 명세와 다름.)
- **상태 관측**: `state_vec()` / `state_dim = n_models + 2 + n_workers + 3` — 모델별 throughput, time, energy, ws별 점유율, stock_short/over, idle_avg 의 6 채널 모두 관측.
- **보상**: `potential()` 기반 Φ telescoping (`r_t = Φ(s_{t+1}) − Φ(s_t)`). 현재 **transitional** — W5/W1/W2(throughput·time·energy)만 반영하고 W3/W4/W6(재고·유휴)은 `state_vec` 으로 관측만 하며 보상 반영은 후속 재설계 예정.
- **하이퍼파라미터·차원**: AAS `ModelArchitecture.GNN`/`PPO.TrainingConfig` 에서 주입(고정값 표 아님). 도구 env 빌더(`_capture_oqc.make_env`, `_timeit.build`)가 추출·주입하는 형태가 표준.
