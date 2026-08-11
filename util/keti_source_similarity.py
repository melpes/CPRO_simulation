"""각 자료가 KETI FAB 설비와 어떻게 닮았는지, 파라미터가 문서 어디에 있는지 적어 둔다.

유사성은 '같은 공정인가' 로 끝내지 않고 어떤 계통이 대응하고 무엇이 다른가까지 적는다.
그래야 Property 를 가져올 때 어디까지 믿을지 판단할 수 있다.

키는 (AAS, 장비명 접두). 장비명 앞의 일련번호는 유사장비가 추가되면 밀리므로 무시한다.
"""

import re

# (AAS, 파일명 접두) → (KETI 설비와의 유사성, 파라미터 위치)
SIMILARITY = {
    # ── 본설비 (KETI 보유) ─────────────────────────────────────────
    ("박막증착장비-PECVD", "26_박막증착장비"): (
        "KETI 본설비 자신. 4개 챔버(PECVD·Sputter·Dry Etcher·Thermal Evaporator)가 한 클러스터",
        "ZEUS 구성 및 성능 — 챔버별로 한 줄씩만 (PECVD : SiO2, Si3N4)"),
    ("유기증착기-PlasmaChamber", "24_유기증착기"): (
        "KETI 본설비 자신. Plasma Treatment·Organic·Metal Chamber + Glove Box 로 구성",
        "ZEUS 구성 및 성능 — System Configuration 항목"),
    ("PEALD", "44_PEALD"): (
        "KETI 본설비 자신. ZEUS·i-Tube 모두 미등록 / 포털 자료 없음",
        "자료 없음"),
    ("현상장비", "43_스핀 트랙 시스템"): (
        "KETI 본설비 자신. 코터·디벨로퍼·핫플레이트·쿨플레이트·로봇이 한 트랙",
        "매뉴얼 PDF — p37 성능(유틸리티·Exhaust Port), p52 Utility Hook-Up, "
        "p80~81 System Specifications(유닛별 사양), p134·p252 부속"),
    ("현상장비", "18_현상장비"): (
        "KETI 본설비. 스핀트랙과 같은 코터/디벨로퍼 트랙 / 2008년 도입분이라 사양 기재 얇음",
        "ZEUS 구성 및 성능"),
    ("현상장비", "34_스핀디벨로퍼"): (
        "KETI 본설비. 단독 스핀 현상기. 트랙의 Developer Unit 에 해당",
        "ZEUS 구성 및 성능 — Spin Motor·Spin Chuck·Bowl·Dispenser·Utility"),
    ("마스크 얼라이너", "42_마스크 얼라이너(8인치)"): (
        "KETI 본설비. Suss Microtec MA8 Gen4, 2026년 등록분이라 사양이 가장 상세",
        "ZEUS 구성 및 성능 — Substrate·Mask size·Contact Mode·Resolution·Alignment Gap·"
        "Align Accuracy(TSA/BSA)·Exposure lamp·Wavelength·Objective"),
    ("마스크 얼라이너", "21_마스크얼라이너"): (
        "KETI 본설비. 코디엠 제작 / 사양이 유닛 나열 위주라 값 적음",
        "ZEUS 구성 및 성능 — 노광기 본체·Mask Spot 냉각·기판 Stage 온조·Ionizer·HEPA·Loader"),
    ("식각/스트립", "19_엣쳐_스트리퍼"): (
        "KETI 본설비. 이름은 '에처/스트리퍼'인데 ZEUS 사양은 E-UV·Spin coater·EBR·Spin Developer 로 "
        "습식 코팅·현상 계통 / 진공 건식식각(박막증착장비 Dry Etcher)과는 다른 장비",
        "ZEUS 구성 및 성능 — 유닛별(E-UV·Spin coater·EBR·Spin Developer)"),
    ("식각/스트립", "35_유기스트리퍼"): (
        "KETI 본설비. PR 제거 전용 습식 라인",
        "ZEUS 구성 및 성능 + 매뉴얼 PDF p15~16 (모듈별 센서 구성)"),
    ("참고", "27_화학 습식 증착(CBD)"): (
        "KETI 본설비. 상압 용액 공정 / 진공 증착 3종과 파라미터 종류가 완전히 다름",
        "ZEUS 구성 및 성능 — CBD 1ea (CdS, ZnS)"),

    # ── 유사장비 ─────────────────────────────────────────────────
    ("박막증착장비-PECVD", "저온 플라즈마 화학기상"): (
        "저온 PECVD 전용기. 도메인은 반도체 레벨로 상이 / 공정 원리 동일. "
        "Main Chamber·Electrodes(평행판 용량결합)·RF Generator 2대·RF Matching·Liquid Source Line 이 "
        "KETI PECVD 챔버 계통과 그대로 대응",
        "ZEUS 구성 및 성능 — 부품별 계층 목록"),
    ("박막증착장비-PECVD", "마이크로파 플라즈마"): (
        "플라즈마 CVD 계열이나 여기 방식이 마이크로파다. 챔버·가스·진공·기판냉각은 공유하지만 "
        "마그네트론·아이솔레이터·3스터브 튜너·양방향 커플러는 RF 방식 KETI 장비에 없는 계통",
        "ZEUS 구성 및 성능 — 1.마이크로파 시스템 / 2.진공시스템 / 3.가스공급"),
    ("박막증착장비-Sputter", "스퍼터 증착기"): (
        "마그네트론 스퍼터. 진공 게이지 제어·시편 회전·자동 압력 제어·캐소드·가스 공급·RF 파워가 "
        "KETI Sputter 챔버와 같은 계통",
        "ZEUS 구성 및 성능 — 유닛별"),
    ("박막증착장비-Sputter", "12인치 스퍼터 시스템"): (
        "스퍼터 증착 전용기. 기판 크기만 상이 / 챔버·셔터·진공·터보펌프·타깃·RF·가스 계통 동일",
        "ZEUS 구성 및 성능 — 항목별 수치"),
    ("박막증착장비-DryEtcher", "유도결합 플라즈마 반응성 이온 식각"): (
        "ICP-RIE. 진공 건식식각 / KETI Dry Etcher 챔버와 같은 공정. "
        "플라즈마 소스·RF/바이어스 전원·챔버 냉각(He 백사이드)·시편 척·가스가 대응",
        "ZEUS 구성 및 성능"),
    ("박막증착장비-DryEtcher", "유도결합플라즈마 식각"): (
        "ICP 식각 / 같은 공정",
        "ZEUS 구성 및 성능"),
    ("박막증착장비-DryEtcher", "반도체 미세 식각 장비"): (
        "진공 ICP 건식식각. 수집한 유사장비 중 가장 상세. "
        "Etch rate·종횡비·Selectivity 같은 공정 성능과 ICP/Bias 전원·챔버 재질·진공펌프 3종·"
        "게이지·MFC 가스종까지 확보",
        "ZEUS 구성 및 성능 — 나.장비 구성 / 다.성능 및 규격(1 장비 성능, 2 상세 규격 가~바)"),
    ("박막증착장비-ThermalEvaporator", "열증착기 (울산과학기술원"): (
        "진공 열증착기 / 둘 다 저항 가열 도가니 방식 + 다원소 화합물 방식 / 공정 동일",
        "ZEUS 구성 및 성능"),
    ("유기증착기-PlasmaChamber", "표면처리기 (전남대"): (
        "플라즈마 표면처리 전용기. KETI Plasma Treatment Chamber 와 기능 거의 동일",
        "ZEUS 구성 및 성능"),
    ("유기증착기-PlasmaChamber", "플라즈마 표면처리기 (충북대"): (
        "ICP 플라즈마 표면처리기. 챔버·RF·가스·진공 계통 그대로 대응",
        "ZEUS 구성 및 성능"),
    ("유기증착기-PlasmaChamber", "8inch 표면나노구조 플라즈마"): (
        "RIE 방식 플라즈마 처리 장치 / 챔버 내경·전극 조립체·가스 샤워헤드·진공 펌핑 공유 / "
        "RIE 라 식각 성격 혼재",
        "ZEUS 구성 및 성능 — 부품별"),
    ("유기증착기-OrganicChamber", "OLED 증착시스템(DT03)"): (
        "선익시스템 Sunicel plus 200 — KETI 유기증착기와 동일 모델. 공정 과정 거의 동일",
        "ZEUS 구성 및 성능 (8줄)"),
    ("유기증착기-OrganicChamber", "유기진공열 증착기"): (
        "유기물 진공 열증착 전용기. Organic Chamber 의 Low Temp. Cell 과 같은 공정",
        "ZEUS 구성 및 성능"),
    ("유기증착기-OrganicChamber", "진공열 증착기 (경상국립대"): (
        "진공 열증착기 / 유기물 전용 여부 원문 미명시 / 보트·진공 계통만 공유",
        "ZEUS 구성 및 성능"),
    ("유기증착기-MetalChamber", "열증착기 및 글로브박스"): (
        "Metal Chamber 와 가장 비슷하다. 열증착 계통(보트·전원·두께 모니터·진공)이 대응. "
        "글로브박스 계통은 12건 구성에 없어 제외했다",
        "ZEUS 구성 및 성능 — 열증착 부분"),
    ("유기증착기-MetalChamber", "열증착기 (울산과학기술원"): (
        "진공 열증착기. Metal Chamber 는 BN Boat 로 금속을 올리는 단순 공정인데 "
        "이 장비는 더 복잡한 공정 / 참고 수준",
        "ZEUS 구성 및 성능"),
    ("PEALD", "플라즈마 강화 원자층 증착 장비"): (
        "씨엔원 6 Atomic Premium System — KETI PEALD 와 동일 제작사·모델. "
        "웨이퍼 대상 장비이나 공정 과정 거의 동일",
        "ZEUS 구성 및 성능 — 웨이퍼 챔버 / 가스 공급 / Process Module"),
    ("PEALD", "KETI성남"): (
        "아이작리서치 iMV-DX4. 분말·웨이퍼 다기능 ALD 라 웨이퍼 보관 챔버까지는 비슷하나 "
        "분말 증착(유동층 반응기)은 KETI PEALD 에 없는 공정",
        "ZEUS 구성 및 성능 — 웨이퍼 챔버 부분만 유효 (분말 챔버는 제외)"),
    ("현상장비", "포토 트랙"): (
        "에스브이에스 MSX1000 — KETI 스핀 트랙과 동일 모델",
        "ZEUS 구성 및 성능"),
    ("현상장비", "12인치 완전자동 트랙시스템"): (
        "에스브이에스 MSX3000. 상위 모델 / 코터·디벨로퍼·베이크·로봇 구성 그대로 대응",
        "ZEUS 구성 및 성능 — 유닛 번호별 (1)~(12)"),
    ("현상장비", "12인치 정렬노광 및 다중공정"): (
        "트랙 계통 대응 / 정렬노광 계통 혼재 / 노광 Property 는 노광 AAS 소관",
        "ZEUS 구성 및 성능 — 트랙 부분만"),
    ("현상장비", "포토레지스트 트랙 시스템"): (
        "에스브이에스 SSP200. 코터·디벨로퍼 트랙",
        "ZEUS 구성 및 성능"),
    ("마스크 얼라이너", "노광기 ((재)철원플라즈마"): (
        "코디엠 MA-1200 — KETI 21번과 동일 제작사. UV 램프 파장·해상도·마스크 홀더 대응",
        "ZEUS 구성 및 성능"),
    ("식각/스트립", "Wet station"): (
        "울텍 AquaChem. 약액 욕조 4종(Developer·Etcher·Striper·BOE)·QDR bath·Hot DI rinse·"
        "Hot air dry 를 한 장비에 보유 / KETI 엣쳐/스트리퍼·유기스트리퍼를 모두 포괄",
        "ZEUS 구성 및 성능 — 본체 구성 / 시스템 구성 / 시스템 성능"),
    ("식각/스트립", "웨이퍼회전건조기"): (
        "세미트로닉스 SD-1505S2. 스핀 건조 계통만 대응 / 식각·현상 계통 없음",
        "ZEUS 구성 및 성능"),
    ("프린팅", "스크린프린터 (한국전자통신연구원"): (
        "Seria 스크린프린터. 스퀴지·스크린·정렬 계통 대응",
        "ZEUS 구성 및 성능"),
    ("프린팅", "재료프린터 (한국표준과학연구원"): (
        "Fuji Film DMP-2831 — KETI 잉크젯(lab)과 동일 모델",
        "ZEUS 구성 및 성능"),
    ("프린팅", "머티리얼 프린터 (서강대"): (
        "DMP-2831 동일 모델", "ZEUS 구성 및 성능"),
    ("프린팅", "인쇄전자용 프린터 (선문대"): (
        "DMP-2831 동일 모델", "ZEUS 구성 및 성능"),

    # ── KOSMO 참고자료 ────────────────────────────────────────────
    ("유기증착기-PlasmaChamber", "KOSMO 표면처리기 AAS"): (
        "플라즈마 표면처리기의 완성된 AAS. KETI Plasma Treatment Chamber 와 기능이 같아 "
        "OperationData Property(챔버압력·RF·가스·펌프·도어) 그대로 사용 가능 / "
        "TechnicalData 는 원심 바스켓형(BasketDiameter·SupportedSpinSpeed)이라 무관",
        "AASX 내부 OperationData 서브모델 (TechnicalData 는 제외)"),
    ("박막증착장비-DryEtcher", "KOSMO 반도체회로 에칭장비 AAS"): (
        "진공 건식식각 장비의 완성된 AAS / KETI Dry Etcher 챔버와 공정 동일 / "
        "EtchingChamber·ESC·RF발생기·가스샤워헤드·MFC·진공펌프·게이트밸브·스크러버 계통 대응 / "
        "생산관리(WorkOrder·ProductionPlan)·에너지 계통은 다른 유사장비로 대체 가능해 제외",
        "AASX 내부 TechnicalData + OperationalData (생산관리 계통 제외)"),
    ("박막증착장비-DryEtcher", "KOSMO 반도체회로 에칭장비 활용 가이드"): (
        "Property 선별의 근거 문서. 2-(나) '반도체 에칭 장비 개요' 가 플라즈마 건식식각 관리 데이터를 "
        "명시 — 플라즈마 균일도(RF Power·MFC·APC), 식각 종점(OES), 챔버 벽 상태, ESC 온도",
        "2. 참조모델 대상장비 개요 → 나. 반도체 에칭 장비 개요 / 다. 최적 운영 관점의 4대 핵심 요소 / 라. 장비 동작 단계"),
    ("CBD", "KOSMO 전해도금조 AAS"): (
        "용액 욕조 침지까지는 CBD 와 동일 / 코팅 방식 상이 — "
        "전해도금조는 전기 도금 / CBD 는 화학반응 석출 / "
        "탱크·순환·히터·필터·배기 등 설비 공통 계통만 사용 / "
        "전기도금 공정제어(Currentdensity·DCVoltage·DCCurrent·정류기)는 CBD 에 채울 값 없어 제외",
        "AASX 내부 TechnicalData + OperationalData 중 설비 계통만"),

    # ── 프린팅 본설비 6대 (역할이 같아 하나의 AAS 로 병합) ────────────
    ("프린팅", "20_스크린프린터"): (
        "KETI 본설비. 스크린 인쇄 — 스퀴지·스크린 프레임·정렬 계통",
        "ZEUS 구성 및 성능"),
    ("프린팅", "09_잉크젯 프린터 for PLED #1"): (
        "KETI 본설비 / 잉크젯 / 프린팅 6대는 역할 동일 → 하나의 AAS 로 병합 / 파라미터는 합집합",
        "ZEUS 구성 및 성능 — Print Head 계통"),
    ("프린팅", "13_잉크젯 프린터 for PLED #2"): (
        "KETI 본설비. 잉크젯 (#1 과 같은 계열)",
        "ZEUS 구성 및 성능 — Print Head 계통"),
    ("프린팅", "23_잉크젯 프린터(lab)"): (
        "KETI 본설비. Fuji Film DMP-2831 — 타 기관에 동일 모델이 3대 있어 사양 보완이 가장 쉽다",
        "ZEUS 구성 및 성능"),
    ("프린팅", "30_잉크젯프린터(lab #2)"): (
        "KETI 본설비. 잉크젯 lab 계열. 사양 기재가 가장 얇다",
        "ZEUS 구성 및 성능"),
    ("프린팅", "31_리버스 옵셋 프린터"): (
        "KETI 본설비. 블랭킷 전사 방식이라 스크린·잉크젯과 인쇄 원리가 다르지만 "
        "기판·정렬·인쇄 영역 계통 공유",
        "ZEUS 구성 및 성능"),

    # ── 동일 모델·계열이나 사양 기재가 얇은 유사장비 ────────────────
    ("유기증착기-OrganicChamber", "유기 태양전지용 증착설비"): (
        "선익시스템 Sunicel plus 200 — KETI 유기증착기와 동일 모델. 다만 ZEUS 사양 기재가 6줄로 얇다",
        "ZEUS 구성 및 성능 (6줄)"),
    ("유기증착기-OrganicChamber", "OLED 증착장비(OLED Evaporation"): (
        "선익시스템 Sunicel plus 200 동일 모델. 사양 3줄",
        "ZEUS 구성 및 성능 (3줄)"),
    ("유기증착기-OrganicChamber", "OLED 증착 장비 (한국과학기술원"): (
        "선익시스템 Sunicel plus 100 — 동일 계열 하위 모델. 사양 4줄",
        "ZEUS 구성 및 성능 (4줄)"),
    ("PEALD", "플라즈마 원자층 증착기 (씨엔원"): (
        "씨엔원 Atomic Premium — KETI PEALD 와 동일 제작사 계열",
        "ZEUS 구성 및 성능 (14줄)"),
    ("PEALD", "원자층증착기 (씨엔원"): (
        "씨엔원 Atomic Premium 계열. 사양 8줄",
        "ZEUS 구성 및 성능 (8줄)"),
    ("현상장비", "[FL-TR"): (
        "에스브이에스 MSX1000 — KETI 스핀 트랙과 동일 모델. 기관 내 트랙 I~IV 로 분리 등록",
        "ZEUS 구성 및 성능"),

    # ── 제외 등급 (사양이 없거나 계통이 겹침) ──────────────────────
    ("박막증착장비-PECVD", "유도결합형 플라즈마 화학기상"): (
        "ICP-CVD 로 공정은 가까우나 ZEUS 특성이 2줄뿐이라 Property 도출 불가",
        "자료 없음 (특성 2줄)"),
    ("박막증착장비-Sputter", "마그네트론 스퍼터"): (
        "마그네트론 스퍼터로 공정은 같으나 값이 전부 수량(Process Chamber 1set, Sputter Gun 3set) 이라 "
        "공정 파라미터 없음 / 같은 Property 를 강원대·차세대융합 장비가 값과 함께 보유",
        "해당 없음 (구성 수량만)"),
    ("박막증착장비-Sputter", "스퍼터 (한국생산기술연구원"): (
        "ZEUS 특성 0줄", "자료 없음"),
    ("박막증착장비-ThermalEvaporator", "전자빔 증착기"): (
        "전자빔 가열 방식 / KETI 저항가열 도가니와 상이 / ZEUS 특성 2줄",
        "자료 없음 (특성 2줄)"),
    ("유기증착기-OrganicChamber", "유기 태양전지용 증착설비 (한국생산기술"): (
        "선익 동일 모델이나 ZEUS 특성 2줄", "자료 없음 (특성 2줄)"),
    ("유기증착기-OrganicChamber", "유기증착기 (한국생산기술"): (
        "선익 동일 모델이나 ZEUS 특성 2줄", "자료 없음 (특성 2줄)"),
    ("PEALD", "원자층 증착 장비"): (
        "씨엔원 계열이나 ZEUS 특성 0줄", "자료 없음"),
    ("현상장비", "감광액 도포기"): (
        "에스브이에스 MSX2000 상위 모델이나 ZEUS 특성 2줄", "자료 없음 (특성 2줄)"),
    ("마스크 얼라이너", "노광기 (한국생산기술연구원"): (
        "Suss Microtec MA8 동일 계열이나 ZEUS 특성 2줄", "자료 없음 (특성 2줄)"),
    ("식각/스트립", "플라즈마 애싱 시스템"): (
        "플라즈마 건식 PR 제거. 진공 챔버·샤워헤드·기판척·RF 발생기·진공펌프 계통이 "
        "박막증착장비 Dry Etcher 와 겹친다. 식각·스트립은 습식(비진공) 라인이라 제외했다",
        "해당 없음 (Dry Etcher 로 대체)"),

    # ── KOSMO 부속 문서 ──────────────────────────────────────────
    ("유기증착기-PlasmaChamber", "KOSMO 표면처리기 활용 가이드"): (
        "표면처리기 AAS 를 만든 절차와 데이터 정의를 담은 문서. Property 보다 작성 방법 참고용",
        "AAS 개념·구성요소·작성 절차 장"),
    ("유기증착기-PlasmaChamber", "KOSMO 표면처리기 사전검증보고서"): (
        "표면처리기 AAS 검증 결과 / Property 타당성 확인용", "전체"),
    ("유기증착기-PlasmaChamber", "KOSMO 표면처리기 체크리스트"): (
        "AAS 작성 점검표 / 우리 AAS 작성 시 동일 항목 확인용", "전체"),
    ("박막증착장비-DryEtcher", "KOSMO 반도체회로 에칭장비 사전검증보고서"): (
        "에칭장비 AAS 의 검증 결과", "전체"),
    ("박막증착장비-DryEtcher", "KOSMO 반도체회로 에칭장비 체크리스트"): (
        "AAS 작성 점검표", "전체"),
    ("CBD", "KOSMO 전해도금조 활용 가이드"): (
        "전해도금조 AAS 작성 가이드. 용액 욕조 설비의 데이터 정의 참고", "전체"),
    ("CBD", "KOSMO 전해도금조 사전검증보고서"): ("전해도금조 AAS 검증 결과", "전체"),
    ("CBD", "KOSMO 전해도금조 체크리스트"): ("AAS 작성 점검표", "전체"),
}



def _bare(s):
    return re.sub(r"^\d{2}_", "", (s or "").strip())


def similarity_of(aas, name):
    """(유사성, 파라미터 위치) 를 찾는다. 없으면 빈 문자열."""
    n = _bare(name)
    for (a, pre), val in SIMILARITY.items():
        if a == aas and n.startswith(_bare(pre)):
            return val
    # 분류명이 '참고' 인 CBD 본설비처럼 AAS 키가 어긋나는 경우를 위한 2차 시도
    for (a, pre), val in SIMILARITY.items():
        if n.startswith(_bare(pre)):
            return val
    return ("", "")
