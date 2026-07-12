# 코드 주석·docstring 아카이브

> simulation 패키지 루트 `.py` 의 주석/docstring 을 코드에서 분리해 보존한 문서.
> 코드 본문에는 주석을 두지 않는다(요청). `# -*- coding -*-` 인코딩 선언만 유지.
> 항목은 원본 라인 순. (재구성 시점 자동 추출)

## `path_extractor.py`

**모듈 설명**

```
AAS 메타모델 — 시뮬레이션이 AAS 데이터를 받는 유일한 창구.

지금 단계: 각 SME / 데이터형식이 갖는 **속성만** 선언. 접근 규칙·로직은 추후 부착.

자식 접근 통일 규칙 (TBD)
    container.idShort        # 자식 idShort 가 고정 — idShort 그대로 속성명
    container[idShort]       # 자식 idShort 가 다양 (SMC)
    container[i]             # 정수 인덱스 (SML, 순서 의미)
    container[...]           # 모든 자식
    container[predicate]     # callable 필터

SME 자체 필드
    .idShort  .semanticId  .Qualifier  .value  ...

Qualifier
    sme.Qualifier              → {type: value} dict
    sme.Qualifier['SMT_Side']  → value 직접

경로 deref (TBD)
    refElem.target
```

**docstring (클래스·함수)**

- **`class semanticId`** (L49):

```
ConceptDescription 참조 — 인스턴스 자체가 CD URL 문자열.

    >>> s = semanticId('https://.../ids/cd/Process/1/0')
    >>> s == 'https://.../ids/cd/Process/1/0'   # True (str 그 자체)
```

- **`class SMEPath`** (L57):

```
SME 경로 — 식별자(URL/IRDI)와 idShort 들의 sequence (list 의 일종).

    `List[semanticId]` 와의 차이:
        - SMEPath: 키들이 chain 으로 연결돼 단일 대상 SME 를 가리킴 (target = 경로 끝)
        - List[semanticId]: 각 키가 독립된 대상을 가리킴 (target = 대상들의 list)
```

- **`class Qualifier`** (L80): `{type: value}` dict 자체. 이름 Qualifier 로 식별, 추후 메서드 부착 위치.
- **`class Submodel`** (L139): 자식 idShort 로 키된 dict.
- **`class ManufacturingProcess`** (L146): 제품 AAS 의 ManufacturingProcess Submodel.
- **`class SubmodelElementCollection`** (L172): 자식 idShort 로 키된 dict.
- **`class ProcessGroup`** (L178): 공정 그룹 — `value: Dict[str, ProcessNode]`. ProcessType 은 제외 (generic SMC).
- **`class ProcessNode`** (L185):

```
공정 노드. 자식 SME 들은 idShort 로 접근. 자식 중 ReferenceElement 면 자동 deref.
    자식 타입:
        CycleTimeSec  → Property (int)
        DefectRate    → Property (float)
        RatedPowerKw  → Property (float)
        DepPrev       → Property (str, ';' 구분으로 join)
        DepType       → Property (str: 'SEQUENCE'|'JOIN'|'FORK')
        DepNext       → Property (str, ';' 구분으로 join) — 옵셔널. 공용 노드(OQC 등)가
                        자신의 후속을 선언해 모델별 MP 의 DepPrev 를 수정하지 않고 edge 형성.
        InputBOM      → InputBOM (dict-like {item_code: Quantity})
        DepWaitSec    → DepWaitSec (Property, 옵셔널 — 본드 경화·AGING 등 후처리 대기)
        SamplingRate  → SamplingRate (Property, 옵셔널 — 확률적 분기 게이트)

    위치 매칭 (`_positions`):
        - 모델별 MP 의 그룹·노드 — 'ManufacturingProcess', '*', '*'
        - PSM 의 모델 공용 노드 (ProcessOQC/ProcessRMA 등) — model_id='ALL' 흐름.
```

- **`class SMTEquipmentProcess`** (L250):

```
SMT 라인 설비 공정 노드 (LoaderProcess/ScreenPrinterProcess/SPIProcess/MounterProcess/
    ReflowProcess/UnloaderProcess/AOIProcess). 위치: SMTProcess.SMTLines.<Line_N>.<설비>Process.
    자식: DepPrev/DepType (inline Property), CycleTimeSec/RatedPowerKw (ReferenceElement →
          설비 카탈로그 AAS 조회), Materials (Operation, PCB IO — chunk 2 에서 사용).
    cycle/power 는 본 노드 semanticId(=설비 카탈로그 AAS ref, 예 /ids/aas/Loader/1/0) 로
    카탈로그 Submodel 을 찾고, 자식 ref 의 CD semanticId 로 Property lookup
    (WWMPropertyRef 와 동일한 cross-AAS deref 패턴).
```

- **`class BOMCategory`** (L280): BOMCategory 컨테이너 — `value: Dict[Category_idShort, BOMCategoryEntry]`.
- **`class BOMCategoryEntry`** (L286):

```
단일 BOM 카테고리. 자식 Property 값을 직접 노출 (Property wrapper 제거).
        MinStock   → int
        MaxStock   → int
        OrderRatio → float
```

- **`class RuntimeVariables`** (L303):

```
PSM SimulationModel.RuntimeVariables — 에피소드 중 동적으로 변하는 상태.

    AAS 는 각 변수의 정의(description)만 보유하고 value=None (실행 중 결정).
    이 클래스가 그 정의에 대응하는 **AAS 명시 연산의 단일 구현처**다. 시뮬
    코드(ver1)는 메서드를 호출만 하고 같은 로직을 다시 작성하지 않는다.
    description 은 참고용이며 진실의 원천은 아래 메서드.

    동명 메서드가 자식 Property(value=None) 를 shadow 한다. raw Property 가
    필요하면 `rv['CycleCompleted']` 처럼 __getitem__ 으로 접근.

    메서드 규약:
      - 순수 산출형: 런타임 입력만 받아 값 반환.
      - 누적형: 마지막 인자로 현재값을 받아 다음값을 반환 (상태 미보유).
```

- **`class SubmodelElementList`** (L446): 순서 의미 — index 로 접근하는 list.
- **`class InputBOM`** (L456):

```
공정 input BOM. SML of ReferenceElement 를 dict-like `{item_code: Quantity}` 로 노출.
    item_code = ref 의 첫 키 (CD URL) 의 idShort 부분. Quantity = ref 의 Qualifier['Quantity'].
```

- **`class ObservationNodeFeatures`** (L483):

```
GNN 노드 피처 구성 — 각 ReferenceElement 가 ProcessNode 속성의 CD 를 가리킴(순서=피처 벡터 순서).
    attrs() = 그 CD 들의 idShort 리스트 = obs_node_features 가 노드마다 getattr 할 속성명. NodeFeatureDim=len.
```

- **`class PurchaseOrder`** (L500):

```
고객 PO (Purchase Order). SMC; 자식 = 모델별 Property(idShort=model_id, value=주문수량,
    Qualifier{DueDay, RegisteredDay} — t=0 기준 경과일). 순회 → (model_id, (Quantity, DueDay, RegisteredDay)).
```

- **`class DepWaitSec`** (L528):

```
공정 cycle_time 이후 다음 공정 ready 까지의 추가 대기 시간 (초).
    워커 비점유 — 본드 경화 같은 후처리 지연을 일반화한 도메인 타입.
    AAS 의 자식 idShort 는 데이터마다 달라도 본 클래스로 통합 추출:
      - BT5_42 본드 경화: idShort='CuringTimeSec', value=86400 (24h)
      - 새 idShort 추가는 본 클래스의 _positions 에 한 줄 추가만 하면 됨.
    ※ AGING (VD7_100/BT5_100/NVD_110) 은 2026-05-28 부터 DepWait 가 아니라 워커 점유
      CycleTimeSec=10800(3h) + WWM UnitsPerWorker=10 (병렬 모니터링) 으로 변경 → 여기서 제외.
```

- **`class SamplingRate`** (L543):

```
노드가 ready 됐을 때 실제 실행될 확률 (0~1). 확률적 분기 게이트.
    AAS 의 자식 idShort 가 무엇이든 본 클래스로 통합 추출:
      - OQC: idShort='SamplingRate', value=0.05 (5% 만 거치고 95% 는 skip)
      - 향후 다른 검사·샘플링 노드도 동일 패턴 재사용 — _positions 에 한 줄 추가.
    시뮬에서 `if random.random() >= node.SamplingRate: done_set.add(pc); continue`
    로 ready 큐 진입 시 확률적으로 소비.
```

- **`def _is_identifier`** (L596):

```
key 가 외부 식별자(IRI URL 또는 IRDI) 인지. idShort 와 구분.
    - IRI: '://' 포함 (URL)
    - IRDI: '#' 포함 (ECLASS '0173-1#XX-NNNNNN#VVV', CDD 등)
```

- **`def _resolve_identifier`** (L603):

```
모든 AAS 의 submodel walk 해서 Submodel.id 또는 SME.semanticId 가
    identifier 와 정확히 일치하는 SME 반환. 못 찾으면 None.
```

- **`def _walk_for_match`** (L618):

```
node subtree 에서 semanticId == target_identifier 인 SME 찾기 (자기 자신 포함).
    `value` (Submodel/SMC/SML) 와 `statements` (Entity) 만 자식 컨테이너로 인정.
    ReferenceElement.value (List[semanticId] str 들) 같은 비-SME 리스트는 자식 아님.
```

- **`class ProcessNodePropertyRef`** (L699):

```
PSM Node.SIM_MODEL_*.<proc>.{CycleTimeSec/DefectRate/RatedPowerKw}.
    value: SMEPath ([SM URL, ProcessGroup_idShort, ProcessNode_idShort, Property_idShort]).
    target: MODEL_N.MP 안의 실제 Property.
```

- **`class ProcessNodeListRef`** (L723):

```
PSM Action.{IndependentSequence/DependentSequence/DependentJoin/AssignedProcessGroups}.*.
    value: List[semanticId] (ProcessNode CD URL 들).
    target: ProcessNode 들의 list (각 CD URL semanticId 매칭, ProcessNode 타입 필터).
```

- **`class AssignedProcessGroupsRef`** (L740):

```
WWM 의 WorkstationInformation.*.AssignedProcessGroups.*.
    value: List[semanticId] — 각 URL 은 ProcessNode CD URL.
    target: 매칭되는 ProcessNode 의 list. 매칭 안 되는 URL (의도된 누락 케이스 OQC/RMA 등) 은 skip.
```

- **`class MPSubmodelListRef`** (L755):

```
PSM Warehouse.InputBOM.
    value: List[semanticId] (MP Submodel URL 들).
    target: ManufacturingProcess Submodel 들의 list.
```

- **`class BOMCategoryRef`** (L769):

```
PSM Warehouse.{MinStock/MaxStock/OrderRatio}.
    value: List[semanticId] (BOMCategory CD URL, 단일).
    target: BOMCategory SMC.
```

- **`class WWMPropertyRef`** (L785):

```
PSM DefaultParameters.{WorkStartTime/WorkEndTime/BreakDurationMin}.
    value: SMEPath ([WWM submodel id URL, Property CD URL]).
    target: WWM 안의 Property (semanticId 가 두 번째 키와 매칭).
```

- **`def _find_submodel_by_id`** (L810): Submodel.id 가 url 과 일치하는 Submodel 인스턴스 반환. 없으면 None.
- **`def _find_submodel_by_semantic`** (L821): Submodel.semanticId 가 url 과 일치하는 Submodel 반환.
- **`def _find_typed_by_semantic`** (L832):

```
semanticId == url 이고 isinstance(target_type) 인 SME 반환.
    같은 semanticId 의 여러 SME 중 target_type 만 골라내 disambiguation.
```

- **`def _walk_for_typed`** (L845): node subtree 에서 semanticId==target_url 이고 isinstance(target_type) 인 첫 SME.
- **`def _idShort_from_cd`** (L863):

```
CD URL 의 idShort 부분 추출 (예외적 유틸 — InputBOM 등 idShort 키가 필요한 경우에만).
    일반적인 ref 매칭은 semanticId 직접 비교 사용.
```

- **`class AssetAdministrationShell`** (L878): AAS 컨테이너 클래스. 범용 타입.
- **`def load`** (L968):

```
JSON 파일 하나 로드. 여러 번 호출해 여러 AAS 를 합쳐 사용.

    AAS idShort 로 라우팅:
      - 'ProvisionofSimulationModelsAAS' → 모듈 레벨 PSM 인스턴스 채움
      - 'WorkstationWorkerMatchingDataAAS' → 모듈 레벨 WWM 인스턴스 채움
      - 그 외 (MODEL_N 등) → 새 AssetAdministrationShell 만들어 ProductAAS 리스트에 append

    ReferenceElement 들은 lazy — target 접근 시점에 _aas_registry 통해 cross-AAS deref (TBD).
```

- **`def _build_sme`** (L1003):

```
raw JSON dict → SubmodelElement 인스턴스 (재귀).
    position: 이 SME 의 트리상 위치 (submodel_idShort, ..., self_idShort).
              도메인 클래스 매칭 (_DOMAIN_BY_POSITION) 에 사용.
```

- **`def _match_domain`** (L1071):

```
SubmodelElement 의 모든 (간접) 서브클래스에서 `_positions` ClassVar 검사.
    매칭되는 클래스 중 가장 구체적인(wildcard 적은) 패턴의 클래스 반환.
    `_positions_excluded` 매칭이 있으면 해당 위치는 generic SME 로 fallback (None 반환).
    `*` 는 wildcard.
```

- **`def _walk_subclasses`** (L1097): root 의 모든 (간접) 서브클래스 yield.
- **`def _cast_value`** (L1104):

```
raw value 를 AAS valueType (xs:int, xs:double, xs:time 등) 에 맞춰 캐스트.
    valueType 없거나 알려지지 않은 타입이면 raw 그대로 반환.
```

- **`def _parse`** (L65): raw reference dict → SMEPath 인스턴스 (체인 경로용). 내부 전용.
- **`def _parse_as_list`** (L72):

```
raw reference dict → List[semanticId] (각 키가 독립 대상인 ref 용).
        SMEPath 가 아닌 일반 reference 들의 공통 파서 — SMEPath 안에 모아둠. 내부 전용.
```

- **`def __getattr__`** (L103):

```
`.idShort` 자식 접근: `value` dict 에서 lookup. (Submodel/SMC 가 해당)
        `value` 가 dict 가 아닌 SME (Property scalar, SML list 등) 는 자연스럽게 TypeError.
```

- **`def _walk_entities`** (L116): 이 노드 트리 아래 모든 Entity yield (자기 자신 포함). 재귀.
- **`def groups`** (L151): ProcessType 같은 비-그룹 자식 제외.
- **`def model_id`** (L156): 이 MP 가 속한 ProductAAS 의 idShort (registry walk).
- **`def DepNext`** (L223): 공용 노드 reverse-edge 선언용. 없으면 None — 일반 노드는 DepPrev 만 사용.
- **`def InputBOM`** (L227): InputBOM 없는 노드도 있으므로 None 허용 (시뮬은 `if not node.InputBOM` 검사).
- **`def DepWaitSec`** (L231):

```
자식 중 DepWaitSec 인스턴스가 있으면 반환. 없으면 None.
        AAS 데이터의 자식 idShort 가 'CuringTimeSec' / 'AgingTestDurationSec' 등
        무엇이든 본 도메인 클래스로 통합 — _positions 매칭으로 isinstance 보장.
```

- **`def SamplingRate`** (L240):

```
자식 중 SamplingRate 인스턴스가 있으면 반환. 없으면 None (= 항상 실행).
        OQC 등 확률적 분기 게이트 노드만 가짐. 시뮬: random < value 일 때만 실행, 그 외 skip.
```

- **`def target_qty`** (L512): {model_id: 주문수량} — build_simulation 의 target_qty 형태로.
- **`def __getattr__`** (L575): Entity 의 자식은 `value` 가 아니라 `statements` dict 에서 lookup.
- **`def _parse_value`** (L653):

```
raw reference → value 필드 값. 기본은 List[semanticId].
        SMEPath 가 필요한 자식 클래스는 override 해서 SMEPath._parse 사용. 내부 전용.
```

- **`def __getitem__`** (L660): ref[i] / ref[idShort] → target[i] / target[idShort] (자기 자신을 target 처럼).
- **`def target`** (L667):

```
value 의 키들로 대상 SME 를 찾는다. 각 키는 외부 식별자(URL/IRDI) 또는 idShort.
            - 식별자: 모든 AAS walk 해서 Submodel.id 또는 SME.semanticId 와 직접 일치 비교
            - idShort: 현재 노드의 자식 dict lookup
            - 첫 키 resolve 후 나머지를 path 로 시도 → path 깨지면 keys 전체를 list 로 간주
```

- **`def __getattr__`** (L886):

```
submodel idShort 로 attribute 접근. `aas.SimulationModels` 등.
        누락 시 KeyError 자연 발생 (hasattr/getattr default 호환 X — 호출부에서 처리).
```

- **`def workers`** (L892):

```
WWM 의 WorkstationInformation 으로부터 `{WorkstationId: {worker_count, ProcessCode}}` 구성.
        AssignedProcessGroups 의 각 ref → ProcessNode 들 → idShort 평탄화.
        AAS 인스턴스 무관하게 동일 결과 (WWM 단일 출처).
```

- **`def _grouped_bom`** (L915):

```
ProductAAS HS entities 를 Qualifier['Category'] 로 그룹핑.
        self_managed=None  : 전부 (기존 WarehouseManagedBOM 동작 — ver0 호환)
        self_managed=False : CoManaged 만   /  True : SelfManaged 만
        Category 없는 entity(모델 루트 등)는 제외.
```

- **`def WarehouseManagedBOM`** (L938): 전체 (SelfManaged 포함). ver0 호환 — 기존 동작 무변경.
- **`def CoManagedBOM`** (L943): CoManaged 부품만. SelfManaged(PCB 등 자체생산 하위조립체)는 제외.
- **`def SelfManagedBOM`** (L948): SelfManaged(Category 보유) 만 — PCB(=SMT_PCB) 등. 별도 창고/모듈 소유.

**주석 (원본 라인 순)**

- L34 — `# region`
- L35 — `# ====================================================================`
- L36 — `# 열거형`
- L37 — `# ====================================================================`
- L41 — `# endregion`
- L44 — `# region`
- L45 — `# ====================================================================`
- L46 — `# 참조 / 경로 / Qualifier (데이터 형식)`
- L47 — `# ====================================================================`
- L81 — `# endregion`
- L84 — `# region`
- L85 — `# ====================================================================`
- L86 — `# SubmodelElement 베이스 — 모든 SME 공통 필드`
- L87 — `# ====================================================================`
- L90 — `# region [구조]`
- L92 `semanticId: semanticId` — `# 필수`
- L93 `Qualifier: Qualifier = field(default_factory=Qualifier)` — `# {type: value}`
- L94 `value: (Dict[str, SubmodelElement]` — `# Submodel, SMC 자식`
- L95 `| List[SubmodelElement]` — `# SML 자식`
- L96 `| List[semanticId] | SMEPath` — `# ReferenceElement 경로`
- L97 `| str | int | float | bool` — `# Property scalar`
- L99 — `# endregion`
- L101 — `# region [로직]`
- L107 — `# dict-like / list-like 위임 (value 가 dict/list 인 SME — Submodel/SMC/SML — 에만 의미 있음)`
- L129 — `# endregion`
- L130 — `# endregion`
- L133 — `# region`
- L134 — `# ====================================================================`
- L135 — `# Submodel 계열`
- L136 — `# ====================================================================`
- L140 `id: str = ''` — `# AAS V3 unique identifier (URL)`
- L163 — `# endregion`
- L166 — `# region`
- L167 — `# ====================================================================`
- L168 — `# SubmodelElementCollection 계열`
- L169 — `# ====================================================================`
- L262 `reference = self.value[child_idShort]` — `# ReferenceElement (CycleTimeSec/RatedPowerKw)`
- L263 `catalog   = _find_submodel_by_id(self.semanticId)` — `# 설비 카탈로그 Submodel (id = 설비 AAS ref).`
- L264 — `#   ★ Submodel.id 매칭만 — 설비노드 자신(같은 semanticId 의 SMC)은 매칭 안 됨(self-match 회피).`
- L265 — `#   카탈로그 미로드면 None → cycle/power None → factory 가 SMT 비활성(stub fallback).`
- L322 — `#← .DefaultParameters.IdleProcessRatedPowerKw 기반 공정별 idle 전력.`
- L323 — `# 공정이 작업 중이 아닐 때(근무·휴게·퇴근후 무관) 소모하는 전력 =`
- L324 — `# max(RatedPowerKw·IdlePowerRatio, IdleProcessRatedPowerKw). IdlePowerRatio`
- L325 — `# (=0.10) 는 AAS 미반영 정책 상수로 호출부가 주입.`
- L330 — `#← .RuntimeVariables.EpisodeEnergyKwh 의 idle 성분.`
- L331 — `# 모든 공정이 now 초 동안 idle 전력을 연속 소모한 에너지(배타 분해의`
- L332 — `# baseline). active 구간의 (rated−idle) 프리미엄은 EpisodeEnergyKwh 가`
- L333 — `# 별도 누적 → 합이 곧 배타 총 에너지.`
- L341 — `#← .RuntimeVariables.MaxEpisodeEnergyKwh`
- L342 — `# W2_Energy 정규화 분모 = 전 unit 완성 시 active 프리미엄 총량 (energy 항 [0,1] 상한).`
- L343 — `# 각 노드가 target_qty 회 가동될 때의 (RatedPowerKw − idle)·CycleTimeSec 합.`
- L344 — `# EpisodeEnergyKwh(분자) 도 같은 프리미엄만 누적하므로 비율 ∈ [0,1].`
- L345 — `# idle baseline 은 makespan 비용이라 W1_TimeElapsed 가 담당 — 에너지 항 분자·분모 모두 제외`
- L346 — `#   (이전엔 분자에 하루치 idle 포함 + 분모는 1사이클뿐이라 비율이 ~38 로 폭발, W5 를 152× 지배).`
- L347 — `# node.model_id 가 target_qty 키에 없으면(공용 'ALL' 노드) 전체 target 합으로 상한 근사.`
- L358 — `#← .RuntimeVariables.EpisodeEnergyKwh (active 프리미엄 누적분)`
- L359 — `# process_job 완료 시 active 구간의 idle 대비 초과분`
- L360 — `# CycleTimeSec·(RatedPowerKw − idle_kw)/3600 누적. baseline 이 모든`
- L361 — `# 시간을 idle 로 이미 계상하므로 여기선 차액만 더한다(배타). idle>rated`
- L362 — `# 인 저전력 공정은 음수 — baseline 의 과계상을 정확히 상쇄.`
- L367 — `#← .RuntimeVariables.CycleCompleted`
- L368 — `# 후행 엣지 없는(terminal) ProcessCode 가 완료되면 True →`
- L369 — `# Throughput 증가 + completed 리셋 트리거.`
- L374 — `#← .RuntimeVariables.Throughput`
- L375 — `# terminal 노드(CycleCompleted) 완료 시 그 노드의 model_id 카운트 +1.`
- L376 — `# Throughput: {model_id: int} (모델별). 모델별 target 도달 시 종료.`
- L382 — `#← .RuntimeVariables.StockShortageCount`
- L383 — `# present_stock < MinStock 인 재고 항목 수 (consume 시점 검사).`
- L392 — `#← .RuntimeVariables.StockOverflowCount`
- L393 — `# present_stock > MaxStock 인 재고 항목 수 (replenish 시점 검사).`
- L403 — `#← .RuntimeVariables.IdleViolationCount`
- L404 — `# 근무시간 중(호출부가 _is_work_time 으로 게이트) 워커가`
- L405 — `# IdleWorkerThreshold 초과 유휴인 슬롯 수 누적. idle_time dict 는`
- L406 — `# 워크스테이션별 유휴 시작 시각 추적 — 호출부 소유, 여기서 mutate.`
- L420 — `#← .RuntimeVariables.EpisodeReturns`
- L421 — `# 에피소드 reward 들의 Gamma 할인 누적. Critic target / advantage`
- L422 — `# baseline. G = reward + Gamma·G (역방향).`
- L430 — `#← .RuntimeVariables.Advantages`
- L431 — `# (EpisodeReturns − Critic value) 를 평균0/표준편차1 로 정규화.`
- L432 — `# path_extractor 는 torch 비의존 — 순수 파이썬. (모집단 표준편차)`
- L437 — `# endregion`
- L440 — `# region`
- L441 — `# ====================================================================`
- L442 — `# SubmodelElementList 계열`
- L443 — `# ====================================================================`
- L490 — `# endregion`
- L493 — `# region`
- L494 — `# ====================================================================`
- L495 — `# PO (Purchase Order) — 고객 주문. PO 관련 중 유일하게 AAS 에 올린 입력 데이터.`
- L496 — `# (현재고·발주잔량 등 내부 동적상태는 AAS 가 아니라 코드 런타임 변수 present_stock/on_order.)`
- L497 — `# ====================================================================`
- L514 — `# endregion`
- L517 — `# region`
- L518 — `# ====================================================================`
- L519 — `# Property / Range`
- L520 — `# ====================================================================`
- L559 — `# endregion`
- L562 — `# region`
- L563 — `# ====================================================================`
- L564 — `# Entity / RelationshipElement`
- L565 — `# ====================================================================`
- L568 — `# region [구조]`
- L569 `entityType: EntityType` — `# 필수 (default 없음)`
- L571 — `# endregion`
- L573 — `# region [로직]`
- L580 — `# endregion`
- L585 `first: List[semanticId] | SMEPath` — `# 필수`
- L586 `second: List[semanticId] | SMEPath` — `# 필수`
- L587 — `# endregion`
- L590 — `# region`
- L591 — `# ====================================================================`
- L592 — `# 내부 — 외부 식별자 (URL/IRDI) → SME 매칭`
- L593 — `# Submodel.id 또는 SME.semanticId 와 문자열 직접 비교.`
- L594 — `# ====================================================================`
- L637 — `# endregion`
- L640 — `# region`
- L641 — `# ====================================================================`
- L642 — `# ReferenceElement 계열 — 베이스 + 도메인 ref 들 (target 타입 명확화로 disambiguation)`
- L643 — `# ====================================================================`
- L646 — `# region [구조]`
- L647 `value: List[semanticId] | SMEPath` — `# 필수 — 가리키는 경로`
- L648 — `# endregion`
- L650 — `# region [로직: 파서]`
- L656 — `# endregion`
- L658 — `# region [로직: target 위임]`
- L662 — `# endregion`
- L664 — `# region [로직]`
- L676 `if first is None:` — `# 대상 AAS 미로드 등 → 조기 None`
- L680 — `# keys[1:] 가 모두 식별자 — path 안에서 찾을 수 있으면 path, 아니면 list`
- L689 — `# 첫 식별자 + idShort 들 (단일 path)`
- L694 — `# endregion`
- L802 — `# endregion`
- L805 — `# region`
- L806 — `# ====================================================================`
- L807 — `# 도메인 ref 용 타입 필터 lookup 헬퍼들`
- L808 — `# ====================================================================`
- L867 `return identifier` — `# IRDI 등은 그대로 (확장 시 처리)`
- L868 — `# endregion`
- L871 — `# region`
- L872 — `# ====================================================================`
- L873 — `# AAS 컨테이너 + 외부 노출 인스턴스`
- L874 — `# 시뮬 코드는 모듈 레벨 인스턴스 `ProvisionofSimulationModelsAAS` 만 다룸.`
- L875 — `# ====================================================================`
- L879 — `# region [구조]`
- L882 — `# endregion`
- L884 — `# region [로직]`
- L905 `'UnitsPerWorker': (ws.value['UnitsPerWorker'].value` — `#← WorkstationInformation.UnitsPerWorker`
- L906 `if 'UnitsPerWorker' in ws.value else 1),` — `# 부재 = 1 (병렬 확장 없음 — DepWaitSec None 과 동일 옵셔널 패턴)`
- L950 — `# endregion`
- L953 — `# AAS 인스턴스 (모듈 레벨). 외부 노출은 `ProvisionofSimulationModelsAAS` 뿐.`
- L956 `ProductAAS: List[AssetAdministrationShell] = []` — `# MODEL_N 들 (load 호출 시 채워짐)`
- L959 — `# 모든 로드된 AAS 인스턴스 보관 (내부). cross-AAS deref 시 lookup 용.`
- L995 — `# endregion`
- L998 — `# region`
- L999 — `# ====================================================================`
- L1000 — `# 내부 — JSON dict → SME 인스턴스 빌더 (재귀, 위치 기반 도메인 매칭)`
- L1001 — `# ====================================================================`
- L1007 — `# 공통 필드`
- L1066 — `# 모르는 modelType — base`
- L1116 — `# xs:time "HH:MM" / "HH:MM:SS" → 자정 기준 초 (시뮬에서 사용하는 표현).`
- L1123 — `# endregion`


## `knowledge_graph.py`

**모듈 설명**

```
ver1 공정 KG 도메인 (KETI 재구성 — ② 공정 그래프). GraphNode/GraphEdge/KnowledgeGraph.
공정 선후관계(DepPrev/DepType edges) + ready_queue. 조립 only vs +SMT 포함은 build 에서 결정.
AAS·simpy·torch 무관 순수 도메인 — AAS 객체는 주입받고 path_extractor 를 import 하지 않는다(코어 leaf).
```

**주석 (원본 라인 순)**

- L10 `if TYPE_CHECKING:` — `# Warehouse 는 타입 힌트 전용 (런타임 결합 없음 — duck-typed)`
- L16 `ProcessCode  : str` — `#← ManufacturingProcess.groups.{GroupIdShort}.processes.{ProcessCode}`
- L17 `GroupIdShort : str` — `#← ManufacturingProcess.groups.{GroupIdShort}`
- L18 `model_id     : str` — `#← ManufacturingProcess.id.split('/')[6]  # 'MODEL_A'. 공용 노드(OQC/RMA)는 'ALL'`
- L19 `CycleTimeSec : float` — `#← ProcessNode.CycleTimeSec.value`
- L20 `DefectRate   : float` — `#← ProcessNode.DefectRate.value`
- L21 `RatedPowerKw : float` — `#← ProcessNode.RatedPowerKw.value`
- L22 `InputBOM     : dict` — `#← ProcessNode.InputBOM`
- L23 `DepWaitSec   : float | None = None` — `#← ProcessNode.DepWaitSec.value (자식 SME 없으면 None).`
- L24 — `# cycle 후 후속 ready 까지 추가 대기 (워커 비점유). 본드 경화·AGING 등.`
- L25 `SamplingRate : float | None = None` — `#← ProcessNode.SamplingRate.value (자식 SME 없으면 None).`
- L26 — `# None = 항상 실행. 0.05 = 5% 만 실행, 95% 는 ready 됐을 때 즉시 done 마킹.`
- L27 `OutputBOM    : dict | None = None` — `#← ProcessNode.Materials.outputVariables (A안: 완료 시 창고 적재 {item_code: Quantity}).`
- L28 — `# None = 산출물 없음(일반 조립노드). SMT 등 자체생산 노드만 보유.`
- L29 — `# AAS 연동(SMTProcess→OutputBOM 추출)은 SMT 노드 파서 도입 시 — 현재는 메커니즘만.`
- L30 — `# DepPrev/DepType 는 노드에 캐싱하지 않는다. 의존 관계의 단일 표현은 edges`
- L31 — `# (이전 공정 → 다음 공정 + type). 이전 공정이 필요하면 _predecessors 로 검색.`
- L35 `ProcessCode  : str` — `#← ProcessNode.{ProcessCode}            (다음 공정)`
- L36 `DepType      : str` — `#← ProcessNode.DepType.value   ('SEQUENCE' | 'JOIN')`
- L37 — `# edges 의 dict 키가 이전 공정. 키(이전 공정) → [GraphEdge(다음 공정, type)]`
- L38 — `# VD7_40   → [GraphEdge(VD7_40_1, JOIN)]`
- L39 — `# VD7_20_1 → [GraphEdge(VD7_40_1, JOIN)]`
- L40 — `# VD7_10   → [GraphEdge(VD7_10_1, SEQUENCE)]`
- L44 `nodes        : dict` — `#{ProcessCode: GraphNode}`
- L45 `edges        : dict` — `#{DepPrev: [GraphEdge, ...]}`
- L46 `workers      : dict` — `#{WorkstationId: {'worker_count': int, 'ProcessCode': [...]}}`
- L47 — `#        'WWM_FwInputLine': {`
- L48 — `#        'worker_count': 2,`
- L49 — `#        'ProcessCode' : ['VD7_10', 'VD7_10_1', 'VD7_10_2', 'VD7_10_3',`
- L50 — `#                         'BT5_10', 'BT5_11', ...]`
- L51 `NodeFeatureAttrs : list | None = None` — `#← ModelArchitecture.Observation.ObservationNodeFeatures.attrs() — GNN 노드 피처 속성명(순서=벡터 순서). obs_node_features 가 노드별 getattr. None=RL 미사용(예 gantt).`
- L55 — `# ManufacturingProcesses: {model_id: ManufacturingProcess submodel}  ← 모델별 MP`
- L56 — `# shared_groups: {GroupIdShort: ProcessGroup SMC}  ← PSM 의 ProcessOQC/ProcessRMA. model_id='ALL' 노드 — 공용 설비.`
- L60 `DepWait  = ProcessNode.DepWaitSec` — `# DepWaitSec(Property) | None`
- L61 `SamplRate = ProcessNode.SamplingRate` — `# SamplingRate(Property) | None`
- L73 — `# DepPrev → reverse edge (DepPrev → self) 등록. 기존 모델별 노드 정의 방식.`
- L80 — `# DepNext → forward edge (self → DepNext) 등록. 공용 노드(OQC) 가 자신의`
- L81 — `# 후속을 선언해 모델별 MP 의 DepPrev 변경 없이 reverse-edge 형성. 옵셔널.`
- L90 — `# 모델별 MP 노드들`
- L95 — `# 공용 노드 (PSM ProcessOQC/ProcessRMA — model_id='ALL')`
- L114 — `# edges(이전 공정 → 다음 공정) 역방향 맵. edges 는 build 후 불변이라 1회 캐싱`
- L115 — `# (ready_queue 가 매 평가마다 호출 → 매번 전 엣지 스캔하던 비용 제거, Track F).`


## `warehouse.py`

**모듈 설명**

```
ver1 자원/재고 도메인 (KETI 재구성 — ③ 공장 자원). StockItem/Warehouse/_StockRouter.
MBOM·min/max stock·발주(replenish)·PCB 라우팅. AAS·simpy·torch 무관 순수 도메인 —
AAS 객체·simpy env 는 주입받고 path_extractor 를 import 하지 않는다(코어 leaf).
※ Warehouse.replenish 는 simpy env 를 인자로 받는 형태(도메인이 simpy 를 import 하지 않음).
```

**docstring (클래스·함수)**

- **`class _StockRouter`** (L84):

```
메인(CoManaged) + PCB(SelfManaged) 두 Warehouse 인스턴스를 묶어
    Warehouse 와 동일한 인터페이스(inventory / consume / replenish)로 노출.
    Warehouse·StockItem 구조는 무변경 — item_code 소속으로만 라우팅.
```


**주석 (원본 라인 순)**

- L15 `present_stock      : float` — `# 초기재고 = MinStock`
- L19 `on_order           : bool = False` — `# 발주 outstanding 여부 — True 면 재발주 금지`
- L23 `inventory   : Dict[str, Dict[str, StockItem]]` — `#{Category : {item_code  : StockItem}}`
- L40 — `# 차감 후 '발주점(MinStock·OrderRatio) 이하 & 아직 발주 안 나간' 품목을 발주.`
- L41 — `# 반환: 이번에 신규 발주된 StockItem 리스트(빈 리스트=발주 없음, falsy).`
- L51 `and not item.on_order):` — `# 이미 발주 나간 품목 재발주 금지`
- L57 — `# 노드 완료 시 산출물을 창고에 적재 (A안: SMT 등 자체생산 하위조립체). consume 의 역연산.`
- L65 — `# 발주된 품목만 lead time 후 발주량(MaxStock·OrderRatio) 입고 + 발주 해제.`
- L66 — `# ★ 입고 직후 발주점 재검사 (deadlock 방지): 누적 부족분이 1회 발주량보다 클 때,`
- L67 — `#   해당 부품의 모든 consumer 노드가 ready 차단되면 consume 못 일어남 → trigger 영구 차단.`
- L68 — `#   on_order=False 직후 발주점 이하면 즉시 추가 발주 1회. on_order 단일 락 유지하므로`
- L69 — `#   consume 시 폭증 트리거는 여전히 차단됨 (도착 시점 1회만 추가).`
- L70 — `# notify: 입고(BOM 해제) 직후 호출 — BOM 대기로 잠든 produce_unit 깨우기(Track F).`
- L71 — `#   재귀 발주에도 그대로 전달해 모든 입고가 깨우기를 트리거하도록(이벤트 누락 방지).`
- L95 `def inventory(self):` — `# _bom_satisfied 읽기용 (병합 뷰)`
- L104 `self.pcb.consume(pcb_bom)` — `# PCB 보충은 smt 코루틴 담당`
- L107 `def produce(self, OutputBOM: dict) -> None:` — `# 산출물 적재 (A안). PCB→pcb 창고, 그 외→메인 (consume 과 동일 라우팅)`
- L116 `def replenish(self, env, ReplenishLeadDay, items, notify=None):` — `# 메인만 (PCB 는 일정증가 별도)`


## `simulation.py`

**모듈 설명**

```
ver1 simpy 이산사건 시뮬레이션 + RL (KETI 재구성 — ④ 학습·구동).
CproSimEnv(simpy env·디스패처·smt·reward·state_vec) + 관측 producer + GraphModule/op_* + PPOAgent.
(train 루프는 train.py 로 이전 — simulation 은 엔진+정책 공통 코어. EPISODE_DURATION_SEC 은 여기 유지.)
도메인(knowledge_graph/warehouse)·smt 는 import, AAS·정책상수는 build.py 가 주입.
```

**docstring (클래스·함수)**

- **`def obs_node_features`** (L462): 노드별 NodeFeatureAttrs gather → (N, F). 구성=AAS ObservationNodeFeatures(CD 리스트).
- **`def obs_graph_topology`** (L473): 공정 precedence(DepPrev/DepType edges) → edge_index (2, E). 토폴로지(고정).
- **`def obs_state_vector`** (L483): 전역 상태 → (StateDim,). 구성=RuntimeVariables/Params, 정규화=코드.
- **`def import_callable`** (L626): 'torch_geometric.nn.GCNConv' → 클래스/함수 객체. AAS Op 가 가리키는 실제 라이브러리/primitive.
- **`def op_concat_state`** (L632): 노드 임베딩 x 에 state 벡터를 행 broadcast 해 concat. state=None(StateDim=0) 이면 x 그대로.
- **`class GraphModule`** (L642):

```
계산그래프 spec 으로 net 조립. spec=[{'id','Op','Args','In'}], In={forward param: source}.
    source = 다른 노드 id 또는 외부 입력 이름(예 obs.x/edge_index/ready_emb/pooled_emb/state).
    파라미터 보유 모듈만 등록·학습; 함수(relu/softmax/primitive)는 매 forward 호출(Args 는 호출 인자).
    Linear in_features 처럼 런타임 의존 차원은 wiring 으로 resolve — source_dims(외부 입력 차원)로 추론.
    코드는 아키텍처를 표현하지 않는다 (import + wire + 최소 dim 추론).
```


**주석 (원본 라인 순)**

- L15 — `# ============================================================`
- L16 — `# 1 epoch = 3일 (259200s). 학습 horizon 기본값.`
- L17 — `# 1일(86400)로는 BT5_42 24h 본드(DepWaitSec)가 에피소드 전체를 먹어 MODEL_B 완성 불가 +`
- L18 — `# A/C 가 capacity-bound → 스케줄링 학습 leverage 거의 0 (2026-06-01 60ep 실측: 전 지표 flat).`
- L19 — `# 3일이면 B 의 24h 본드가 들어가 B 생산 가능 + throughput 이 정책 민감 → 학습 leverage 확보.`
- L20 — `# qty 고정(100)에선 horizon 을 늘려도 보상항 비율 보존(throughput·energy·위반카운터 모두 시간 비례).`
- L21 — `# 평가는 전량완료 기준(CproSimEnv.run(max_sec=큰 cap) 으로 target 도달까지).`
- L23 — `# ============================================================`
- L25 — `#========시뮬레이션 환경========-`
- L45 `self.WarehouseManagedBOM  = WarehouseManagedBOM` — `# CoManaged (PCB 제외)`
- L46 `self.SelfManagedBOM       = SelfManagedBOM` — `# PCB 등 — 별도 창고. None 이면 PCB 분리 안 함`
- L50 `self.break_start_sec      = break_start_sec` — `# int(min.split(':')[0]) * 3600 + int(min.split(':')[1]) * 60`
- L51 `self.break_end_sec        = break_end_sec` — `# int(max.split(':')[0]) * 3600 + int(max.split(':')[1]) * 60`
- L53 `self.IdleProcessRatedPowerKw = IdleProcessRatedPowerKw` — `#← DefaultParameters.IdleProcessRatedPowerKw`
- L54 `self.IdlePowerRatio       = IdlePowerRatio` — `# AAS 미반영 정책상수(=0.10) — 호출부 주입`
- L55 `self.RuntimeVariables     = RuntimeVariables` — `#← path_extractor RuntimeVariables (AAS 명시 연산)`
- L56 `self.SMTLines             = SMTLines` — `# {line_id: [(idShort, CycleTimeSec, RatedPowerKw)...]} ← SMTProcess. None=구 stub`
- L57 `self.SmtArrayPcb          = SmtArrayPcb` — `# 1 어레이 = N PCB (§7-4 어레이=6 PCB) — 정책상수 주입`
- L58 `self.SmtBatchArrays       = SmtBatchArrays` — `# 1 배치 = N 어레이 (§7-3-A 매거진=40 어레이) — 정책상수 주입`
- L62 — `#========RuntimeVariables (← SimulationModel.RuntimeVariables)========`
- L63 — `# AAS 에 value=None 으로 정의만 있는 동적 상태. 연산은 self.RuntimeVariables`
- L64 — `# (path_extractor) 가 단일 구현. 여기선 에피소드 초기값만 둔다.`
- L65 `self.CycleCompleted       = False` — `#← .CycleCompleted`
- L66 `self.Throughput           = {model_id: 0 for model_id in self.target_qty}` — `#← .Throughput (모델별)`
- L67 `self.EpisodeEnergyKwh     = 0.0` — `#← .EpisodeEnergyKwh`
- L68 `self.SMTEnergyKwh         = 0.0` — `# SMT 라인 활성에너지 — 별도 누적(보상 비결합). total_energy_kwh 에만 합산`
- L69 `self.StockShortageCount   = 0` — `#← .StockShortageCount`
- L70 `self.StockOverflowCount   = 0` — `#← .StockOverflowCount`
- L71 `self.IdleViolationCount   = 0` — `#← .IdleViolationCount`
- L72 — `#----generic 헬퍼 (AAS 외 — 순수 코드용)----`
- L76 `self.last_active          = {ws: 0.0 for ws in self.workers}` — `# ws 가 fully idle 진입한 시각 (state_vec idle 항 산출용)`
- L81 `if self.SelfManagedBOM:` — `# PCB(SelfManaged) 별도 창고`
- L85 `if self.SMTLines:` — `# AAS SMTProcess 설비 라인 — 실제 SMT 생산(GoodPCB → pcb 창고)`
- L88 `line_codes = pcb_codes[line_index::n_lines]` — `# PCB 코드 라인 분배(2라인 = 두개씩 라운드로빈)`
- L90 `else:` — `# SMTLines 미주입 → 구 stub 일정증가(fallback)`
- L93 `self.worker_resources     = {` — `# 라인별 동시 작업 한도 = 워커수 × 1워커당 동시 처리수`
- L94 `WorkstationId: simpy.Resource(self.env,` — `# AGING 은 UnitsPerWorker=10 → 6×10=60 동시. 그 외 라인은 ×1.`
- L98 — `# [B2 중앙 디스패처] ws별 대기 job 큐 + 깨우기 이벤트. 워커 빌 때 디스패처가`
- L99 — `# 큐에서 다음 job 선택 — 후보 ≥2 면 agent.choose(cross-unit/model), 아니면 FIFO.`
- L102 — `# 재고 입고 broadcast 이벤트 — BOM 대기로 잠든 produce_unit 들을 한 번에 깨움(Track F).`
- L103 — `# replenish(notify=self._wake_stock) 가 입고 직후 트리거. 폴링(timeout 60s) 대체.`
- L105 — `# 위반 카운터(W3/W4/W6) 정규화 상수 — 1일 근무틱(30s 샘플) × 대상 수 = 매 틱 전부 위반 시 최대치.`
- L106 — `# 고정값이라 potential() telescoping 안전(시간가변 분모 X). 1일 학습 스케일 기준 → 항 ~[0,1].`
- L108 `nominal_work_ticks        = work_day_sec / 30.0` — `# _watch 샘플 주기 30s`
- L113 — `# W2_Energy 정규화 분모 = 전 unit 완성 시 active 프리미엄 (target_qty·KG 만 의존 → 에피소드 내 고정).`
- L118 `def _is_work_time(self) -> bool:` — `# ver0 원본 그대로 (무변경)`
- L124 — `# 다음 근무 재개까지 남은 초 — process_job / _dispatcher 비근무 점프 공통.`
- L133 — `# ver0 process_job 원본 본문 유지. 최소 수정만:`
- L134 — `#   (1) 파라미터 done_set 추가  (2) 근무시간 대기  (3) 워커 Resource 점유`
- L135 — `#   (4) self.completed → done_set, 전역 clear() 제거`
- L138 `while not self._is_work_time():` — `# (2) 비근무면 재개까지 정확 점프`
- L140 `with self.worker_resources[WorkstationId].request() as req:` — `# (3) 워커 capacity`
- L150 `if node.OutputBOM:` — `# A안: 완료 시 산출물 창고 적재`
- L152 `done_set.add(ProcessCode)` — `# (4) self.completed → done_set`
- L154 `if self.in_progress[WorkstationId] == 0:` — `# ws fully idle 진입 — duration 기준점`
- L157 — `# (4) terminal 시 self.completed.clear() 제거 — 유닛-local done_set 이라 불필요/유해`
- L160 — `# model_id 일치 OR 공용 노드(model_id='ALL', 예: OQC/RMA) 둘 다 포함.`
- L161 `return [pc for pc in self.KnowledgeGraph.ready_queue(` — `# ver0 ready_queue 원본`
- L163 `self.DependentJoin, done_set, self.warehouse)` — `# completed ← done_set`
- L170 — `# ============================================================`
- L171 — `# [B2 중앙 디스패처 재설계]  per-unit 단일선택 폐기 → 전 유닛이 ready job 을`
- L172 — `# ws별 큐에 제출(fan-out 병렬 유지). 워커 슬롯이 빌 때 디스패처가 그 ws 큐에서`
- L173 — `# 다음 job 선택: 후보 ≥2 면 agent.choose(=cross-unit/model 우선순위, PPO 결정점),`
- L174 — `# 후보 1개거나 agent=None 이면 FIFO(=기존 greedy/simpy 의미 보존).`
- L175 — `# choose()/learn() 는 불변 — candidate 출처만 'cross-unit pending' 로 바뀜.`
- L176 — `# ============================================================`
- L183 — `# 재고 입고 시 호출(replenish notify). 현재 _stock_wake 를 succeed → BOM 대기 unit 전부 깨움.`
- L184 — `# 즉시 새 이벤트로 교체해 다음 대기자가 fresh 이벤트를 받게 함(broadcast-recreate).`
- L185 — `# simpy 협조적 스케줄 → unit 의 'ready 확인 후 yield' 사이 끼어듦 없어 lost-wakeup 無.`
- L194 `if not self._pending[ws]:` — `# 큐 빌 때 잠듦(simpy 협조적 → lost-wakeup 無)`
- L198 `if not self._is_work_time():` — `# 근무시간 게이트(시작 시점만 — ver0 의미)`
- L201 `req = res.request()` — `# 워커 슬롯 대기(빌 때까지)`
- L204 `if not pend:` — `# 단일 디스패처라 보통 발생X — 안전망`
- L207 `distinct_pcs = list(dict.fromkeys(j['pc'] for j in pend))` — `# 순서보존 distinct (동일 공정 중복 unit job 압축)`
- L208 `if agent is not None and len(distinct_pcs) >= 2:` — `# ★contention 결정점★ (PPO) — 공정 타입 ≥2 경합 시만`
- L209 `chosen_pc = agent.choose(distinct_pcs, self)` — `#   choose 후보 = distinct 공정 (큐 깊이 무관, buf·연산 폭증 방지)`
- L210 `job = next(j for j in pend if j['pc'] == chosen_pc)` — `#   고른 공정의 첫 job (같은 공정 unit 은 교환가능)`
- L212 `job = pend[0]` — `# FIFO (greedy / 단일 공정 / 후보1개)`
- L220 `yield self.env.timeout(node.CycleTimeSec)` — `# 점유한 채 작업(시작 후 근무외 넘어가도 ver0 동일)`
- L228 `self.env, self.ReplenishLeadDay, ordered, self._wake_stock))` — `# 입고 시 BOM 대기 unit 깨움`
- L229 `if node.OutputBOM:` — `# A안: 완료 시 산출물 창고 적재 (SMT PCB 등). 일반 조립노드는 None → no-op`
- L231 `self.in_progress[ws] -= 1` — `# ★ 워커 즉시 자유 — DepWait 중 다른 job 가능`
- L232 `if self.in_progress[ws] == 0:` — `# ws fully idle 진입 — duration 기준점 갱신`
- L234 `self._wake_dispatcher(ws)` — `# 슬롯 비었음 → 디스패처 재가동`
- L236 `if node.DepWaitSec:` — `# ★ AAS DepWaitSec — 본드 경화·AGING 등 후처리 대기`
- L237 `yield self.env.timeout(node.DepWaitSec)` — `#   워커 비점유. 이 코루틴만 잠듦 — env.now 는 다른 이벤트로 진행.`
- L239 `job['done_set'].add(pc)` — `# DepWait 완료 후 done 인정 — 후속이 비로소 ready`
- L244 `job['ev'].succeed()` — `# produce_unit outstanding 깨움 → 새 ready job fan-out`
- L247 — `# 주문 1개 = 코루틴 1개. ready job 을 ws 큐에 제출(fan-out)하고 완료를 대기.`
- L248 — `# 선택(어느 job 먼저)은 디스패처가 cross-unit 으로 — 여기선 제출/대기만.`
- L261 — `# ★ SamplingRate 확률적 분기: ready 됐어도 random >= rate 면 즉시 done 마킹·skip.`
- L262 — `#   OQC 같은 확률 게이트 노드 — 5% 만 실제 워커 소비, 95% 는 bypass.`
- L278 `yield self._stock_wake` — `# BOM 부족으로 제출불가 → 재고 입고 시까지 대기(Track F: 폴링 제거)`
- L279 `continue` — `#   유일한 unblock 이벤트가 replenish 임을 분석으로 확인`
- L280 `yield simpy.AnyOf(self.env, outstanding)` — `# 하나라도 끝나면 재평가`
- L284 — `# AAS SMTProcess 설비 라인 1줄(env.process 로 등록). 배정 PCB 코드를 라운드로빈으로 배치 생산.`
- L285 — `# equipment: [(idShort, CycleTimeSec, RatedPowerKw), ...] 라인 설비 순서(SMTEquipmentProcess → factory 주입).`
- L286 — `# 1 array = SmtArrayPcb(6) PCB, 라인 통과시간 = Σ설비 cycle (직렬 — §7-4 "어레이 1장 처리시간 ≈620s").`
- L287 — `# 1 batch = SmtBatchArrays(40) array(=240 PCB 매거진). PCB 전환 = 현 배치 전량 완료 후(라인 클리어).`
- L288 — `# ★ open-loop 라운드로빈 — 수요 무관이라 특정 코드 starvation 가능(측정·보고 대상). 수요기반은 후속.`
- L291 `array_cycle  = sum(cycle for _, cycle, _ in equipment)` — `# 어레이 1장 라인 통과시간(s)`
- L292 `array_energy = sum(power * cycle for _, cycle, power in equipment) / 3600` — `# 어레이 1장 SMT 활성에너지(kWh)`
- L294 `for code in pcb_codes:` — `# 라운드로빈 PCB 전환(라인 클리어 후)`
- L295 `for _ in range(self.SmtBatchArrays):` — `# 1 배치`
- L296 `while not self._is_work_time():` — `# 비근무면 재개까지 점프(조립과 동일 게이트)`
- L300 `self.warehouse.produce({code: self.SmtArrayPcb})` — `# GoodPCB 어레이(6) → pcb 창고`
- L301 `self._wake_stock()` — `# PCB 입고 → BOM 대기 produce_unit 깨움`
- L304 — `# 주문수량만큼 produce_unit 을 동시에 띄우고 한 번 진행. agent=None → greedy.`
- L307 `for ws in self.workers:` — `# [B2] ws별 중앙 디스패처`
- L316 `if self._is_work_time():` — `# 근무시간 틱마다 위반 카운터 누적 (W3/W4/W6)`
- L334 `'EpisodeEnergyKwh': float(self.total_energy_kwh()),` — `# idle+프리미엄 총량(버그수정: idle 포함)`
- L335 `'ActivePremiumKwh': float(self.EpisodeEnergyKwh),` — `# 참고: active 초과분만(기존 값)`
- L339 — `# 진짜 총 에너지 = idle baseline(now 의존, 전 공정이 now 내내 idle) + active 프리미엄.`
- L340 — `# 기존 버그: 보상/로그가 프리미엄(상수)만 써서 makespan 무관 → idle 누락.`
- L344 `return idle_base + self.EpisodeEnergyKwh + self.SMTEnergyKwh` — `# SMT 라인 활성에너지 합산(보상엔 비결합)`
- L348 — `# PPOAgent 인스턴스화 시점에 미리 알아야 — env.reset() 호출 불필요(설정만으로 산출).`
- L349 — `# 구성: [throughput per model] + [time] + [energy]`
- L350 — `#     + [worker_util per ws] + [stock_short, stock_over] + [idle_avg]`
- L354 — `# 결정점마다 호출. 활성 보상항(W1/W2/W5) + 미활성 채널(W3/W4/W6) 까지 전부 동적 관측.`
- L355 — `# 보상에 없어도 critic V(s) 추정에 도움 — 관측은 풀로, 보상은 별도 결정.`
- L356 — `# 모든 값 0~1 근방으로 정규화 — GNN 임베딩과 concat 시 한 항이 압살하지 않도록.`
- L360 `for model_id in self.target_qty:` — `# ① 모델별 throughput 진척 (W5 대응)`
- L362 `feats.append(self.env.now / max(work_day * total_target, 1.0))` — `# ② 시간 진척 (W1 대응)`
- L363 `feats.append(self.EpisodeEnergyKwh / self._max_episode_premium)` — `# ③ 에너지 진척 (W2 대응) — active 프리미엄 / 전량 [0,1] (potential 과 동일 분모)`
- L364 `for ws, info in self.workers.items():` — `# ④ ws별 워커 점유율`
- L366 — `# ⑤ 재고 항 (W3/W4 대응) — 전 품목 정규화 합 (MinStock 부족 / MaxStock 과잉)`
- L377 — `# ⑥ 유휴 항 (W6 대응) — fully idle ws 의 평균 지속시간 / IdleWorkerThreshold`
- L378 — `# last_active[ws] = ws 가 fully idle 로 진입한 시각 (_run_job/process_job 에서 갱신)`
- L387 — `# 현재 상태의 목적함수 값 Φ(s). 임의 시점(결정점/종료)에서 호출 가능.`
- L388 — `# per-step 보상 r_t = Φ(s_{t+1})−Φ(s_t) 의 telescoping → 종료 시 episode_reward 와 일치.`
- L389 — `# W3/W4/W6(재고과잉·재고부족·유휴)은 _watch 30s 틱이 누적한 단조 카운터로 반영 —`
- L390 — `# 순간값이 아닌 누적이라야 중간 위반이 telescoping 에서 상쇄되지 않음. 고정 분모로 ~[0,1].`
- L391 — `# ★스케일 균형은 1일 학습 qty≈100(모델당) 기준 — 6항 모두 throughput 의 1.0~1.7× (검증).`
- L392 — `#   W5/W2 는 total_target·전량프리미엄(∝qty)으로 정규화돼 ∝1/qty 줄지만 W4/W6 은 qty 무관`
- L393 — `#   → qty 를 크게(≥500) 키우면 재고·유휴가 지배 + throughput 자체도 0 붕괴. qty~100 유지할 것.`
- L397 `return (` — `# W2 분모 _max_episode_premium = reset 캐싱(전량 프리미엄)`
- L400 `- (self.EpisodeEnergyKwh / self._max_episode_premium)    * w['W2_Energy']` — `# active 프리미엄만 / 전량 프리미엄 ∈ [0,1] (idle 제외)`
- L407 — `# 종료 시 스칼라 보상 = Φ(terminal). learn() 의 마지막 결정 보상 기준값.`
- L411 — `# 에피소드 = produce_unit 구조 1회(env.run(agent, max_sec=episode_max_sec)). 결정점마다 agent.choose 가`
- L412 — `# rollout 기록 → 종료 후 episode_reward 로 1회 PPO learn. (직렬 step/skip 없음)`
- L413 — `# 매 ep rl_logger_spec 항목 JSONL 기록 + best R 갱신 시에만 agent_mod.pt 저장.`
- L414 — `# episode_max_sec: 1 epoch 길이 (기본 86400s = 1일). target_qty 도달 또는 이 시간 도달 시 종료.`
- L415 — `# 출력 → mod_run/result/runs/<run_name>/  (None 이면 timestamp 자동 생성)`
- L417 `_ROOT    = os.path.dirname(os.path.abspath(__file__))` — `# 패키지 루트 (이 파일 위치)`
- L418 `_MOD_RUN = os.path.join(_ROOT, 'mod_run')` — `# 결과·rl_logger 거주지`
- L432 `if os.path.exists(os.path.join(_OUT, 'STOP')):` — `# 협조적 중단(외부 신호)`
- L436 `summary = env.run(agent=agent, max_sec=episode_max_sec)` — `# 1 epoch = episode_max_sec (기본 1일)`
- L439 `metrics = agent.learn(R, env.KnowledgeGraph)` — `# 진단 dict (B/C/D)`
- L445 `violations={'stock_shortage': env.StockShortageCount,` — `# W4/W3/W6 추세 추적`
- L449 `torch.save(agent.state_dict(), ckpt)` — `# best 갱신 시에만, 덮어쓰기`
- L457 — `#========관측 카탈로그 (observe — 닫힌 producer 집합, KnowledgeGraph/env 위에서만)========`
- L458 — `# (a) 환경 관측 producer. AAS 인코더 Inputs 가 CD ref(cd/NodeFeatures·cd/GraphTopology)로 가리키고`
- L459 — `# 해석기가 카탈로그 id 로 resolve, 알고리즘(choose)이 호출해 텐서 공급. (b) ready/pooled 임베딩은`
- L460 — `# 알고리즘 내부값이라 여기 없음(choose 가 actor/critic 에 직접 공급). raw AAS 안 봄 — 도메인 클래스 위.`
- L486 `OBSERVATION_CATALOG = {` — `# 닫힌 어휘 — AAS 외부 ref 가 가리킬 수 있는 관측 소스`
- L493 — `#======== RL 신경망·해석기 (<- cpro_nn 통합): import_callable / GraphModule / op_* / PPOAgent ========`
- L499 — `# 아키텍처(encoder/actor/critic)는 해석기(cf.build_agent)가 GraphModule 로 빌드해 주입.`
- L500 — `# AAS ModelArchitecture.Network 가 조립을 기술하고 코드 팔레트가 빌더를 보유 — 여기선 받기만.`
- L501 — `# submodule 속성명(GNNEncoder/Actor/Critic)은 state_dict 호환 위해 고정.`
- L514 `self.RuntimeVariables = RuntimeVariables` — `#← path_extractor RuntimeVariables (AAS 명시 연산)`
- L518 `self.buf = []` — `# 결정점마다 {ready, idx, logp, value}`
- L520 `@torch.no_grad()` — `# rollout 은 무-grad (표준 PPO). grad 는 learn() 이 forward 재실행하며 계산.`
- L522 — `# produce_unit 의 결정점 콜백. 학습(training)→샘플, 평가(eval)→argmax(결정론).`
- L523 — `# ready_pcs 는 distinct 공정 코드 리스트(디스패처가 중복 압축해 전달) — 큐 깊이가 아니라`
- L524 — `# 공정 타입 위 분포를 학습. 저장값은 전부 스칼라/snapshot 텐서라 grad 불요. buf 는 학습·평가 양쪽 다.`
- L529 `state            = env.state_vec() if self.StateDim > 0 else None` — `# 결정점 동적 관측`
- L534 `'logp': dist.log_prob(idx),` — `# no_grad 컨텍스트 — grad_fn 없음`
- L536 `'state': state,` — `# 결정점 상태 snapshot`
- L537 `'phi': float(env.potential())})` — `# 결정점 Φ(s_t) — per-step 보상용`
- L541 — `# 에피소드 종료 후 1회 PPO-clip 업데이트. terminal 스칼라 보상을 전 결정이`
- L542 — `# 공유 (critic baseline 으로 advantage). 보상 시점/형태는 튜닝 대상.`
- L543 — `# 반환: rl_logger_spec 진단 dict (마지막 epoch 기준). buf 비면 None.`
- L547 `values   = torch.stack([b['value'] for b in self.buf])` — `# 결정점 V(s_t) (detach)`
- L551 — `# per-step 보상 r_t = Φ(s_{t+1})−Φ(s_t). 마지막은 Φ(terminal)=episode_return.`
- L552 — `# telescoping → Σr ≈ R − Φ(s_0) (potential-based shaping; 최적정책 불변).`
- L557 — `# GAE (γ=self.Gamma, λ=self.GaeLambda — 기존 선언됐으나 미사용이던 것 복원). 터미널 V=0.`
- L565 `returns = advantages + values` — `# critic 타깃 (분산>0)`
- L571 `node_features  = obs_node_features(KnowledgeGraph)` — `# 에폭당 1회 (그래프 고정)`
- L576 `state      = b['state']` — `# 결정점 시점 snapshot 재사용`
- L596 — `# ---- rl_logger_spec 진단 (마지막 epoch tensor 기준) ----`
- L599 `ret_var    = float(returns.var())` — `# 스칼라 보상이면 0 (무신호 진단 핵심)`
- L603 — `# 스칼라 보상 → ret_var≈0 이면 ev 정의 불가(=학습 무신호 진단)`
- L618 — `#========RL 계산그래프 해석기 (코드 = import + wire, 아키텍처 = AAS)========`
- L619 — `# AAS ModelArchitecture 의 계산그래프(op 노드: Op=import 경로 / Args=생성자 인자 / In=named 입력)를`
- L620 — `# 제네릭하게 조립한다. 코드는 아키텍처를 '표현'하지 않는다 — importlib 로 실제 클래스/함수를 가져와`
- L621 — `# named 텐서로 wiring 할 뿐. (공정 노드 생성과 동일: 구조는 AAS, 코드는 해석.)`
- L622 — `# 새 모델/레이어 = AAS 에 Op 경로만 — 코드 무수정(import 가능한 무엇이든).`
- L630 — `# 태스크 primitive (라이브러리 레이어가 아닌 RL 태스크 op — AAS Op 가 경로로 참조). 최소 코드.`
- L651 `dim = dict(source_dims or {})` — `# node id/입력 → 출력 feature dim`
- L658 `params = inspect.signature(callable_).parameters` — `# 생성자 시그니처로 일반 resolve (특정 레이어 하드코딩 X)`
- L660 `arguments['in_features'] = in_dim['input']` — `# Linear 류 (forward 'input')`
- L662 `arguments['in_channels'] = in_dim['x']` — `# graph conv 류 (forward 'x') — GCN/SAGE/GAT/... 임의 교체`
- L666 `out_dim = (in_dim.get('x') or 0) + (in_dim.get('state') or 0)` — `# 입력 노드 차원 합 (state=StateVector source)`
- L667 `else:` — `# relu/softmax/squeeze 등 passthrough`
- L677 `out = self.mods[node['id']](**bound)` — `# 모듈: Arguments 는 생성 때 소비`
- L679 `out = import_callable(node['Operation'])(**bound, **node.get('Arguments', {}))` — `# 함수: Arguments 를 호출 인자로`


## `carbon.py`

**모듈 설명**

```
ECO 탄소배출 어댑터 (KETI 재구성 — ④ 탄소 seam). [Task 3 결선 예정 — 현재 미wiring]

활동(에너지·공정·자재)을 탄소배출량(kgCO2e)으로 변환하는 **단일 지점**.
ECO(에코앤파트너스)가 MCF(Manufacturing Carbon Footprint)→PCF 수식/계수를 전달하면
**이 파일만** 교체/확장한다 — simulation/run/path_extractor 는 무수정.

관심사 분리:
- 에너지 회계(kWh)는 path_extractor.RuntimeVariables.EpisodeEnergyKwh(AAS-grounded)가 보유.
- 본 모듈은 그 kWh(및 미래 자재 BOM / AAS MCF submodel)를 받아 탄소로 변환만 한다.

ECO 전달 예정(2026-05/06): 배출계수 kWh→kgCO2e, Scope 1/2/3, LCA 자재계수.
연결(Task 3): build.build_simulation 이 CarbonModel 을 env 에 주입 → simulation.potential() 의
W2 항이 carbon.from_energy(EpisodeEnergyKwh) / carbon.from_energy(max_premium) 로 정규화.
기본 emission_factor=1.0 이면 비율 불변 → 현재 동작 정확 보존(에너지 proxy).
```

**docstring (클래스·함수)**

- **`class CarbonModel`** (L23):

```
탄소 변환 어댑터 인터페이스. ECO 전달 형태를 전부 수용하는 메서드 집합.
    구현체를 갈아끼우는 단일 seam — engine/reward/run 은 본 인터페이스만 호출한다.
```

- **`class Scope2Carbon`** (L41):

```
기본 구현: 전력량 × 배출계수 (Scope 2). emission_factor=1.0 이면 에너지 proxy 와 동일(동작 보존).
    실 계수(예: 한국 전력 배출계수 kgCO2e/kWh)는 build.py 주입 또는 ECO 가 AAS 로 제공 시 path_extractor 추출.
```

- **`def from_energy`** (L27): Scope 2 전력 간접배출 = energy_kwh → kgCO2e. (즉시 필요분)
- **`def from_process`** (L31): 공정별 배출(ECO 가 공정별 계수 제공 시). 기본은 0 — 서브클래스 override.
- **`def from_materials`** (L35): Scope 3 / LCA 자재배출 (AAS MCF submodel MountedComponents 연계 — 미래). 기본 0.

**주석 (원본 라인 순)**

- L43 `emission_factor: float = 1.0` — `#← (미래) AAS DefaultParameters.EmissionFactor / ECO 전달`


## `export.py`

**모듈 설명**

```
외부 전달 (KETI 재구성 — ⑤). [stage-5 scaffold — 실 API 계약 미정]

학습된 agent 의 결정형 eval run 결과(최적해)를 외부로 전달 가능한 페이로드로 정리.
포함 예정: 모델별 생산량 / makespan / 에너지 / 탄소(kgCO2e) / 납기준수·tardiness /
공정 스케줄(타임라인) / 워커·셀 구성.

현재는 seam 만 — 페이로드 빌더 + send() stub. 전송 프로토콜(REST/MQTT 등)은 외부 계약 확정 후.
```

**docstring (클래스·함수)**

- **`def build_payload`** (L16): eval run 의 env + summary(run() 반환 dict) → 외부 전달 페이로드. [Task 5 구체화]
- **`def send`** (L28): 외부 API 전송 stub. 실 계약(엔드포인트/포맷) 확정 시 구현.

**주석 (원본 라인 순)**

- L21 — `# 'carbon_kgco2e': ...,   # Task 3 CarbonModel 결선 후`
- L22 — `# 'due_adherence': ...,   # Task 2 납기 결선 후`
- L23 — `# 'schedule'     : ...,   # 공정 타임라인 (plan_cell._schedule_log 등)`


## `build.py` · `train.py` · `run_trained.py` (구 `run.py` 3분할)

> 구 `run.py` 는 ① 공용 배선(build_simulation/build_agent) ② 학습 __main__ 이 섞여 있었다.
> 이를 셋으로 분리: **`build.py`** = 공용 배선(학습·추론·viz 공용), **`train.py`** = 학습 진입점
> (train 루프 + __main__, simulation.train 이전), **`run_trained.py`** = 추론 진입점(학습된 .pt
> 재사용해 PO/수치만 바꿔 KPI+워커스케줄 출력, frozen-safe + CLI). 아래 build_simulation/
> build_agent docstring 은 `build.py` 로 그대로 이전됨. 인계 패키지 레시피는 `deploy/`.

**모듈 설명 (build.py)**

```
CPRO 공용 배선 (build) — AAS → (CproSimEnv, PPOAgent) wiring. train·infer·viz 가 공용 호출.

기존에 `simulation_ver1.__main__` / `_capture_oqc` / `_timeit` / `cpro_ver1_viz` /
`cpro_worker_util` 에 verbatim 복제돼 있던 ~30개 kwarg wiring 블록을 한 곳으로 통합한다.
도구·외피(shell)는 `build_simulation()` / `build_agent()` 만 호출하고 같은 wiring 을 다시 쓰지 않는다.
TRAINING_AAS_FILES(5파일) = 학습·추론 공용 로드셋(SMT 카탈로그 제외). DEFAULT_AAS_FILES(6) 는 viz/하위호환.
build_simulation 은 due_day= 오버라이드(모델별 납기일, ×86400, 머지) 지원.

규칙(CLAUDE.md):
- AAS 접근은 path_extractor 단일 진입점만 사용 — JSON 직접 파싱 없음.
- AAS 미반영 정책상수(`IdlePowerRatio`)는 env 빌더가 주입 — 여기가 단일 주입점.
- torch 는 `build_agent` 에서만 import (`build_simulation` 은 simpy 코어만).
- 입력 AAS 는 호출 전에 로드돼 있어야 한다. 각 도구는 기존 module-top `path_extractor.load` 를
  그대로 유지(`build_simulation(aas_dir=None)` 은 싱글톤을 읽기만). 재로드는 ProductAAS 중복
  append + viz 모듈 캐시 stale 을 부르므로 도구 load 를 여기로 옮기지 않는다.
  `aas_dir` 인자는 외피 단발 호출(빈 싱글톤일 때 1회 로드)용.
```

**docstring (클래스·함수)**

- **`def load_aas`** (L34):

```
aas_dir 의 입력 AAS 들을 path_extractor 싱글톤에 로드. 외피(shell) 단발 호출용.
    (도구는 기존 module-top load 를 유지 — 여기로 옮기지 않음.)
```

- **`def build_simulation`** (L49):

```
로드된 AAS 싱글톤 → CproSimEnv 인스턴스 (→ 반환).
    env_cls 로 기록용 서브클래스(RecEnv/RecMod/UtilEnv 등) 주입 가능 (없으면 CproSimEnv).
    aas_dir 지정 + 싱글톤 비어있을 때만 직접 로드 (외피 단발 호출). 도구는 aas_dir 생략.
```

- **`def build_agent`** (L126):

```
로드된 AAS 싱글톤 + env.state_dim → PPOAgent (→ 반환).
    checkpoint 주면 load_state_dict + eval (결정형 평가용). StateDim 미지정 시 env.state_dim
    (env 없으면 0 — StateDim=0 으로 학습된 구 체크포인트 호환).
```


**주석 (원본 라인 순)**

- L24 — `# CPRO 입력 AAS. 다른 공장(헵시바 등)은 files= 로 교체 — 다중기업 일반화 seam(phase-2).`
- L25 — `# SMTEquipmentCatalog: SMT 설비 cycle/power 임시 카탈로그(SMTProcess ref 가 deref) — 실 설비 AAS 도착 시 교체.`
- L29 `DEFAULT_SHARED_GROUPS = ('ProcessOQC',)` — `# 공용 노드(model_id='ALL'). ProcessRMA 자식 SME 미완 — 후속(E).`
- L30 `IDLE_POWER_RATIO      = 0.10` — `#← AAS 미반영 정책상수 (CLAUDE.md: 호출부 주입)`
- L60 `SimulationModel   = PSM.SimulationModels.SimulationModel` — `#← SimulationModels.SimulationModel`
- L61 `Action            = SimulationModel.KnowledgeGraph.Action` — `#← KnowledgeGraph.Action`
- L62 `DefaultParameters = SimulationModel.DefaultParameters` — `#← DefaultParameters`
- L63 `RewardWeights     = SimulationModel.RewardWeights` — `#← RewardWeights`
- L65 `target_qty = SimulationModel.PurchaseOrder.target_qty()` — `#← PurchaseOrder.target_qty() (인자 미지정 시 PO 주문에서)`
- L67 `ManufacturingProcesses = {mp.model_id: mp for mp in SimulationModel.Warehouse.InputBOM.target}` — `#← Warehouse.InputBOM`
- L71 `NodeFeatureAttrs = SimulationModel.ModelArchitecture.Observation.ObservationNodeFeatures.attrs()` — `#← GNN 노드 피처 구성(CD ref → 속성명)`
- L76 `MaxEpisodes = int(SimulationModel.SimulationConfig.MaxEpisodes.value)` — `#← SimulationConfig.MaxEpisodes`
- L78 — `# SMT 라인 설비(cycle/power) 추출 — SMTProcess.SMTLines.<Line_N>.<설비>Process (SMTEquipmentProcess).`
- L79 — `# 설비 카탈로그(SMTEquipmentCatalog.json) 가 로드된 경우만 cycle/power resolve → SMT 활성.`
- L80 — `# 미로드(도구의 자체 5-파일 load 등)면 None → CproSimEnv 가 구 smt.pcb_supply stub 으로 fallback.`
- L81 `SMTLines = None` — `#← SMTProcess.SMTLines`
- L85 `probe = next(iter(next(iter(lines.values())).value.values()))` — `# 첫 라인 첫 설비`
- L86 `if probe.CycleTimeSec is not None:` — `# 카탈로그 로드 확인`
- L97 `workers                 = PSM.workers,` — `#← WWM`
- L107 `ReplenishLeadDay        = int(DefaultParameters.ReplenishLeadDay.value) * 86400,` — `# ReplenishLeadDay 단위 = days (×86400 = 초)`
- L110 `WarehouseManagedBOM     = PSM.CoManagedBOM,` — `#← ProductAAS HS (CoManaged)`
- L111 `BOMCategory             = SimulationModel.Warehouse.MinStock.target,` — `#← Warehouse.MinStock`
- L117 `RuntimeVariables        = SimulationModel.RuntimeVariables,` — `#← RuntimeVariables (AAS 명시 연산)`
- L119 `IdlePowerRatio          = IdlePowerRatio,` — `#← 정책상수 주입`
- L120 `SelfManagedBOM          = PSM.SelfManagedBOM,` — `#← PCB(SelfManaged) 별도창고`
- L121 `SMTLines                = SMTLines,` — `#← SMTProcess.SMTLines (설비 cycle/power)`
- L134 `Algorithm         = ModelArchitecture.Algorithm` — `#← 알고리즘 selector (Operation + Arguments + 네트워크 Actor/Critic)`
- L135 `Arguments         = Algorithm.Arguments` — `#← 하이퍼파라미터 (형 TrainingConfig)`
- L140 — `# 전 네트워크(encoder/actor/critic) = AAS 계산그래프(op 노드) → 제네릭 해석기(GraphModule). 코드는 import+wire.`
- L141 — `# 각 노드: Op=실제 import 경로/태스크 primitive, Args=생성자 인자, In={forward param: source}.`
- L143 — `# ReferenceElement(외부 관측 카탈로그 CD ref) → 카탈로그 id(CD tail). Property → 내부 노드 출력(문자열).`
- L157 `NodeFeatureDim = len(ModelArchitecture.Observation.ObservationNodeFeatures)` — `#← 노드 피처 개수 = GNN 입력차원`
- L161 `if 'out_channels' in node.get('Arguments', {}))` — `# 인코더 출력차원 = 마지막 conv out`
- L162 — `# actor/critic 도 계산그래프. source_dims 로 Linear in_features(=embedding+state) 를 wiring resolve.`
- L166 — `# 알고리즘 = Operation 으로 선택 (PPO 고정 아님). networks(encoder/actor/critic) + Arguments(하이퍼) + env-주입(StateDim/RuntimeVariables).`
- L167 `algo_cls = sv.import_callable(Algorithm.Operation.value)` — `#← "simulation.PPOAgent"`
- `train.py.__main__` — `# 학습 진입점. build.TRAINING_AAS_FILES(5파일) 로드 → build.build_simulation/build_agent → train 실행.` (구 run.py.__main__ + simulation.train 흡수.)
- `run_trained.py` — `# 추론 진입점. TrainedModel(.pt+AAS 1회 로드).run(po, overrides) → {kpi, schedule}. CLI: --in/--out.`
- L193 `_ROOT = os.path.dirname(os.path.abspath(__file__))` — `# 패키지 루트 — AAS JSON`
- L201 `for mp in SimulationModel.Warehouse.InputBOM.target}` — `#← Warehouse.InputBOM`


## `smt.py`

**모듈 설명**

```
SMT 라인 전용 모듈 (PCB SelfManaged 보충 + SMT 공정 구현).

PCB 는 SelfManaged 하위조립체로 자체 SMT 공정에서 생산된다. 본 모듈은
SMT 라인 [Loader → ScreenPrinter → SPI → Mounter(×2 기종) → Reflow →
AOI → Unloader] 를 모델링해, PCB 별도 Warehouse 를 채운다.

현재는 stub 코루틴(`pcb_supply`) — 라인당 평균 생산량을 매 interval 마다
종류별로 균등 증가시킨다. 이 stub 자리에 실제 설비 단위 SMT 공정이 들어갈
예정 (Loader/Printer/SPI/Mounter/Reflow/AOI/Unloader IDEF0 → simpy 코루틴).

(path_extractor 가 SelfManaged 를 SelfManagedBOM 으로 분리 제공.)
```

**docstring (클래스·함수)**

- **`def pcb_supply`** (L27):

```
PCB 창고 전용 일정증가 코루틴. env.process() 로 등록.

    pcb_warehouse : SelfManagedBOM 으로 build 된 Warehouse 인스턴스
                    (구조는 일반 Warehouse 와 동일, PCB 만 담김)
```


**주석 (원본 라인 순)**

- L16 — `# TODO: 실제 SMT 라인 평균 PCB 생산량 출처(AAS/공정데이터) 확정 시 교체.`
- L17 — `#       현재는 stub 상수. 단위 = PCB개 / 라인 / SUPPLY_INTERVAL_SEC.`
- L20 `SUPPLY_INTERVAL_SEC = 3600.0` — `# 1 시뮬-시간마다 보충`
- L36 `increment = avg_pcb_per_line * n_lines / n_types` — `# 종류별 매 interval 증가량`


## `plan_cell.py`

**모듈 설명**

```
PoC: 셀(worker 묶음) 재구성 RL 메커니즘.

설계문서(PoC_생산계획DF_셀재구성RL.md) §5~6 의 "행동 고도 = 셀 구성 선택" 절반을
실제 WWM·코드에 맞춰 구현한 PoC. ④ DF 계획레이어는 최소화(target_qty 유지, 계획신호는
env 상태에서 직접 산출) — 핵심 가설 "셀 구성 RL 이 보상을 움직이는가" 검증에 집중한다.

검토 시 발견한 설계문서 결함을 교정해 구현(자세한 근거는 작업 대화 참고):
- 실제 WWM = 10라인/58명. 설계 5셀이 RMALine(6명) 누락 → 6셀로 재정의(전 라인 커버, 합 58).
- 셀=라인 여러 개인데 라인마다 UnitsPerWorker 가 다름(Aging upw=10, 나머지 1) →
  템플릿은 '셀 합계 인원'을 주고, 셀 내부는 라인 baseline 비례 분배 + 라인별 upw 적용.
- simpy.Resource 는 capacity 런타임 변경 불가 + 디스패처가 Resource 를 루프 진입 시 1회
  캡처 → 교체해도 무효. 본 PoC 는 Resource 대신 정수 캡(_line_cap)으로 동시성 제어
  (디스패처가 매 루프 self._line_cap[ws] 재조회 → 재구성이 즉시 반영).

기반 CproSimEnv 는 무변경 — 본 클래스는 env_cls seam(cf.build_simulation(env_cls=...))으로
주입되는 서브클래스. 디스패처는 FIFO(dispatch_agent=None) 로 두고 셀 결정만 RL 레버로 둔다
(인과 귀속 명확화). cell_agent / 베이스라인 selector 는 공통 인터페이스 choose_cell(env)->int.
```

**주석 (원본 라인 순)**

- L31 — `#========셀 정의 + 템플릿 (전 라인 커버, 합 58)========`
- L32 — `# CELLS: 셀 → 담당 WWM 라인(idShort) 목록. 6셀이 실제 10라인 전부 커버.`
- L33 — `# ※ 라인명 하드코딩은 PoC 의 셀 설계(라벨 의존). 정도(正道)는 WWM 에 Cell qualifier 추가 후`
- L34 — `#   path_extractor 추출 → 여기서 읽기 (CLAUDE.md "라벨 매칭 분기 금지"). 후속 과제.`
- L36 `'CELL_MOD':  ['WWM_FwInputLine', 'WWM_LensHolderLine', 'WWM_FocusLine'],` — `# 모듈/광학 전공정 (base 2+4+3=9)`
- L37 `'CELL_SEMI': ['WWM_SemiAssemblyLine'],` — `# 서브조립 (base 11)`
- L38 `'CELL_SET':  ['WWM_SetAssemblyLine'],` — `# 본체조립 (base 12)`
- L39 `'CELL_INSP': ['WWM_InspectionLine', 'WWM_AgingLine'],` — `# 검사+AGING (base 4+6=10, Aging upw=10)`
- L40 `'CELL_QA':   ['WWM_OqcLine', 'WWM_RMALine'],` — `# OQC+RMA (base 4+6=10)`
- L41 `'CELL_PACK': ['WWM_PackagingLine'],` — `# 포장 (base 6)`
- L44 — `# CELL_TEMPLATES[action] = {cell_id: 셀 합계 인원}. action ∈ {0..K-1} = RL 행동(Stage 1 categorical).`
- L45 — `# 합 58(LOW_UTIL 만 38 — 20명 미배치=의도적 저자원). 셀 내부 분배는 _distribute 가 라인별로.`
- L47 `{'CELL_MOD':  9, 'CELL_SEMI': 11, 'CELL_SET': 12, 'CELL_INSP': 10, 'CELL_QA': 10, 'CELL_PACK':  6},` — `# 0 BALANCED(=실제 WWM)`
- L48 `{'CELL_MOD': 16, 'CELL_SEMI': 11, 'CELL_SET': 11, 'CELL_INSP':  8, 'CELL_QA':  8, 'CELL_PACK':  4},` — `# 1 MOD_RUSH`
- L49 `{'CELL_MOD':  7, 'CELL_SEMI':  9, 'CELL_SET': 20, 'CELL_INSP':  8, 'CELL_QA':  8, 'CELL_PACK':  6},` — `# 2 SET_RUSH`
- L50 `{'CELL_MOD':  7, 'CELL_SEMI':  9, 'CELL_SET': 12, 'CELL_INSP':  8, 'CELL_QA':  8, 'CELL_PACK': 14},` — `# 3 PACK_RUSH`
- L51 `{'CELL_MOD':  6, 'CELL_SEMI':  7, 'CELL_SET':  8, 'CELL_INSP':  6, 'CELL_QA':  6, 'CELL_PACK':  5},` — `# 4 LOW_UTIL(38명)`
- L57 — `# 셀 합계 인원을 라인 baseline 비례로 정수 분배. 각 라인 ≥1, 합 == cell_total.`
- L58 — `# 나머지(반올림 손실)는 소수부 큰 라인부터 +1, 초과면 인원 많은 라인부터 −1.`
- L78 — `#========셀 재구성 시뮬 환경 (CproSimEnv 서브클래스)========`
- L80 — `# __init__ 는 CproSimEnv 그대로 (factory 가 동일 kwarg 로 생성). 셀 상태는 reset 에서.`
- L84 — `#========셀 재구성 상태 (← 에피소드마다 재생성, 외부입력 self.workers 는 불변 유지)========`
- L85 `self._upw              = {ws: self.workers[ws]['UnitsPerWorker'] for ws in self.workers}` — `# 라인별 1워커당 동시처리 (Aging=10)`
- L86 `self._baseline         = {ws: self.workers[ws]['worker_count']   for ws in self.workers}` — `# WWM 기본 인원(=template 0)`
- L87 `self._assigned_workers = dict(self._baseline)` — `# 현재 라인별 배치 인원`
- L88 `self._line_cap         = {ws: self._assigned_workers[ws] * self._upw[ws] for ws in self.workers}` — `# 라인 동시작업 한도`
- L91 `self._horizon_sec      = float(EPISODE_DURATION_SEC)` — `# run() 이 실제 horizon 으로 덮어씀`
- L92 `self._record_schedule  = getattr(self, '_record_schedule', False)` — `# opt-in (run 전 set → 간트용 이벤트 기록)`
- L93 `self._schedule_log     = []` — `# [{model, pc, line, t0, t_cycle, t_total}] — _redraw_gantt_slots 스키마`
- L96 — `# 템플릿 → 라인별 배치 인원 재산출 → worker_resources(simpy.Resource) 를 새 capacity 로 재생성.`
- L97 — `# self.workers 는 건드리지 않는다(외부입력 mutate 금지 — 유휴/관측 분모는 _assigned_workers/_assigned_view).`
- L98 — `# ※ Resource 재생성 = capacity 런타임 변경 불가 우회. 진행 중 job 은 자기 req 의 옛 Resource 로`
- L99 — `#   release(_run_job 가 req.resource 사용)하므로 교체해도 정합. 신규 요청만 새 Resource 로.`
- L100 `new_assigned = dict(self._baseline)` — `# 셀에 없는 라인(없음)은 baseline 유지 — 방어`
- L108 `self.worker_resources[ws] = simpy.Resource(self.env, capacity=self._line_cap[ws])` — `# 새 capacity`
- L110 `for ws in self.workers:` — `# 캡 상향분 즉시 가동 / 잠든 디스패처 재평가`
- L114 — `# IdleViolationCount(workers) 가 읽는 worker_count 를 현재 배치 인원으로 치환한 view.`
- L118 — `# potential() 의 6항 분해 (W·정규화metric, 부호 포함). 합 == potential() (보상항별 비교용).`
- L119 — `# ※ 기반 potential() 본문과 동일 수식 — 변경 시 동기 유지(PoC 진단용 거울).`
- L133 — `# 기반 _dispatcher 와 동일하되 교정 1개: res 를 루프 진입 시 캡처하지 않고 매 루프 재조회 →`
- L134 — `# _apply_cell_template 의 Resource 교체가 다음 요청부터 반영(기반의 1회 캡처 버그 회피).`
- L136 `if not self._pending[ws]:` — `# 큐 빌 때 잠듦`
- L140 `if not self._is_work_time():` — `# 비근무면 재개까지 점프`
- L143 `res = self.worker_resources[ws]` — `# ★매 루프 재조회 (교체된 Resource 반영)`
- L144 `req = res.request()` — `# 워커 슬롯 대기(capacity 가 동시성 enforce)`
- L147 `if not pend:` — `# 단일 디스패처라 보통 발생X — 안전망`
- L150 `distinct_pcs = list(dict.fromkeys(job['pc'] for job in pend))` — `# 순서보존 distinct 공정`
- L151 `if dispatch_agent is not None and len(distinct_pcs) >= 2:` — `# contention 시 dispatch agent (PoC 기본 None=FIFO)`
- L160 — `# 기반 _run_job 와 동일하되 교정 1개: release 를 self.worker_resources[ws] 가 아닌 req.resource 로 →`
- L161 — `# cycle 중 Resource 가 교체돼도 자신이 점유한 옛 Resource 에 정확히 반납(교차 release 오염 회피).`
- L164 `t0   = self.env.now` — `# cycle 시작(=워커 점유 시작) — 간트 t0`
- L167 `req.resource.release(req)` — `# ★req 자신의 Resource 로 반납`
- L168 `t_cycle = self.env.now` — `# cycle 끝(=워커 해제) — 간트 t_cycle`
- L182 `if node.DepWaitSec:` — `# 본드 경화·AGING 등 후처리 대기 (워커 비점유)`
- L188 `if self._record_schedule:` — `# 간트용 이벤트 (워커 점유 [t0,t_cycle] + 후처리 t_total)`
- L195 — `# 계획틱: plan_interval_sec 마다 셀 구성 재선택·적용 (하루 1회=86400 기본). 비근무 게이트 없음 —`
- L196 — `# 캡은 다음 근무 재개 시 발효되므로 자정 재편이 자연스러움.`
- L203 — `# [throughput/model] + [time, demand_scale, required_pace] + [occupancy/cell, pending/cell] + [template one-hot]`
- L207 — `# 셀 선택용 관측. 전부 0~1 근방 정규화. AAS-grounded(throughput/target/workers/in_progress)만 사용.`
- L208 — `# demand_scale·required_pace 는 t=0 에도 수요 규모를 노출 — critic 이 수요 분산을 baseline 으로`
- L209 — `# 흡수하고 actor 가 수요에 조건부 선택하도록(없으면 t=0 상태가 수요와 무관해 학습 신호 약화).`
- L212 `for model_id in self.target_qty:` — `# 모델별 throughput 진척`
- L214 `feats.append(min(self.env.now / self._horizon_sec, 1.0))` — `# 시간 진척`
- L215 `feats.append(min(total_target / (len(self.target_qty) * 100.0), 1.5))` — `# 절대 수요규모 (PoC 정규화: 모델당 100 기준)`
- L218 `feats.append(min((remaining / (time_left_h + 1e-6)) / 50.0, 2.0))` — `# 필요 페이스 EA/h (PoC 정규화: 50 기준)`
- L219 `for cell_id, lines in CELLS.items():` — `# 셀별 점유율 + 대기 깊이`
- L225 `for template_id in range(len(CELL_TEMPLATES)):` — `# 현재 템플릿 one-hot`
- L231 — `# cell_agent: 셀 구성 RL/selector (None=재구성 없이 BALANCED 고정 = B1). dispatch_agent: 미시`
- L232 — `# 디스패치(PoC 기본 None=FIFO). 기반 run() 의 셀-틱 추가판 — _watch idle 분모만 _assigned_view.`
- L236 `if cell_agent is not None:` — `# t=0 초기 결정 (horizon<interval 도 1회 적용 보장)`
- L272 — `#========셀 선택자: RL agent + 베이스라인 (공통 인터페이스 choose_cell(env)->int)========`
- L274 — `# 셀 템플릿 선택 정책(K 카테고리 MLP actor-critic) + MC-return PPO-clip.`
- L275 — `# ★보상은 dispatch PPOAgent 의 telescoping(Φ delta)이 아니라 episode return(R) 의 MC 추정:`
- L276 — `#   셀 결정은 '에피소드 내내 어느 구성을 유지하나' 의 에피소드 단위 행동이라 그 가치가 궤적 전체에`
- L277 — `#   걸쳐 있다. Φ telescoping 으로 per-step 쪼개면 credit 이 노이즈에 묻혀 학습이 최적 템플릿을 못 찾음`
- L278 — `#   (검증: 동일 셋업서 telescoping 은 MOD_RUSH 오수렴, MC-return 은 LOW_UTIL 정수렴). advantage=R−V(s),`
- L279 — `#   critic 이 수요별 baseline 흡수. dispatch 의 그래프노드 행동(다른 시간스케일)과 의도적으로 다름.`
- L299 `self.buf = []` — `# 계획틱마다 {state, idx, logp}`
- L310 — `# 에피소드 종료 후 1회 PPO-clip (MC-return). 전 결정에 동일 return R, advantage=R−V(s). buf 비면 None.`
- L338 — `# 고정 템플릿 (B1=ConstSelector(0)=BALANCED, 또는 스윕용 임의 템플릿 고정).`
- L347 — `# 무작위 템플릿 — RL/규칙의 하한 비교군.`
- L357 — `# B2 규칙 정책: 병목 셀(점유율+대기 최대)에 맞는 rush 템플릿. 거의 완료면 LOW_UTIL(유휴 절감).`
- L358 — `# 실공장 계획자 수준의 휴리스틱 — RL 이 이걸 이겨야 정당성. (셀→템플릿은 PoC 휴리스틱 매핑)`
- L360 `BOTTLENECK_TO_TEMPLATE = {'CELL_MOD': 1, 'CELL_SET': 2, 'CELL_PACK': 3}` — `# rush 템플릿 보유 셀만`
- L363 `if sum(env.Throughput.values()) >= 0.9 * total_target:` — `# 막바지 → 저유휴`


---

## Task 2 — 납기 보상 (W7_DueDate) 설계 노트

PO 납기일(DueDay)을 생산성 보상에 반영. **페이스 기반** — 매 결정점 조밀·선제 신호.

### 메커니즘 (DuePaceDeficit)
- 모델 m: 필요 진척률 `r_m = min(now / (DueDay_m×86400), 1)`, 실제 `p_m = Throughput_m / target_m`.
- 페이스 결손 `d_m = max(0, r_m − p_m)` (뒤처지면 양수, 앞서면 0).
- `_watch` 틱(30s, 근무시간)마다 `DuePaceDeficit += Σ_m d_m` 누적 (단조 카운터 — W3/W4/W6 패턴, telescoping 안전).
- 보상: `Φ −= (DuePaceDeficit / _due_violation_norm) × W7_DueDate`.
- 정규화 `_due_violation_norm = max(1, n_models × nominal_work_ticks)` (reset 1회 산출).
- W5(throughput) 불변 → 생산성 차원 = W5 + W7.

### 구현 위치
- `path_extractor.py` `RuntimeVariables.DuePaceDeficit(Throughput, target_qty, DueDay, now, DuePaceDeficit)` — 순수 누적 (AAS 명시 연산).
- `build.py build_simulation`: PO에서 `DueDay = {model: day×86400}` 추출·주입(`due_day=` 오버라이드로 모델별 머지 가능), RewardWeights 튜플에 'W7_DueDate' 추가.
- `simulation.py CproSimEnv`: `DueDay` 주입(__init__), reset에 `DuePaceDeficit=0`·`_due_violation_norm`, _watch 누적, potential W7 항, state_vec 페이스 결손 채널(+1, state_dim 18→19).
- `scratch/plan_cell.py` (셀재구성 RL PoC — 보관): reward_terms W7 + _watch 누적.
- `aas_data/ProvisionOfSimulationModel.json`: RewardWeights에 W7_DueDate Property(value 0.25) + ConceptDescription.

### horizon
- `EPISODE_DURATION_SEC = 30 × 86400`(30일). 에피소드는 전 생산 완료 시 즉시 종료(`_watch`)하므로 큰 값은 상한일 뿐 — 잘림 방지용. (구 3일은 완성 전 절단.)

### 검증 (스모크)
- baseline DueDay=22일: W7norm ≈ 0.022 (느슨 → 페이스 여유, 소penalty).
- tight DueDay=1일: W7norm ≈ 0.43 (빡빡 → 큰 penalty, 발화). 의도대로 차등.

### 운용 메모
- 현재 PO 전부 DueDay=22·수량 100 (학습 기준선). 모델 간 **차등 납기**로 바꿔야 W7이 *우선순위*를 차별 — 동일 납기에선 W5 보강에 가까움.

---

## Task 3 — 탄소 어댑터 (carbon.py · W2) 설계 노트

에너지(W2)를 탄소 변환 seam을 거치게 함. ECO가 MCF 탄소 수식/계수를 주면 **carbon.py만 교체**.

### 구조 (직접 import, run 주입 X)
- `carbon.py`: 배출원 변환 함수 모음. 현재 전력만 —
  - `EMISSION_FACTOR_KWH = 1.0` (kgCO2e/kWh, Scope2 전력). proxy=1.0 → 동작 보존. **ECO 교체점**.
  - `from_energy(kwh) = kwh × EMISSION_FACTOR_KWH`.
  - `total(energy_kwh)` = Σ 배출원 집계 진입점 (현재 = from_energy).
- 일반화: 전력과 **같은 레벨**(설비·공정 가동 시 직접 탄소)의 배출원이 추가될 수 있음 — `from_X` 함수 + `total` 합산 항. (자재 LCA 아님 — 가동 기반.)
- 각 모듈이 `import carbon` 후 직접 변환. run 주입 없음(배출계수 고정이라 불필요; AAS/run 주입은 동적계수 필요 시 추후 승격).

### 결선
- `simulation.py potential()` W2: `− (carbon.total(EpisodeEnergyKwh) / carbon.total(_max_episode_premium)) × W2_Energy`.
  - 에너지 회계(kWh)는 `RuntimeVariables.EpisodeEnergyKwh`(AAS) 유지 — carbon은 변환만.
- `export.py build_payload`: `carbon_kgco2e = carbon.total(energy)`.

### 검증
- factor=1.0: W2_carbon == W2_energy (0.9986) → 기존 동작 보존.
- factor 변경(0.4541): potential 불변 — 선형 계수가 분자·분모에서 약분.
- ⇒ W2가 *실질적으로* 탄소로 작동하려면 ECO가 **비선형/다배출원** 모델을 줘야 함. 그 전까진 에너지 proxy.

### AAS idShort
- W2 idShort는 `W2_Energy` 유지(에너지가 탄소 기반, 현 동작 동일). ECO 실모델 결합 시 `W2_Carbon` 개명 검토.


## build.py 설계 노트 (공유그룹·idle·PO)

### 공유그룹(shared) 판별 — 하드코딩 제거
`build_simulation`의 `shared_groups`는 `KnowledgeGraph.Node` 그룹 중 **모델 공유**(KG에서 model_id='ALL'로 1회 생성) 노드를 고른다. 과거엔 `DEFAULT_SHARED_GROUPS=('ProcessOQC',)` 하드코딩이었음.

- Node 5그룹 = `SIM_MODEL_A/B/C`(모델별 — 실제 per-model 노드는 `MP.groups`에서 오므로 **중복·미사용**) + `ProcessOQC`(활성 공유, `SamplingRate=0.05`) + `ProcessRMA`(**비활성**: `SamplingRate=None`, `WWM_RMALine` 워커 6·예측자 11개(주공정) → 포함 시 전 유닛이 RMA로 라우팅·활성화됨. 미완 모델이라 의도적 off).
- 현재 규칙(코드만, AAS 무변경): `if not name.startswith('SIM_') and any(node.SamplingRate is not None for node in group.value.values())` → SIM_* 제외 + RMA(미샘플) 제외 = **OQC만**.
- ⚠️ **SamplingRate를 "활성 공유" 프록시로 전용한 휴리스틱**이라 취약: 샘플링 없는 활성 공유공정이 생기면 누락, 샘플링 있는 비활성 공정이 생기면 오포함. 견고한 대안 = AAS Node 그룹에 명시 `Scope/Active` Qualifier, 또는 `ProcessRMA`를 Node+Action에서 제거. RMA 정식 모델링 시 재검토.

### 기저 전력 — 설비(워크스테이션) 단위·근무시간 게이팅 (구 idle 전력 모델 대체)
`DefaultProcessConsumedPowerKw`(AAS `DefaultParameters`, 구 `IdleProcessRatedPowerKw`): 공장 공통 주기 소모 + 설비 켜둠 소모를 퉁친 기저값. 기저 에너지 = **워크스테이션 수** × kW × **근무시간 경과**(`_work_elapsed`, 휴게 제외) — 과거 "KG 노드 수 × env.now(24h)"에서 변경(노드 단위는 모델×공정 중복 카운트였음). 가동 에너지는 공정별 `CycleTimeSec × RatedPowerKw` **전액**(과거 `Rated − idle` 차감 제거 — 기저가 노드 단위가 아니게 되어 차감 근거 소멸, 기저를 정격보다 높여도 클램프로 신호가 죽지 않음). W2_Energy 분자 = `total_energy_kwh()`(기저+조립 가동+SMT 가동, 실 전력 총 적산) — state 관측도 동일. 분모 = 가동 최대 + (기저 + SMT 정격 합, SMT 실가동일 때만) × 지평. 지평 = `ExpectedMakespanSec`(병목 라인 하한 × 1.5): 라인별 Σ target×CycleTime ÷ (worker_count×UnitsPerWorker)의 최대 — 과거 `work_day_sec × 총 target`(직렬 가정, 실제의 ~40배)은 시간항을 자기상쇄시켜 기저값을 키워도 W2 신호가 안 컸음(상한 = W1의 1/3). 실 makespan 이 지평을 넘으면 비율 > 1 허용(의도). 소규모 PO 는 고정 지연(SMT flush·에이징) 때문에 비율이 크게 나옴 — q180 스케일에서 ~1 근방. SMT 는 기저(DefaultProcessConsumedPowerKw) 부과 대상에선 제외 — smt.py 가 근무시간 정격 연속 소모로 이미 시간 비례 적산. 과거 `IdlePowerRatio=0.10` 하드코딩 제거 이력은 동일.

### PO 단일 순회
`target_qty`·`DueDay`를 `PurchaseOrder.items()`의 `(quantity, day, registered)` 한 번 순회로 산출. 과거 `PurchaseOrder.target_qty()` 별도 메서드 + `items()` 이중 순회 → 메서드 제거하고 통합.
