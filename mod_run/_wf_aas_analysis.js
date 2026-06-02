export const meta = {
  name: 'aas-audit-analysis',
  description: 'AAS 3파트: Part-1 감사 적대검증 / Part-2 SMTProcess 참조해소+일관성+제안 / Part-3 Models3D PDF분석+제거제안',
  phases: [
    { title: 'Verify-Part1' },
    { title: 'Part2-SMTProcess' },
    { title: 'Part3-Models3D' },
  ],
}

const AAS = 'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/aas_data/'
const SMT = 'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/SMT/'
const AUDIT = 'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/mod_run/_aas_full_audit.json'
const PDF = AAS + 'IDTA_02026-1-0_Submodel_ProvisionOf3DModels.pdf'

const CTX = `
[대상 파일]
- JSON(6): ${AAS}{MODEL_A,MODEL_B,MODEL_C,WorkstationWorkerMatchingDataAAS,ProvisionOfSimulationModel,ProvisionOfSimulationModel_smt}.json
- SMT 설비 7 (.aasx, 내부 XML aasx/<Fac>/<Fac>.aas.xml): ${SMT}{1_Loader,2_SPI,3_ScreenPrinter,4_Mounter,5_AOI,6_Reflow,7_Unloader}.aasx
- Part-1 결정론 감사 결과 JSON: ${AUDIT}

[psm_smt SMTProcess 구조 — SimulationModels.submodels[0].submodelElements[0](SimulationModel).value[7]]
SMTProcess(SMC)
 ├ SMTLines(SMC)
 │  ├ Line_1(SMC), Line_2(SMC)  ← 각 7개 설비 공정 SMC
 │  │   설비공정 SMC idShort: LoaderProcess/ScreenPrinterProcess/SPIProcess/MounterProcess/ReflowProcess/UnloaderProcess/AOIProcess
 │  │   각 설비공정 SMC 의 semanticId = 자산URL 'https://www.smart-factory.kr/ids/asset/<Fac>/<모델명>'
 │  │     (Loader/SLD-120, ScreenPrinter/HS-520S, SPI/KY-8030, Mounter/M-Series, Reflow/GT-R8, Unloader/SUD-120, AOI/BF-Comet-c)
 │  │   자식: DepPrev(Property,xs:string,선행공정idShort) / CycleTime(ReferenceElement→cd/CycleTime) /
 │  │         RatedPowerKw(ReferenceElement→cd/RatedPowerKw) / n_modules(Property,xs:int — Mounter만) /
 │  │         Materials(Operation; input/outputVariables 안의 ReferenceElement 들이 자원 CD 참조)
 │  │   Materials 물질흐름: Loader(PCB→PCB) ScreenPrinter(PCB+SolderCream→SolderPastedPCB) SPI(SolderPastedPCB→통과)
 │  │     Mounter(SolderPastedPCB+Chips→ChipMountedPCB) Reflow(ChipMountedPCB→ReflowedPCB)
 │  │     Unloader(ReflowedPCB→통과) AOI(ReflowedPCB→GoodPCB+DefectPCB)
 │  └ ...
 └ SMTMaterials(SMC) → MODEL_A/MODEL_B/MODEL_C(SMC) → PCB(ReferenceElement→ 각 모델 PCB part)

[이미 확인된 참조-정의 진단 (반드시 소스에서 재확인할 것 — 신뢰 말고 검증)]
- cd/CycleTime/1/0 : ScreenPrinter 설비에만 정의(우연). 모델/psm 은 cd/CycleTimeSec/1/0 사용 → 네이밍 불일치 의심.
- cd/RatedPowerKw/1/0 : MODEL_A,MODEL_B,psm,psm_smt 에 정의(psm/psm_smt 는 중복 ×2). 그러나 7개 설비는 cd/RatedPower/1/0 사용 → 불일치.
- cd/DepPrev/1/0 : MODEL_A/B/C 정의. cd/DepNext/1/0 : 어디에도 없음.
- 다음은 어디에도 정의 안 됨(자기참조 제외 진짜 누락): Materials, PCB, SolderPastedPCB, ReflowedPCB, ChipMountedPCB,
  SolderCream, Chips, GoodPCB, DefectPCB, n_modules, SMTProcess, SMTLines, Line_1, Line_2, SMTMaterials, MODEL_A, MODEL_B, MODEL_C.
- 자산참조 불일치: psm_smt 는 '/ids/asset/<Fac>/<모델명>' 를 가리키나 설비 globalAssetId 는 '/ids/aas/<Fac>/1/0'. 설비 안에 모델명(SLD-120 등)이 어디에 표현돼 있는지 확인 필요.
- 설비들은 CycleTime/RatedPower/PowerConsumption/Energy/TechnicalData/Nameplate 등 풍부한 데이터 보유 → psm_smt 가 필요로 하는 값이 이미 다른 형태로 존재할 수 있음.

모든 파일 접근은 python(json/zipfile+xml.etree) 또는 Read 로. 결론은 반드시 소스 근거와 함께.
`

// ---------- 스키마 ----------
const VERIFY_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    scope: { type: 'string' },
    verdict: { type: 'string', enum: ['confirmed', 'partly_wrong', 'wrong'] },
    parser_bugs: { type: 'array', items: { type: 'string' } },
    false_positives: { type: 'array', items: { type: 'string' } },
    missed_findings: { type: 'array', items: { type: 'string' } },
    corrected_counts: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['scope', 'verdict', 'parser_bugs', 'false_positives', 'missed_findings', 'notes'],
}

const PART2_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    refs: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          target: { type: 'string' },
          usedAt: { type: 'string' },
          status: { type: 'string', enum: ['resolves_self', 'resolves_psm_smt', 'resolves_facility', 'resolves_model', 'missing_everywhere'] },
          resolvesIn: { type: 'string' },
          issue: { type: 'string' },
        },
        required: ['target', 'usedAt', 'status', 'issue'],
      },
    },
    consistency_issues: { type: 'array', items: { type: 'string' } },
    proposals: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          item: { type: 'string' },
          action: { type: 'string', enum: ['add_CD', 'rename', 'fix_ref', 'add_property', 'align_asset_id', 'other'] },
          location: { type: 'string' },
          content: { type: 'string' },
          rationale: { type: 'string' },
        },
        required: ['item', 'action', 'location', 'content', 'rationale'],
      },
    },
    summary: { type: 'string' },
  },
  required: ['refs', 'consistency_issues', 'proposals', 'summary'],
}

const PART3_CATALOG_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    pdf_pages_read: { type: 'string' },
    elements: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string' },
          modelType: { type: 'string' },
          cardinality: { type: 'string' },
          meaning: { type: 'string' },
          usage: { type: 'string' },
          spec_ref: { type: 'string' },
        },
        required: ['path', 'meaning', 'usage'],
      },
    },
    cartRefSystem_explained: { type: 'string' },
  },
  required: ['pdf_pages_read', 'elements', 'cartRefSystem_explained'],
}

const PART3_PROPOSAL_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    keep: { type: 'array', items: { type: 'string' } },
    remove: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { path: { type: 'string' }, reason: { type: 'string' } }, required: ['path', 'reason'] } },
    cartRefSystem_resolution: { type: 'string' },
    minimal_structure: { type: 'string' },
    summary: { type: 'string' },
  },
  required: ['keep', 'remove', 'cartRefSystem_resolution', 'minimal_structure', 'summary'],
}

// ================= 실행 =================
const [verifyPart1, part2, part3] = await parallel([

  // ---------- Stream A: Part-1 감사 적대적 검증 ----------
  async () => {
    const checks = [
      { label: 'verify:xml-facilities', prompt: `SMT 설비 7개(.aasx XML)에 대한 Part-1 감사(${AUDIT})의 정확성을 적대적으로 검증하라. 감사 스크립트는 ${'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/mod_run/_audit_all_aas.py'} (XML→JSON-shape 변환 후 검사). 직접 python+zipfile+xml.etree 로 최소 3개 설비(Mounter, AOI, Loader)의 raw XML 을 독립 파싱해 감사가 보고한 수치(idShort누락/CamelCase위반/description누락/semanticId누락/dangling/CD불완전/중복CD id)와 대조하라. 특히 XML 파서 버그를 노려라: 네임스페이스 처리, langString 빈 텍스트 판정, SML 자식 판정, Operation/Entity 재귀, dataType 텍스트 추출, 중복 CD id 가 dedup 되어 누락되지 않았는지. 틀린 수치/누락/오탐을 구체적으로.` },
      { label: 'verify:json-files', prompt: `JSON 6개(MODEL_A/B/C, wwm, psm, psm_smt)에 대한 Part-1 감사(${AUDIT})의 정확성을 적대적으로 검증하라. 직접 python 으로 raw json 을 파싱해 dangling CD(글로벌 union 기준)/CD불완전(idShort·preferredName·dataType·definition)/중복 CD id/semanticId누락/description누락 수치를 재계산해 대조. CamelCase 위반 분류(space/underscore/special/startsDigit/startsLower)가 타당한지, SML 자식이 제대로 제외됐는지 확인. psm_smt 의 SMTProcess Operation 안 ReferenceElement 들이 빠짐없이 순회됐는지(이전에 Operation 재귀 누락 버그가 있었음) 반드시 확인.` },
      { label: 'verify:logic', prompt: `Part-1 감사 스크립트(${'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/mod_run/_audit_all_aas.py'})의 판정 로직 자체를 코드리뷰하라. (1) dangling 판정에서 비-CD 참조(ModelReference→Submodel, Qualifier)를 제대로 제외하는가. (2) CD 불완전 기준(preferredName/dataType/definition)이 구조용 CD(SMC를 가리키는 CD는 dataType 없음이 정상)에 과탐하지 않는가 — dataType 누락을 hard 로 볼지 soft 로 볼지 판단 포함. (3) 글로벌 union 기준 dangling 이 적절한가. (4) idShort/CamelCase 규칙 정의가 사용자 의도(SML 하위 제외)에 맞는가. 개선/수정점 제시.` },
    ]
    return await parallel(checks.map(c => () => agent(`${CTX}\n\n${c.prompt}`, { label: c.label, phase: 'Verify-Part1', schema: VERIFY_SCHEMA })))
  },

  // ---------- Stream B: Part-2 SMTProcess 참조 해소 + 일관성 + 제안 ----------
  async () => {
    const enumerate = await agent(`${CTX}\n\n[Part-2 1단계: 참조 전수 해소]
psm_smt(${AAS}ProvisionOfSimulationModel_smt.json) 의 SMTProcess 서브트리 전체를 python 으로 순회하며, 등장하는 모든 참조(각 설비공정 SMC 의 semanticId=자산URL, 각 ReferenceElement 의 semanticId 와 value, Operation input/output 변수 안 ReferenceElement, Property 의 semanticId)를 전수 추출하라. 각 참조 target 마다: 자기 자신을 가리키는 trivial self-reference 인지 구분하고, self 가 아니면 그 target 이 (a)psm_smt 자체 (b)다른 psm/모델 json (c)7개 설비 aas (d)어디에도 없음 중 어디서 해소되는지 CD id / 자산 id 매칭으로 판정하라. 7개 설비 aasx 의 conceptDescriptions 와 assetInformation.globalAssetId, 그리고 설비 내부에 '모델명(SLD-120 등)'이 어떤 SME 로 표현돼 있는지도 grep 으로 확인하라. refs 배열로 반환.`,
      { label: 'part2:enumerate', phase: 'Part2-SMTProcess', schema: PART2_SCHEMA })

    return await pipeline([enumerate],
      async (enr) => {
        const consistency = await agent(`${CTX}\n\n[Part-2 2단계: 일관성 분석 + 구체적 제안]
1단계 참조해소 결과:\n${JSON.stringify(enr, null, 1).slice(0, 9000)}\n\n
이를 바탕으로: (A) 네이밍/구조 일관성 문제를 전부 적시하라 — 예: psm_smt 'CycleTime' vs 모델/psm 'CycleTimeSec', psm_smt 'RatedPowerKw' vs 설비 'RatedPower', 자산 semanticId(/ids/asset/<Fac>/<모델명>) vs 설비 globalAssetId(/ids/aas/<Fac>/1/0) 불일치, 단위/valueType, ReferenceElement 의 value 가 자기 CD 를 가리키는 placeholder 패턴, MounterProcess 의 Chips 입력이 value=PCB 로 잘못 연결된 것 등. (B) 각 누락/불일치마다 **구체적 제안**: action(add_CD/rename/fix_ref/add_property/align_asset_id), location(정확한 파일·SME 경로·삽입 위치), content(추가/변경할 CD 면 idShort·preferredName·dataType·definition, 이름 변경이면 before→after), rationale. 모델/psm/설비에 이미 존재하는 정의를 최대한 재사용하는 방향으로(중복 CD 신설 지양). proposals 배열로.`,
          { label: 'part2:propose', phase: 'Part2-SMTProcess', schema: PART2_SCHEMA })
        return { enumerate: enr, propose: consistency }
      },
      async (both) => {
        const verdict = await agent(`${CTX}\n\n[Part-2 3단계: 제안 적대적 검증]
다음 참조해소+제안을 소스에서 적대적으로 검증하라. 각 proposal 의 location 이 실제 존재하는지, rename 대상(예: CycleTimeSec, RatedPower)이 실제로 그 파일에 그 idShort/id 로 존재하는지, status 판정(특히 'missing_everywhere' 와 'resolves_facility')이 맞는지 python 으로 일일이 확인하라. 틀린 제안·잘못된 해소판정·놓친 불일치를 지적하고, 검증 통과한 최종 권고를 정리하라.\n\n참조해소:\n${JSON.stringify(both.enumerate).slice(0, 5000)}\n\n제안:\n${JSON.stringify(both.propose).slice(0, 7000)}`,
          { label: 'part2:verify', phase: 'Part2-SMTProcess', schema: VERIFY_SCHEMA })
        return { ...both, verify: verdict }
      },
    ).then(r => r[0])
  },

  // ---------- Stream C: Part-3 Models3D PDF 분석 ----------
  async () => {
    const catalog = await agent(`${CTX}\n\n[Part-3 1단계: PDF 기반 요소 카탈로그]
IDTA 02026 ProvisionOf3DModels Submodel 명세 PDF 를 Read 도구(pages 파라미터)로 체계적으로 읽어라: ${PDF}. 먼저 페이지 수/목차를 파악한 뒤, Submodel(Models3D) 의 SML(Model3D) 및 그 하위 File / Capability(PosModelPurpose/NegModelPurpose/EmbeddedInfo/State/ObjectType/Origin/Simplification) / Geometry(Representation/LengthUnit/CartBoundingBox/CartRefSystem/CartOffsetVector/NormOrientationVector/CartBoundingVector) 의 각 요소에 대해 의미·역할·사용법·cardinality(0..1, 1, 0..*)를 spec 근거(페이지/표)와 함께 정리하라. 특히 CartRefSystem 이 (i)Geometry 직속과 (ii)Geometry>CartBoundingBox>SMC 하위 두 곳에 나오는데, 명세상 각각 무엇을 정의하는지(모델 좌표계 vs 바운딩박스 좌표계), 둘의 관계/중복 여부를 명확히 설명하라. elements 배열 + cartRefSystem_explained 로 반환.`,
      { label: 'part3:pdf-catalog', phase: 'Part3-Models3D', schema: PART3_CATALOG_SCHEMA })

    return await pipeline([catalog],
      async (cat) => {
        const proposal = await agent(`${CTX}\n\n[Part-3 2단계: 제거 제안 + CartRefSystem 해소]
PDF 카탈로그:\n${JSON.stringify(cat, null, 1).slice(0, 11000)}\n\n
psm_smt 의 Models3D SM 은 IDTA 템플릿을 일괄 복사한 것이며(7개 설비용 SMC 복제, 하위는 템플릿 그대로), 현재 psm 의 기능은 'SMT 공정 시뮬레이션 + 시각화'다 — 3D 모델은 설비/제품의 시각화(뷰어 로딩)에 쓰일 뿐 기하 연산(충돌·정밀좌표)은 하지 않을 가능성이 높다. psm_smt 의 실제 Models3D 구조를 python 으로 확인한 뒤: (A) 현 psm 기능 대비 **불필요한 요소 제거 제안** — 어떤 SMC/Property/SML 을 지워도 되는지 path 와 이유. (예: ConsumingApplication, SourceApplication, ExternalFile/Api, FileClassification, Capability 의 Simplification, Geometry 의 상세 좌표계 등이 시각화에 불필요한지) (B) **CartRefSystem 중복 해소**: Geometry 직속 CartRefSystem 과 CartBoundingBox 하위 CartRefSystem 중 시각화 목적상 무엇을 남기고 무엇을 지울지, 혹은 둘 다 필요한지 결론. (C) 최소 구조(파일참조+필수 메타) 제안. keep/remove/cartRefSystem_resolution/minimal_structure 로.`,
          { label: 'part3:removal', phase: 'Part3-Models3D', schema: PART3_PROPOSAL_SCHEMA })
        return { catalog: cat, proposal }
      },
      async (both) => {
        const verdict = await agent(`${CTX}\n\n[Part-3 3단계: PDF 대조 검증]
다음 Models3D 분석/제거제안을 PDF(${PDF}) 원문과 적대적으로 대조하라. 각 요소의 의미·cardinality 설명이 명세와 맞는지, CartRefSystem 중복 해소 결론이 명세 정의(모델 좌표계 vs bbox 좌표계, mandatory 여부)와 모순되지 않는지, '제거 가능' 판정이 mandatory(1 또는 1..*) 요소를 잘못 지우자고 하지 않는지 페이지 근거로 확인하라. 틀린 해석·위험한 제거제안을 지적.\n\n카탈로그:\n${JSON.stringify(both.catalog).slice(0, 5000)}\n\n제안:\n${JSON.stringify(both.proposal).slice(0, 6000)}`,
          { label: 'part3:verify', phase: 'Part3-Models3D', schema: VERIFY_SCHEMA })
        return { ...both, verify: verdict }
      },
    ).then(r => r[0])
  },
])

return { verifyPart1, part2, part3 }
