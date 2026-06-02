# AAS 3-파트 감사·분석 보고서 (워크플로우 9에이전트 + 1차근거 검증)

대상: SMT 설비 7(.aasx XML) + MODEL_A/B/C + wwm + psm + psm_smt (JSON). 결정론 감사 `mod_run/_aas_full_audit.json`, 진단/검증은 raw 소스·PDF 원문 대조.

---

## Part 1 — 완전성·명명 감사 (13 AAS)

감사 수치는 3개 설비(Loader/Mounter/AOI) + 6 JSON 독립 재현으로 **정확 확인**(파서 버그 없음). 단 아래 해석 정제 적용.

### 파일별 수치 (main 기준, _aas_full_audit.json)
| file | nodes | CD | idMiss | CamelV | descMiss | semMiss | dangP | dangE | cdInc | dupId |
|---|---|---|---|---|---|---|---|---|---|---|
| MODEL_A | 571 | 287 | 0 | 188 | 13 | 0 | 2 | 1 | 159 | 16 |
| MODEL_B | 797 | 437 | 0 | 311 | 396 | 0 | 0 | 1 | 198 | 39 |
| MODEL_C | 642 | 305 | 0 | 227 | 134 | 0 | 0 | 1 | 2 | 0 |
| wwm | 240 | 74 | 0 | 10 | 15 | 0 | 1 | 1 | 5 | 0 |
| psm | 450 | 186 | 0 | 93 | 258 | 10 | 1 | 1 | 58 | 1 |
| psm_smt | 1385 | 284 | 0 | 100 | 258 | 10 | 70 | 1 | 156 | 1 |
| Loader | 313 | 302 | 0 | 1 | 16 | 0 | 0 | 2 | 166 | 1 |
| SPI | 464 | 396 | 0 | 1 | 8 | 1 | 0 | 2 | 125 | 16 |
| ScreenPrinter | 498 | 472 | 0 | 1 | 10 | 1 | 0 | 2 | 132 | 36 |
| Mounter | 586 | 552 | 0 | 10 | 16 | 8 | 0 | 2 | 145 | 81 |
| AOI | 428 | 515 | 0 | 1 | 8 | 1 | 0 | 3 | 134 | 35 |
| Reflow | 430 | 437 | 0 | 1 | 11 | 2 | 0 | 2 | 138 | 39 |
| Unloader | 313 | 302 | 0 | 1 | 16 | 0 | 0 | 2 | 168 | 1 |

### 카테고리별 결론
- **idShort 누락**: 전 파일 0.
- **CamelCase 위반**: 전부 `underscore` 유형(MODEL_A, BT5_*, VD7_*, NVD_*, HasPart_*, Line_1, n_modules, 설비의 HasPart_FETs/Inductors/Resistors, IPCommunication__00__). 소문자-시작 위반은 **`n_modules`(Mounter ×2)** 가 유일 — PascalCase 규약상 핵심 케이스. 도메인 ID(MODEL_A 등)는 의도적일 수 있어 판단 필요.
- **description 누락**: MODEL_B 396(actionable 112=HierarchicalStructures Entity/부품), psm/psm_smt 258(actionable 45=KnowledgeGraph 공정노드 SMC). 나머지는 대부분 CD로 커버.
- **semanticId 누락(SM 제외)**: psm/psm_smt 10(KnowledgeGraph `Action`의 ReferenceElement, idShort=None 익명). 설비의 Mounter 8/AOI 1/Reflow 2/SPI·SP 1 = ECLASS 스타일 무명 중첩 SMC(정상). MODEL_A/B/C 의 `ManufacturingProcess` SM 은 SM이라 제외되나 semanticId 부재(별도 기록).
- **dangling CD(프로젝트)**: MODEL_A `VD7FwInput`,`VD7GimbalAssembly`; wwm `UnitsPerWorker`; psm `DepNext`; psm_smt 70(SMTProcess — Part 2 참조).
- **중복 CD id(무결성)**: MODEL_A 16종·MODEL_B 39종(`HasPart_*` 2~4회), psm/psm_smt `RatedPowerKw` ×2, 설비 Mounter 81·Reflow 39·ScreenPrinter 36·AOI 35·SPI 16종(벤더 export 중복).

### 감사 해석 정제 (검증 에이전트 + 1차근거)
1. **dangling external 오분류(FP)**: submodel-template semanticId(`…/HierarchicalStructures/1/1/Submodel`, `…/sm/workstationworkermatchingdata`, 설비 `…/nameplate/3/0/…`)와 외부 ECLASS IRDI(`0173-1#…`)는 **누락 CD가 아니라 외부/템플릿 참조**. `is_cd_ref` 가 모든 ExternalReference→GlobalReference 를 CD로 본 탓 + Submodel 가드 부재. 수치는 맞으나 라벨이 과함.
2. **글로벌 union이 파일-로컬 dangling을 가림(중요)**: 각 AAS는 독립 입력 contract인데, union 기준이면 cross-file로 해소돼 가려진다. 실제로 **psm_smt `cd/CycleTime`(14×)는 ScreenPrinter 설비로만, `cd/DepPrev`(15×)는 MODEL_A/B/C로만 해소**되고, **MODEL_C에는 `cd/RatedPowerKw`가 없음**(26× 참조). → 파일 단독 기준이면 dangling.
3. **CD 불완전 과탐**: cdInc의 대부분이 `dataType`만 누락(MODEL_A 159 중 133). IEC61360 dataType은 optional이고 구조/부품 CD엔 무의미 → **soft**로 봐야 함. 진짜 결함 = `preferredName`/`definition`/`embeddedDataSpecifications` 누락(MODEL_B 다수, 설비 일부, psm 공정노드 definition 50개).
4. **ReferenceElement.value 미검사로 놓친 실결함**: MODEL_A에 **선행 공백 오염 참조** `' …/cd/P30500003/1/0'`(CD는 존재하나 공백으로 해소 깨짐)과 동종 qualifier semanticId 공백 오염. → 문자열 매칭 실패 유발하는 실제 데이터 결함.

> 감사 스크립트 보강 권고: (a) dangling에 `mt!='Submodel'` 가드 + project-namespace 한정, (b) 파일-로컬/글로벌 dangling 분리 보고, (c) dataType-only를 soft 버킷, (d) ReferenceElement.value·first/second·qualifier semanticId도 참조검사 대상에 포함, (e) 값/idShort의 선행·후행 공백 검사 추가.

---

## Part 2 — psm_smt SMTProcess 참조 해소 + 일관성 + 제안

SMTProcess 참조 슬롯 182개 전수 해소(검증 confirmed). 상태: self 1 / 설비해소 2 / 모델해소 2 / **어디에도 없음 22**.

### 일관성 문제 (소스 확인됨)
1. **`CycleTime` ↔ `CycleTimeSec`** — psm_smt 설비공정 14개가 `CycleTime` RefElem(semanticId `cd/CycleTime/1/0`)을 쓰는데 이 CD는 psm_smt·models·psm에 **없고 ScreenPrinter 설비에만 우연히 존재**. 모델/psm은 `CycleTimeSec/1/0` 사용. → 단순 표기차가 아니라 **dangling + 네이밍 불일치 동시**.
2. **`RatedPowerKw` — 정정: 불일치 아님(의도된 표기)**. psm은 단위접미 관행(`EpisodeEnergyKwh`·`IdleProcessRatedPowerKw`·`RatedPowerKw`·`CycleTimeSec`·`CuringTimeSec`·`BreakDurationMin`)을 쓰므로 `RatedPowerKw`가 정상. 설비의 `RatedPower`로 정렬하지 않는다. **남는 실제 이슈는 `RatedPowerKw` CD 중복(×2)뿐**(+값 채움은 Option 문제).
3. **ReferenceElement self-ref placeholder** — CycleTime·RatedPowerKw·Materials I/O의 RefElem `value`가 자기 semanticId CD를 그대로 가리킴(실제 대상 미지목).
4. **Mounter `Chips` 입력 — 정정: 버그 아님(의도된 설계)**. semanticId=`cd/Chips/1/0`, value→`cd/PCB/1/0`. 마운터가 올리는 칩은 **PCB의 BOM 부품**이라 칩 자원의 소스로 PCB를 가리키는 것은 의도된 모델링. (다만 psm_smt/MODEL_A에 literal "Chips" idShort 리스트는 없고 칩=PCB의 일반 부품(HasPart_*)으로 존재 — 명시적 Chips 그룹이 필요하면 후속 보강.)
5. **자산참조 ↔ globalAssetId 불일치** — 14개 설비공정 SMC semanticId=`/ids/asset/<Fac>/<모델명>` vs 설비 globalAssetId=`/ids/aas/<Fac>/1/0`. Loader만 nameplate URIOfTheProduct로 우연 일치, 6개는 placeholder라 영구 미해소. 7개 공통 존재 타깃은 globalAssetId뿐.
6. **물질흐름 join-key CD 전무** — `PCB·SolderCream·SolderPastedPCB·ChipMountedPCB·ReflowedPCB·GoodPCB·DefectPCB·Chips·Materials` 어디에도 CD 미정의 → Materials join 설계 전제 미충족.
7. **구조 컨테이너 CD 전무** — `SMTProcess·SMTLines·Line_1·Line_2·SMTMaterials` 미정의(모델은 컨테이너 SMC에 CD 부여가 norm).
8. **SMTMaterials.MODEL_A/B/C** semanticId=`cd/MODEL_X/1/0` 미정의 — 모델 globalAssetId `/ids/asset/MODEL_X/1/0`가 이미 있어 재사용 권장.
9. **DepType 부재** — 모델 ProcessNode는 `DepType`(SEQUENCE/JOIN)+`DepPrev` 쌍, SMT 노드는 DepPrev만(선형이라 SEQUENCE 암시) → 스키마 갭.
10. **n_modules** — 소문자-시작 idShort(CamelCase 위반) + `cd/n_modules` 미정의.

### 핵심 설계 결정: CycleTime/RatedPowerKw 표현 방식
- **Option 1 (현 설계: 설비 AAS lookup)** — 7개 설비 RatedPower/CycleTime value=None, 6/7 nameplate placeholder → **현 데이터로 시뮬 불가**. 채택 시 7개 설비파일 값 채움(+자산참조 정렬)이 선행. (설비는 `RatedPower`, psm은 `RatedPowerKw` 표기를 각자 유지 — lookup 시 의미 매핑만 필요.)
- **Option 2 (값 보유 Property로 전환) — 권고** — `CycleTimeSec/1/0`(이미 존재, value `xs:integer` unit=s)·`RatedPowerKw/1/0`(이미 존재, value `xs:float` unit=kW) CD를 그대로 쓰고 모델 ProcessNode 선례대로 값 Property화. **신규 CD 0개**, dangling 해소·모델 정렬·시뮬 가용 동시 충족.

### 구체적 제안 (검증 통과)
| # | 항목 | action | 위치 | 내용 |
|---|---|---|---|---|
| 1 | CycleTime→CycleTimeSec | rename | 14개 CycleTime RefElem | Property(`xs:integer`,unit s), semanticId `cd/CycleTimeSec/1/0`(기존), value=실측. 신규 CD 0 |
| 2 | RatedPowerKw 값화 | fix_ref | 14개 RatedPowerKw RefElem | Property(`xs:float`,unit kW), semanticId 유지, value=정격전력. self-ref 제거 |
| 3 | RatedPowerKw CD 중복제거 | other | psm_smt conceptDescriptions | 동일 id ×2 중 1개 삭제 |
| ~~4~~ | ~~Mounter Chips ref 수정~~ **철회** | — | — | value→PCB는 의도된 설계(칩은 PCB의 BOM 부품). 수정 불필요 |
| 5 | 물질흐름 join-key CD 신설(**진짜 신설**) | add_CD | psm_smt conceptDescriptions | PCB·SolderCream·SolderPastedPCB·ChipMountedPCB·ReflowedPCB·GoodPCB·DefectPCB·Chips·Materials (preferredName+definition; dataType는 구조CD라 생략 가능) |
| 6 | 설비공정 자산참조 정렬 | align_asset_id | 14개 설비공정 SMC.semanticId | `/ids/asset/<Fac>/<모델명>`→설비 globalAssetId `/ids/aas/<Fac>/1/0` (대안: 설비 nameplate에 실모델명 채움) |
| 7 | SMTMaterials.MODEL_X 재사용 | align_asset_id | SMTMaterials.MODEL_A/B/C.semanticId | `cd/MODEL_X`→모델 globalAssetId `/ids/asset/MODEL_X/1/0` |
| 8 | n_modules 정렬 | rename | MounterProcess.n_modules | idShort→`NModules`(또는 ModuleCount) + `cd/NModules` 신설 |
| 9 | 구조 컨테이너 CD(저순위) | add_CD | psm_smt conceptDescriptions | SMTProcess/SMTLines/Line_1/Line_2/SMTMaterials |
| 10 | DepType 추가 | add_property | 14개 설비공정 SMC, DepPrev 옆 | Property value='SEQUENCE', semanticId `cd/DepType/1/0`(모델 재사용) |
| 11 | description 동반 갱신 | other | CycleTime/RatedPowerKw SME | Option 2 채택 시 'lookup' 문구→값 보유형으로 |

> 검증 정정(무해): valueType 표기 `xs:int`→실제 `xs:integer`, `xs:double`→실제 `xs:float`. SMTMaterials.PCB는 단일이 아닌 모델별 다중키 체인(14 CD 전부 모델에서 해소).

---

## Part 3 — Models3D SM (IDTA 02026 템플릿) 분석

PDF 명세(IDTA_02026-1-0, 131p) 원문 대조. psm_smt Models3D는 `_apply_3dmodels_smt.py`가 템플릿을 그대로 복사(7설비용 SMC 7복제 + CD 98개 복붙)한 **빈 스켈레톤**(populated value 0개, DigitalFile value=None, contentType=image/png 플레이스홀더). sim/viz 코어(simulation_ver1·path_extractor·cpro_ver1_viz)는 Models3D를 **읽지 않음** → 현재 제거 안전.

### 요소 의미·카디널리티 (Model3D entry 하위, PDF Table 2~4·73~99)
- **File : SMC [1]** (유일 필수 컨테이너) — 모델 파일 실체.
  - FileId : SML **[1]** / FileClassification : SML **[1]** / FileVersion : SML **[0..1]** / ConsumingApplication : SML **[0..1]**.
  - FileVersion entry: Title MLP[1], FileName PROP[1], FileVersionId PROP[1], StatusValue PROP[1], SetDate PROP[1], ProvidingOrganization SMC[1], FileFormat SMC[1], **PreviewFile FILE[1] (MIME image/…, 필수)**, **DigitalFile FILE[0..1] (MIME model/…, 선택)**, SourceApplication SMC[0..1], ExternalFile/BasedOn/RefersTo/Api SML[0..1].
- **Capability : SMC [0..1]** (선택) — 모델 신뢰성/용도(Pos·NegModelPurpose)/수명상태/Origin/Simplification.
- **Geometry : SMC [0..1]** (선택) — 파일 미개봉용 기초 기하: Representation PROP[1], LengthUnit PROP[1], CartBoundingBox SML[0..1], CartRefSystem SML[0..1].

### CartRefSystem 중복 질문 — **중복 아님 (서로 다른 것)**
- **Geometry > CartRefSystem** (SML[0..1], semanticId `…/Geometry/CartRefSystem/1/0`) = **모델/자산 자체의 기준 좌표계(들)**. SML이라 복수 프레임 가능.
- **Geometry > CartBoundingBox > CartRefSystem** (SMC[0..1], semanticId `…/CartBoundingBox/CartRefSystem/1/0`) = **그 바운딩박스의 기준 좌표계**(`CartBoundingVector`가 이 프레임에서 확장). SMC라 단일.
- semanticId·parent·modelType(SML vs SMC)·역할 모두 달라 한쪽이 다른쪽 복사본이 아님. **삭제 대상이 아니라 둘 다 사용** — 좌표계 표현이 Model3D의 목적이므로 모델 프레임·bbox 프레임 모두 의미 있음.

### 제거 제안 (정정 — Model3D 목적 = 좌표계 표현)
**사용자 확정**: Model3D는 설비/제품의 **좌표계 표현**용으로 담음 → **Geometry(좌표·CartRefSystem·CartBoundingBox)가 핵심 보존 대상**, 나머지(File·Capability)도 **필수[1]은 유지**. (앞서 "Geometry 통째 제거"는 뷰어-로딩 전용이라는 잘못된 전제 — 철회.)

**유지(KEEP):**
- **Geometry 전체** — Representation[1]·LengthUnit[1]·CartBoundingBox[0..1]·CartRefSystem[0..1]. 좌표 표현이 목적이므로 핵심.
- **두 CartRefSystem 모두 유지** — Geometry-direct(모델/자산 프레임) + CartBoundingBox-nested(bbox 프레임). 서로 다른 좌표계라 둘 다 사용.
- **File 필수[1]**: FileId[1]·FileClassification[1]·FileVersion[0..1]{ Title[1]·FileName[1]·FileVersionId[1]·StatusValue[1]·SetDate[1]·ProvidingOrganization[1]·FileFormat[1]·**PreviewFile[1]** + **DigitalFile[0..1]**(실제 3D 파일, MIME `model/…`) }. DigitalFile contentType=image/png 플레이스홀더는 실제 3D MIME으로 교정.
- **Capability 유지 시 필수[1]**: PosModelPurpose[1]·Origin[1].

**제거 후보(선택 [0..1], 좌표/파일과 무관한 메타만):**
- File: ConsumingApplication[0..1], FileVersion의 ExternalFile/BasedOn/RefersTo/Api/SourceApplication[0..1].
- Capability(전체 [0..1]): 좌표와 무관 → 통째 제거 가능. 유지 택 시 PosModelPurpose[1]·Origin[1] 필수 + 선택분(NegModelPurpose/EmbeddedInfo/State/ObjectType/Simplification) 제거.

**불변 원칙(PDF p20/p21 확정)**: 부모를 남기면 그 **필수[1] 자식은 삭제 불가**(FileId·FileClassification·PreviewFile 등). **PreviewFile[1] 필수·DigitalFile[0..1] 선택**(원 제안이 반대로 봤던 부분).

### 결론
좌표계 표현이 목적 → **Geometry 보존(두 CartRefSystem 모두)**, File·Capability는 **필수[1] 유지 + 선택 메타만 정리**. 제거 시 해당 SME를 backing하던 Models3D CD만 lockstep 정리(좌표/필수 backing CD는 보존).

---

## Part 2 실행 — SMTProcess 완성 (wip 복사본) + path_extractor join 가정 하 잔여 gap

**적용 위치**: `aas_data/wip/`(원본 6개 json 복사) 중 `ProvisionOfSimulationModel_smt.json`. 원본 미수정. 스크립트: `mod_run/_complete_smtprocess.py`.

**통일 스킴(적용 완료):**
- 설비 식별: 14개 설비공정 SMC `semanticId` → **`/ids/aas/<Fac>/1/0`**(설비 AAS id, key=AssetAdministrationShell). 이름(SLD-120 등) 매칭 안 함 — 모든 설비에 존재하는 안정적 식별자로 통일.
- `CycleTime` → **`CycleTimeSec`**(정준; dangling+표기 동시 해소).
- `RatedPowerKw` 유지(psm 단위접미 관행).
- `DepType='SEQUENCE'` Property 추가(14), `n_modules` → `NModules`(2).
- `SMTMaterials.MODEL_A/B/C` semanticId → 모델 globalAssetId `/ids/asset/MODEL_X/1/0` 재사용.
- CD 17개 신설(자원 PCB·SolderCream·SolderPastedPCB·ChipMountedPCB·ReflowedPCB·GoodPCB·DefectPCB·Chips·Materials, 구조 SMTProcess·SMTLines·Line_1·Line_2·SMTMaterials, 값형 NModules·DepType·DepPrev) + RatedPowerKw 중복 1 제거 → CD 300. SMTProcess CD-type 참조 179개 중 미해소는 모델 BOM PCB part 3개뿐(cross-file 해소).

**"설비에 데이터 있다 + path_extractor가 join" 가정 하 잔여 gap(부족한 점):**
1. **CycleTime semanticId 비균일(최대 gap)**: psm_smt는 정준 `cd/CycleTimeSec`를 쓰나 설비는 ScreenPrinter=`cd/CycleTime`, Mounter=`cd/MountCT`·`ProductionCT`, **Loader/SPI/AOI/Reflow/Unloader는 사이클타임 property 자체가 없음**. → 균일 join 불가. 설비가 `CycleTimeSec`를 노출하거나 path_extractor에 per-설비 매핑 필요.
2. **RatedPower semanticId 불일치**: psm `cd/RatedPowerKw` vs 설비 7개 모두 `cd/RatedPower`. → join 시 `RatedPowerKw↔RatedPower` 매핑 필요(또는 설비가 RatedPowerKw 채택).
3. **설비 값 전부 None**: RatedPower·CycleTime·PowerConsumption 모두 미입력. "데이터 있다 치고"지만 현재 비어 join 해도 흐를 값 없음.
4. **모델번호 placeholder**: `ManufacturerProductType`가 6/7 설비에서 `FM-ABC-1234`(Loader만 `SLD-120`). 식별을 AAS id로 통일했으므로 무해하나, 모델번호 기반 연결은 불가.
5. **PowerConsumption semanticId 버전 drift**: 설비별 `/1/0` vs `/2/0` 혼재 — 정확 semanticId join 시 누락 위험.
6. **path_extractor 추출/조인 계층 부재**: SMTProcess 읽기 → SMC.semanticId(설비 AAS id)로 설비 deref → lookup RefElem의 semanticId와 일치하는 설비 property pull, 이 메서드가 아직 없음(시뮬 파이프라인 후속).
7. **자원/Materials 흐름은 psm_smt-side가 맞음**(설비 비노출). 단 `SMTMaterials.MODEL_X.PCB`는 모델 BOM PCB part를 가리키므로 path_extractor가 모델 파일도 함께 로드해야 해소.

## 산출물
- `mod_run/_audit_all_aas.py` (결정론 감사) → `mod_run/_aas_full_audit.json`
- `mod_run/_audit_psm_smt_diff.py` (psm_smt 델타)
- `mod_run/_wf_aas_analysis.js` (9에이전트 워크플로우) → `mod_run/_wf_result.json` (전체 구조화 결과)
