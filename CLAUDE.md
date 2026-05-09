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

## 정책 상수

`OQC_RATE`, `RATED_POWER_KW`, `MIN_STOCK`, `PCB_MAP`/`THT_PCB_BY_MODEL`, `LOCATION_ORDER` 등 **AAS 템플릿에 미반영된 시뮬 정책 데이터**는 `cpro_config.py` 에 모은다. 시뮬 코드(`cpro_simulation_ver3.py`)는 `from cpro_config import *` 로 가져와 사용한다.

- 시뮬 코드 본문에는 정책 상수를 정의하지 않는다.
- 새 정책 상수가 필요하면 `cpro_config.py` 에 추가.
- AAS 템플릿이 확장되어 어떤 정책이 AAS 에서 추출 가능해지면 `cpro_config.py` 에서 제거하고 `path_extractor` 가 추출하도록 수정.
- 임시 글로벌을 **AAS 에서 가져온 것처럼 위장하기 위한 prefix 추론 등 우회 로직은 만들지 말 것**. 차라리 명시적 `cpro_config.py` 항목이 낫다.

## 시각화 분리

- 시각화(엑셀 저장, PNG 저장) 코드는 `cpro_visualization.py` 에 격리되어 있다. `cpro_simulation_ver3.py` 의 `ExperimentRunner.save_results` / `save_figures` 가 thin wrapper 로 위임한다.
- `cpro_visualization.py` 는 시뮬 모듈을 import 하지 않는다 (단방향 의존). 필요한 상수는 keyword argument 로 주입한다.
