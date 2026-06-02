# CPRO 시뮬레이션 — 모듈 분할 · 캡슐화 UML

비아이매트릭스(대시보드 코드 전달) · KETI(API 연동) 산출물(과제수행계획 Line 20·21, 2026-08~10)을
위한 모듈 분할/캡슐화 설계. 회의 합의: "플랫폼 안에서 UML(usecase/class/sequence)로 BI와 의사소통".

## 범례 (표기)

- **기존(solid)** — 현재 코드에 이미 있는 것.
- **신규-코드** — 추가할 코드. **AAS 변경 없음** (factory, 외피).
- **⚠ AAS변경-합의필요** — A안(SMT→창고 적재) 때문에 AAS 템플릿에 새 필드가 필요한 것.
  → AAS 구조 변경은 단독 진행 금지, 합의 대상.

### A안이 요구하는 AAS 변경 (합의 항목 — 이것 하나)

SMT 공정 노드가 "무엇을 몇 개 창고에 적재하는지" 알아야 하므로, **SMT 산출 노드에 `OutputBOM`**
(item_code → Quantity) 을 추가해야 함. 이 한 가지 외에는 전부 코드 변경:
- `Warehouse.produce(OutputBOM)` — 노드 완료 시 산출물 적재 (현재 `Warehouse`는 consume 전용).
- SMT→AAS 노드화가 끝나면 `cpro_smt.py` stub + `_StockRouter` 특수경로는 폐기.

---

## 1. 유스케이스 다이어그램

```mermaid
flowchart LR
  A1([AAS 저작자 / BI UI]):::actor
  A2([운영자]):::actor
  A3([비아이매트릭스 대시보드]):::actor
  A4([KETI 플랫폼]):::actor

  subgraph SYS["CPRO 시뮬레이션 (캡슐화 대상)"]
    direction TB
    U1((공정노드 자동생성<br/>AAS→Knowledge Graph))
    U2((시뮬레이션 실행))
    U3((강화학습 정책 학습<br/>선택))
    U4((결과 조회·스트림))
  end

  A1 --> U1
  A2 --> U2
  A2 -. 선택 .-> U3
  A4 --> U2
  A3 --> U4
  A4 --> U4
  U2 -. include .-> U1
  U3 -. include .-> U2
  classDef actor fill:#eef,stroke:#88a;
```

- 입력 데이터의 유일 원천은 AAS JSON(BI UI가 생성). 실행은 그래프 생성을 **include**.
- 강화학습은 실행을 반복하는 **선택** 유스케이스 — 핵심 경로 아님(회의: "RL 핵심 아님").

---

## 2. 클래스 다이어그램 (모듈 분할)

5계층: ingest(공정노드 입력) → 도메인(공정노드/창고) → 시뮬생성 → 강화학습 → factory/외피.

```mermaid
classDiagram
  direction LR

  class ProvisionofSimulationModelsAAS {
    +submodels
    +RuntimeVariables
  }
  class KnowledgeGraph {
    +dict nodes
    +dict edges
    +dict workers
    +build()
    +ready_queue()
    +to_pyg_data()
  }
  class GraphNode {
    +str ProcessCode
    +str model_id
    +float CycleTimeSec
    +float RatedPowerKw
    +dict InputBOM
    +dict OutputBOM
  }
  class GraphEdge {
    +str ProcessCode
    +str DepType
  }
  class Warehouse {
    +dict inventory
    +build()
    +consume()
    +replenish()
    +produce()
  }
  class StockItem {
    +float present_stock
    +float MinStock
    +float MaxStock
  }
  class _StockRouter {
    +consume()
    +replenish()
  }
  class CproSimEnv {
    +run() summary
    +reset()
    +produce_unit()
    -_dispatcher()
    -_run_job()
    +state_vec()
    +potential()
  }
  class PPOAgent {
    +choose()
    +learn()
  }
  class GNNEncoder
  class Actor
  class Critic
  class build_simulation {
    +call() CproSimEnv
  }
  class build_agent {
    +call() PPOAgent
  }
  class SimulationShell {
    +simulate() OUT
  }

  KnowledgeGraph "1" *-- "many" GraphNode
  KnowledgeGraph "1" *-- "many" GraphEdge
  Warehouse "1" *-- "many" StockItem
  _StockRouter o-- Warehouse
  CproSimEnv --> KnowledgeGraph : uses
  CproSimEnv --> Warehouse : uses
  CproSimEnv ..> PPOAgent : choose at contention
  PPOAgent *-- GNNEncoder
  PPOAgent *-- Actor
  PPOAgent *-- Critic
  build_simulation ..> ProvisionofSimulationModelsAAS : load
  build_simulation ..> KnowledgeGraph : build
  build_simulation ..> Warehouse : build
  build_simulation ..> CproSimEnv : new
  build_agent ..> PPOAgent : new
  SimulationShell ..> build_simulation
  SimulationShell ..> build_agent

  note for GraphNode "OutputBOM: A안 신규 — SMT 노드 산출물. ⚠AAS변경(합의)"
  note for Warehouse "produce(): A안 신규 — 완료 시 창고 적재. 현재 consume 전용"
  note for _StockRouter "현 PCB 분리경로. SMT→AAS 노드(A안) 후 폐기 대상"
  note for build_simulation "신규 factory — 중복 wiring 통합. 코드만(AAS 무관)"
  note for SimulationShell "신규 외피(exe/API). OUT dict 위 어댑터. 통합방식 무관"
  note for ProvisionofSimulationModelsAAS "AAS 단일 진입점(ingest). torch/simpy 무의존"
```

계층 ↔ 회의 3모듈:
- **공정 노드 생성** = `ProvisionofSimulationModelsAAS` + `KnowledgeGraph`/`Warehouse`
- **시뮬 생성** = `CproSimEnv`
- **강화학습** = `PPOAgent`(+`GNNEncoder`/`Actor`/`Critic`) — `CproSimEnv`에 꽂는 선택 플러그인
- **factory/외피** = `build_simulation`/`build_agent` + `SimulationShell` (신규)

---

## 3. 시퀀스 다이어그램 — 시뮬레이션 실행(핵심 흐름)

```mermaid
sequenceDiagram
  autonumber
  participant C as caller / Shell
  participant F as build_simulation
  participant KG as KnowledgeGraph
  participant WH as Warehouse
  participant E as CproSimEnv
  participant D as _dispatcher(ws)
  participant J as _run_job
  participant AG as PPOAgent

  C->>F: build_simulation(aas_dir, overrides)
  F->>KG: build(MPs, workers, shared)
  F->>WH: build(BOM, MinStock)
  F->>E: new CproSimEnv(KG, WH, ...)
  F-->>C: env (+ agent)

  C->>E: run(agent)
  E->>E: reset()
  loop 주문 수량만큼
    E->>E: produce_unit(model_id)
    E->>KG: ready_queue(completed, WH)
    KG-->>E: ready PCs
    E->>D: pending 큐에 job 추가 후 dispatcher wake
  end
  loop 워커 슬롯이 빌 때마다
    D->>D: 근무시간 게이트 · 슬롯 확보
    alt 경합(공정 ≥2) & agent
      D->>AG: choose(distinct_pcs)
      AG-->>D: chosen_pc  (PPO 결정점)
    else FIFO (greedy/단일)
      D->>D: pend[0]
    end
    D->>J: _run_job(ws, job)
    J->>J: timeout(CycleTimeSec)
    J->>WH: consume(InputBOM)
    opt 발주점 이하
      J->>WH: replenish(lead_time, ordered)
    end
    opt A안 · SMT 산출 노드
      J->>WH: produce(OutputBOM)
    end
    Note over J,WH: produce()는 A안 신규 — ⚠AAS OutputBOM 합의 필요
    J->>E: Throughput 증가 후 dispatcher wake
  end
  E-->>C: {Throughput, makespan_sec, EpisodeEnergyKwh, events}
```

---

## 4. 시퀀스 다이어그램 — 캡슐화/통합 경계 (BI·KETI)

```mermaid
sequenceDiagram
  autonumber
  actor BI as 비아이매트릭스 / KETI
  participant S as SimulationShell (exe/API)
  participant F as build_simulation
  participant E as CproSimEnv

  BI->>S: simulate(aas_json, params)
  S->>F: build_simulation(aas_dir, overrides)
  F-->>S: env
  S->>E: run(agent?)
  E-->>S: OUT {Throughput, makespan_sec, EpisodeEnergyKwh, events}
  S-->>BI: 적응(JSON/스트림) → 대시보드·API 응답
  Note over S: 내부(F·E)는 통합방식·AAS와 무관 — 외피만 교체(exe↔REST↔브릿지)
```

- **OUT 계약을 안정 dict로 고정** → 대시보드 출력/자동생성 설계안이 미정이어도 내부 영향 없음.
- 외피는 `build_simulation` 위 얇은 어댑터 — exe/REST/브릿지 선택은 BI 설계안 도착 후 결정.
