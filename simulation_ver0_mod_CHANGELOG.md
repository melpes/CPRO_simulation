# simulation_ver0_mod.py CHANGELOG

`simulation_ver0.py` (사용자 원본) 와 `simulation_ver0_mod.py` (우리 작업본) 의 차이 history.

## 운영 규칙 (사용자 합의)

- **ver0 원본은 사용자 작성**. 우리는 안 건드림.
- **ver0 에 구현된 코드는 변경 / 삭제 최소화**. 변수명·signature·본문 그대로 보존이 원칙.
- **ver0 에 아직 없는 기능 추가는 OK** (예: ver3 의 produce_unit / run 등).
- ver0 변경 → `_mod` 에 반영 + 본 CHANGELOG 갱신.
- `_mod` 의 변경 → `redesign/` 패키지에 동기화.

---

## 2026-05-15 — 초기 fork (minimal patch)

### 변경 분류

**A. ver0 의 누락/미완성 보완** (호출 시 에러 나는 부분)

| 위치 | ver0 상태 | mod patch |
|---|---|---|
| `GraphNode` | `DepPrev` 필드 정의 없음 — `ready_queue` 가 `node.DepPrev.value` 호출 시 AttributeError | `DepPrev: str` 필드 추가 |
| `KnowledgeGraph.build` 안 `GraphNode(...)` | `DepPrev` 인자 안 줌 (필드 누락과 짝) | `DepPrev = ProcessNode.DepPrev.value` 인자 추가 |
| `KnowledgeGraph.build` 안 `GraphEdge(...)` | `DepPrev` 인자 안 줌 (GraphEdge 정의에는 필드 있음 — dataclass missing arg 에러) | `DepPrev = DepPrev` 인자 추가 |
| `ready_queue` DS 분기 | `node.DepPrev.value in completed` — `.value` 잘못 + single dep 만 처리 | `.value` 제거. `DepPrev.split(';')` 의 `any()` (multi-dep SEQUENCE 의 의미) |
| `ready_queue` DJ 분기 | `node.DepPrev.value.split(';')` — `.value` 잘못 | `.value` 제거 |
| `ready_queue` 전체 | 자기 PC 중복 dispatch 가능 (검사 없음) | 각 분기 진입 시 `if ProcessCode in completed: continue` |
| `CproSimEnv(gym.Env)` 상속 | `import gym` 없음 — 모듈 import 자체 안 됨 | `class CproSimEnv:` 상속 제거 |

**B. 워커 병렬 도입에 필수 patch** (ver0 의 기존 코드 일부 변경 — 불가피)

| 위치 | 변경 |
|---|---|
| `process_job` signature | `worker_resources` 인자 추가 (ver0 에 없음) |
| `process_job` 본문 | `with worker_resources[WorkstationId].request() as req: yield req:` 추가 — 워커 capacity 만큼 동시 점유. 이게 **워커 병렬의 핵심 메커니즘**. 그 안에서 ver0 의 in_progress / timeout / energy / consume / replenish 코드 그대로 |
| `process_job` 끝부분 | `if ProcessCode not in KnowledgeGraph.edges: completed.clear()` 제거. 다중 unit 동시 흐름에서 한 unit 의 terminal 도달이 다른 unit 의 completed 를 비우면 안 됨. terminal 검사는 `produce_unit` 안 unit-local 로 |
| `CproSimEnv.step` 안 `process_job(...)` 호출 | `self.worker_resources` 인자 추가. **나머지 ver0 코드 그대로 유지** (Throughput / Stock / idle / reward / observation 계산 모두 그대로) |

**C. ver0 에 없는 새 기능 추가** (사용자 동의 OK 범위)

| 추가 | 역할 |
|---|---|
| 파일 헤더 docstring + `import` | dataclass / simpy / Dict / Set. ver0 가 빠뜨림 |
| `produce_unit(env, model_id, unit_id, ...)` 함수 | 한 unit 의 KG 진행 loop. unit-local `done_set`. terminal 도달 시 `throughput_counter += 1`. ver3 패턴 |
| `CproSimEnv.__init__` 에 `TARGET_QTY` 인자 | produce_unit 등록에 모델별 qty 필요 |
| `CproSimEnv.reset` 에 `worker_resources` / `_throughput_counter` 초기화 | run() 에서 사용 |
| `CproSimEnv._check_done(stop_event, max_sec)` 메서드 | 매 30s 검사. Throughput 도달 또는 makespan 초과 시 stop |
| `CproSimEnv.run(agent=None, max_sec=...)` 메서드 | reset + 모든 unit produce_unit 등록 + env.run(until=stop_event). 워커 병렬의 진입점 |

### 보존된 ver0 코드 (변경 0)

- `GraphNode` 의 7 개 필드 (DepPrev 추가 1 개 외)
- `GraphEdge` 의 3 개 필드
- `KnowledgeGraph` 의 `_bom_satisfied` 함수 본문
- `KnowledgeGraph.build` 의 본문 구조 (DepPrev 인자 추가 외)
- `StockItem`, `Warehouse` 전체 (build / consume / replenish)
- `CproSimEnv.__init__` 의 모든 ver0 필드 할당 (`self.X = X` 줄)
- `CproSimEnv.reset` 의 ver0 변수 (`EpisodeEnergyKwh`, `Throughput`, `StockShortageCount/OverflowCount`, `idle_time`, `IdleViolationCount`, `completed`, `in_progress`) 모두 그대로
- `CproSimEnv.reset` 의 ready_queue 호출 + `return ready` 그대로
- `CproSimEnv._is_work_time` 본문 그대로
- `CproSimEnv.step` 의 본문 (Throughput / Stock / idle / reward / observation 계산) **그대로 유지** — process_job 호출에 worker_resources 인자만 추가
- ver0 의 주석 (`# int(min.split(':')[0]) * 3600 + ...` 등) 그대로

### 영향

- 사용자가 ver0 를 갱신하면 mod 동기화 — 위 A/B/C 범주 따라 옮김. 변경 영역이 작고 명확.
- `simulation_ver0.py` 가 호출 시 동작하려면 ver0 자체에 A 의 누락/미완성 fix 필요. 사용자가 갱신 시 mod 의 A 항목은 자연 사라짐 (ver0 가 직접 해소).
- B 의 워커 병렬 patch 는 ver3 패턴 의도 — ver0 가 step 모델 유지하더라도 mod 는 run() 으로 동작.
- C 의 추가는 ver0 와 syntactic conflict 없음 — 별도 함수/메서드 추가.

### redesign 동기화 후속

- `redesign/sim_env.py` 도 본 파일과 syntactic 일치하도록 정리. 트래커 (WIPTracker / EnergyLogger / IdleTracker), work_timeout, Warehouse.wait_stock 같은 ver3 부가 기능은 **redesign 별도 모듈로 layered** 추가 가능 — mod 의 코드 변경 없이.

---

## 추후 변경 시 형식

```markdown
## YYYY-MM-DD — 한 줄 요약

### 변경 분류
**A. ver0 의 누락/미완성 보완** — ...
**B. 워커 병렬 (또는 새 핵심 기능) 도입 patch** — ...
**C. 새 기능 추가** — ...

### 보존된 ver0 코드
- ...

### 영향
- ...
```
