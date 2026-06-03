# CPRO 시뮬레이션 라이브러리 아키텍처

## 0. 한 줄 요약

어떤 이산공정이든 **AAS 데이터로 구동**되는 이산사건 시뮬레이션 + 강화학습 라이브러리.
torch 가 임의 신경망 아키텍처(+커스텀)를 **코드**로 받듯, 이 라이브러리는 공정·아키텍처·알고리즘을 **AAS** 로 받는다.
→ **AAS = 라이브러리의 선언적 UI.**

---

## 1. 핵심 원칙 — 2층 구조 (코어 / 어댑터)

**코어는 AAS 를 모른다.** 코어(domain · nn · observe · sim)는 plain Python 객체·spec 을 받고,
AAS 는 그걸 만들어 코어를 구동하는 **어댑터**(aas · factory)일 뿐.

```
[AAS 어댑터]   path_extractor (AAS→객체)   +   factory (AAS→코어 wiring / spec 변환)
                         │  plain 객체·spec
                         ▼
[Core · AAS 무관]   domain   +   nn(해석기·블록)   +   observe   +   sim
```

- 코어는 **코드로도, AAS로도** 구동 가능 (torch 가 AAS 없이 동작하듯).
- AAS 구조가 바뀌어도 코어 인터페이스 불변 — 어댑터만 흡수.
- 불변식: **코어 모듈은 `path_extractor`(aas) 를 import 하지 않는다.** AAS 유래 값은 인자로 주입.

---

## 2. op-node 문법 (계산그래프) — 고정 "언어"

`ModelArchitecture` 는 op-node 들의 그래프. 각 노드:

| 필드 | 의미 |
|---|---|
| `Operation` | 실제 **import 경로** (라이브러리 클래스/함수) 예 `torch_geometric.nn.GCNConv` |
| `Arguments` | 생성/호출 인자 (**하이퍼파라미터 포함**) — 키 = 그 callable 의 실제 파라미터명 |
| `Inputs` | `{forward 파라미터명: source}` — wiring |

`source` 가 가리킬 수 있는 곳 (**닫힌 규칙**):
1. **내부** — 같은 그래프의 **이전** op-node 출력 (idShort)
2. **외부** — **닫힌 관측 카탈로그**(§4) 중 하나 (CD ref)
3. (그 외 임의 AAS 요소 ref **금지**)

→ **이 문법(= 네트워크 forward 그래프)만 고정.** 어떤 op·연결이 오는지는 전부 가변.

### ⚠ 알고리즘 ≠ 네트워크 (섞으면 해석기 트랩)

위 문법은 **네트워크**(encoder/actor/critic — `GraphModule.forward` 로 실행되는 **forward 그래프**)에만 적용된다.
**알고리즘(PPO 등)은 forward 가 없다** — episode 단위 `choose()`/`learn()`, optimizer·buffer 보유 → `GraphModule` 을 통과 못 함.
알고리즘은 `{Operation, Arguments}` 모양은 재사용하되, `Inputs`(텐서 wiring) 대신 **`Networks`**(어떤 네트워크를 쓰는지 ref)를 갖는 **최상위 selector** 이고, `GraphModule` 이 아니라 **`build_architecture`** 가 인스턴스화한다.
```
Algorithm: { Operation: "....PPOAgent",
             Arguments: { LearningRate, ClipEpsilon, Gamma, ... },     ← 하이퍼파라미터
             Networks:  { encoder: Encoder, actor: Actor, critic: Critic } }   ← 텐서 wiring 아님(네트워크 ref)
```
→ "네트워크 = AAS forward 그래프(GraphModule)", "알고리즘 = 코드 절차를 고르는 selector(build_architecture)". `Inputs` 와 `Networks` 는 다른 것.

---

## 3. 고정 vs 가변

### 고정 (아키텍처·알고리즘·공정 무관, 항상 동일)
- **문법**: op-node = `{Operation, Arguments, Inputs}`, 네트워크 = op-node 그래프.
- **해석기** `nn.GraphModule`: 문법으로부터 **임의** net/알고리즘 조립 (import + wire + dim resolve).
- **라이브러리**: `Operation` 이 가리키는 실체 — torch 레이어, 알고리즘 절차(PPO 등), 태스크 primitive, 관측 producer. **코드가 제공, AAS가 선택.**
- **도메인 정규화**: `aas`(path_extractor) + `domain`(KnowledgeGraph/Warehouse) — 공정이 바뀌어도 `build` 가 `.nodes`/`.edges` 로 흡수. 해석기는 raw AAS 안 봄.

### 가변 (AAS)
- **`ModelArchitecture` 전체** — 어떤 op/네트워크/알고리즘 + 각 `Arguments`(하이퍼 포함) + `Inputs` 연결.
  - ⚠ Encoder/Actor/Critic/PPO 는 *지금 이 AAS가 고른 것*일 뿐 **고정 골격 아님**. 다른 DL·알고리즘 가능.
- 공정그래프 내용 ← `ManufacturingProcess`, 피처/state 구성 ← CD 리스트.

---

## 4. 관측 카탈로그 (닫힌 어휘) — ⚠ 템플릿 확정 후 fix

외부 입력은 **두 종류**로 갈린다 — 섞으면 죽인 매직 바인딩이 부활한다.

### (a) 환경 관측 — **인코더**가 env 에서 읽음 → AAS 카탈로그 ref 가능 (**닫힌 집합**)
| 소스 | 정의 | AAS 표현 | 가변? | producer (고정, 도메인 클래스 위) |
|---|---|---|---|---|
| **NodeFeatures** | 노드별 피처 벡터 | 속성 CD **리스트** | **O** (어떤 속성) | 노드마다 그 CD gather → `x` |
| **Topology** | 그래프 인접 | `GraphTopology` CD **1개** | X | `kg.edges` → `edge_index` |
| **StateVector** | 전역 상태 | RuntimeVariable/Param CD **리스트**(구성) | **O**(구성)/정규화 코드 | `env.state_vec()` |

→ AAS ref 가 가리킬 수 있는 CD = **이 (a) 카탈로그뿐**. 매직 문자열·임의 ref 금지.

### (b) 알고리즘 내부 중간값 — **코드(알고리즘)가 actor/critic 에 공급** → AAS 아님
- **ReadyEmbeddings**(인코더출력 @ ready), **PooledEmbeddings**(평균), actor/critic 에 들어가는 **state 텐서 전달**.
- env 관측이 아니라 `PPO.choose()` 가 인코더→actor/critic 사이에서 만들어 **함수 인자로 넘기는 값**. → **AAS 에 두지 않는다**(두면 매직 바인딩 부활 = `Actor.Inputs.x="ReadyEmbeddings"` 가 알고리즘 내부를 가리키는 매직이 됨).
- 그래서: **인코더 Inputs = (a) AAS 관측 ref** / **actor·critic 진입 Inputs = (b) 알고리즘이 채우는 포트**(네트워크 입력 시그니처). actor/critic 의 *내부 레이어*는 AAS forward 그래프지만, *무엇이 먹이는지*는 알고리즘 코드.

> 주: (a) 는 **현 GNN 기준 — 지금 그대로 ship**. §9 의 "템플릿 의존" 은 *추가*만(비-GNN 대응 등). 즉 observe 구현은 템플릿을 기다리지 않는다.

---

## 5. 모듈 아키텍처 + API

### `aas/` — AAS → 타입 객체 (어댑터)
```python
def load(aas_dir, files) -> None                      # 싱글톤 채움
ProvisionofSimulationModelsAAS                         # .SimulationModels.SimulationModel....
# 도메인 SME: Property/SMC/SML/ReferenceElement/ProcessNode/ObservationNodeFeatures...
```
현재: `path_extractor.py`. 변경 거의 없음.

### `domain/` — 정규화 (안정 경계: 공정 변형 흡수)
```python
class KnowledgeGraph:
    @classmethod
    def build(manufacturing_processes, workers, shared_groups, node_feature_attrs) -> KnowledgeGraph
    nodes: dict[str, GraphNode]; edges: dict; workers: dict; NodeFeatureAttrs: list[str]
    def to_pyg_data() -> (Data, node_list)            # x, edge_index
    def ready(completed, in_progress, warehouse) -> list[str]
class Warehouse:
    @classmethod build(...) -> Warehouse
    def consume(bom); def produce(bom); def replenish(...)
```
현재: `simulation_ver1.py` 안. **AAS 유래 객체를 인자로 받음(주입), AAS import X.**

### `nn/` — 해석기 + 빌딩블록 라이브러리 (torch-like 코어)
```python
def import_callable(path: str) -> type | Callable     # "torch_geometric.nn.GCNConv" → 실체
class GraphModule(nn.Module):
    def __init__(spec: list[dict], source_dims: dict)  # 계산그래프 spec(plain) → net
    def forward(**sources) -> Tensor                   # import + wire (아키텍처 표현 안 함)
def op_concat_state(x, state); def op_squeeze_last(input)   # 태스크 primitive
class PPOAgent:                                        # 알고리즘 절차
    def choose(ready, env) -> pc;  def learn(reward, kg) -> metrics
def build_architecture(networks: dict, algorithm: dict, env) -> Agent   # spec → Agent
```
현재: `GraphModule`/`import_callable`/op primitive/`PPOAgent` 이번 세션에 구현됨. **이미 spec(plain)을 받음 = AAS 무관.**

### `observe/` — 관측 카탈로그 (닫힌 producer 집합)
```python
def node_features(kg) -> Tensor        # kg.NodeFeatureAttrs gather
def topology(kg) -> Tensor             # kg.edges → edge_index
def state_vector(env) -> Tensor
def ready_embeddings(emb, ready); def pooled_embeddings(emb)
OBSERVATION_CATALOG: dict[source_id, producer]        # 닫힌 집합 (§4)
```
현재: **흩어져 있음** — `to_pyg_data`(KG), `state_vec`(env), ready/pooled(PPOAgent.choose). → 통일 + 매직문자열 제거가 신규 작업.

### `sim/` — 이산사건 시뮬
```python
class ProcessSimEnv:                                  # 현 CproSimEnv
    def __init__(knowledge_graph, warehouse, *, target_qty, reward_weights, ...)
    def reset(); def run(agent, max_sec) -> summary
    def state_vec() -> Tensor; def potential() -> float; def episode_reward() -> float
    state_dim: int
```
현재: `simulation_ver1.CproSimEnv`. 도메인 객체 + 정책값 주입.

### `factory/` — AAS → 코어 wiring + 진입점 (어댑터)
```python
def build_simulation(aas_dir, *, target_qty, ...) -> ProcessSimEnv
def build_agent(env, *, checkpoint=None) -> Agent
def model_arch_to_spec(model_architecture_aas) -> (networks, algorithm)   # AAS → plain spec
class SimulationShell:                                # 향후 exe/REST 외피
    def run(aas_json, config) -> result
```
현재: `cpro_factory.py`. AAS→spec 변환을 build_agent 가 이미 일부 수행(`_graph_spec`).

### 코어 의존 방향 (acyclic — 파일 분할 전 고정)

순환 import 방지. **허용 화살표만**:
- `domain` — 코어 의존 **없음** (leaf).
- `observe` → `domain` (producer 가 kg 읽음).
- `sim` → `domain` (`state_vec` 등 env 상태는 sim 보유).
- `nn` → `observe` + `domain` (agent 가 producer·kg 사용; **env 는 주입**받아 duck-typed — `nn` 은 `sim` 미import).
- `factory` → 전부 + `aas`.
- `aas` — standalone (factory 만 사용). **코어는 `aas` 미import.**

→ leaf=`domain`; `observe`/`sim`/`nn` 은 `domain`(±`observe`)만; `factory` 가 위에서 묶음. 순환 없음.

---

## 6. 불변식 (반드시 성립)

1. `Operation` = **import 가능**한 클래스/함수.
2. `Arguments`/`Inputs` 키 = 그 callable 의 **실제 파라미터명**.
3. NodeFeatures CD = 각 GraphNode 가 **실제 보유한 속성**(= ProcessNode 속성).
4. 외부 source ref = **§4 카탈로그 중 하나만** (매직 문자열·임의 ref 금지).
5. 내부 source ref = 같은 그래프의 **이전(정의된)** op-node.
6. **코어 모듈(domain/nn/observe/sim)은 aas(path_extractor)를 import 하지 않는다.**

---

## 7. 확장점 (torch 처럼 — "어떤 아키텍처든 + 커스텀")

| 추가하려는 것 | 어디 | 코드 수정 |
|---|---|---|
| 새 레이어 (GAT 등) | AAS `Operation` 에 import 경로 | **無** |
| 커스텀 레이어 | 내 클래스 → AAS 가 경로 ref | 클래스만 |
| 새 알고리즘 | `nn/` 절차 클래스 추가 | 추가 → AAS 선택 |
| 새 관측 소스 | `observe/` producer + 카탈로그 등록 | 추가 |
| 새 공정 | **AAS 데이터만** | 無 (domain 정규화) |

---

## 8. 현황 → 목표 (마이그레이션)

**리라이트 아님** — 본 구조는 현 작동 코드를 역설계한 것. 대부분 이미 존재.

- **이미 정렬**: aas(path_extractor), nn 해석기(이번 세션), domain(KG/Warehouse), sim(CproSimEnv), factory(cpro_factory), 알고리즘(PPOAgent). 2층 분리 사실상 성립.
- **작은 변경(기계적)**: vestigial `GNN` SME 제거; `simulation_ver1.py` → domain/nn/sim 모듈 분할 + import 갱신.
- **중간 변경(신규 로직)**: ① `observe/` 카탈로그 통일 + 매직문자열(ObservationEdgeIndex 등) → 카탈로그 ref(해석기가 ref-입력 vs 문자열-입력 구분); ② PPO → op-node `Arguments`(TrainingConfig SMC 폐기, 알고리즘 노드화).
- 체크포인트는 이미 깨진 상태(재학습 필요) → 재구조화 적기.

권장 순서: ① GNN 제거 + PPO→Arguments → ② observe 카탈로그 + 매직문자열 제거 → ③ 파일 분할.

**회귀 기준** (골든/체크포인트 동등성은 재학습으로 사라짐 → 대체 가드레일). 각 단계 후:
1. `build_simulation` + `build_agent` **빌드 성공** (차원·구조 일치),
2. **몇 에피소드 학습 동작** (choose + learn 무오류),
3. **reorder/sensitivity** (AAS 바꾸면 net·관측이 실제로 바뀜 — decorative 아님 증명).

---

## 9. Open (템플릿 확정 후 / 합의 필요)

- **관측 카탈로그 닫힌 어휘** 확정 (§4 가 충분한지, 비-GNN 대응).
- **정규화 경계** 세부 (어디까지 `KnowledgeGraph` 클래스가 흡수).
- 알고리즘 노드가 네트워크를 `Inputs` 로 받는 정확한 형태.
- `SimulationShell` exe/REST 형태 (BI/KETI 설계안 대기).
- 합성 공정 데이터로 일반화 테스트 (헵시바 기술사양서 도착 후).
