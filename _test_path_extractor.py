# -*- coding: utf-8 -*-
"""path_extractor.load_aas 동작 검증 스크립트.

세 모델(A/B/C) 모두에 대해:
  1) load_aas 가 예외 없이 끝나는가
  2) 각 Submodel(ManufacturingProcess / WWM / SkillLevelType / HierarchicalStructures) 이 비어있지 않은가
  3) ProcessNode 의 핵심 필드가 그럴듯한 값을 가지는가
  4) group_to_workstation 매핑이 ManufacturingProcess 의 GroupIdShort 들을 모두 커버하는가
  5) ProcessNode.WorkstationId 가 WorkstationWorkerMatchingData 의 키 안에 존재하는가
  6) DepPrev 에 적힌 선행공정이 모두 ManufacturingProcess 키 안에 있는가 (orphan 검사)
  7) HierarchicalStructures.PcbEntry 의 SMT 컴포넌트 item_code 가 IRI URL 이 아니라 토큰화돼있는지
     (Re.value.keys 의 raw URL 이 그대로 들어가는 버그가 있는지 확인)
  8) BomItem.item_code 도 IRI URL 형태가 아닌지
  9) WorkstationData.SkillLevel 이 SkillLevelType 의 rank 값 안에 들어있는지
 10) schedule 이 채워져있는지
"""
import json, os, sys, tempfile, traceback
from collections import Counter
from path_extractor import load_aas

PKG = r'C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package'
WWM_PATH = os.path.join(PKG, 'WorkstationWorkerMatchingDataAAS.json')

MODELS = [
    ('MODEL_A', os.path.join(PKG, 'MODEL_A.json')),
    ('MODEL_C', os.path.join(PKG, 'MODEL_C.json')),
]


def _merged_json(model_path: str) -> str:
    """model JSON + WWM JSON 의 submodels 를 합친 임시 JSON 파일을 만들어 경로를 돌려준다.
    path_extractor.load_aas 는 한 파일만 받으므로 병합본으로 검증한다."""
    a = json.load(open(model_path, 'r', encoding='utf-8'))
    b = json.load(open(WWM_PATH,    'r', encoding='utf-8'))
    a['submodels'] = (a.get('submodels') or []) + (b.get('submodels') or [])
    fd, tmp = tempfile.mkstemp(prefix='aas_merged_', suffix='.json')
    os.close(fd)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(a, f, ensure_ascii=False)
    return tmp


def looks_like_iri(s: str) -> bool:
    return s.startswith('http://') or s.startswith('https://') or '/' in s


def check_model(model_id: str, path: str) -> int:
    print('=' * 78)
    print(f'  {model_id}  ({path})')
    print('=' * 78)

    fail = 0
    merged = _merged_json(path)
    try:
        m = load_aas(model_id, merged)
    except Exception as e:
        print(f'[FAIL] load_aas raised: {type(e).__name__}: {e}')
        traceback.print_exc()
        return 1
    finally:
        try: os.remove(merged)
        except OSError: pass

    # ── 1) 비어있지 않음
    print(f'  ManufacturingProcess          : {len(m.ManufacturingProcess):3d} processes')
    print(f'  WorkstationWorkerMatchingData : {len(m.WorkstationWorkerMatchingData):3d} workstations')
    print(f'  SkillLevelType                : {len(m.SkillLevelType):3d} levels')
    print(f'  HierarchicalStructures.pcb    : {len(m.HierarchicalStructures.pcb_entries):3d} PCB entries')
    print(f'  HierarchicalStructures.parts  : {len(m.HierarchicalStructures.assembly_parts):3d} assembly parts')
    print(f'  group_to_workstation          : {len(m.group_to_workstation):3d} mappings')
    print(f'  schedule                      : {m.schedule}')

    if not m.ManufacturingProcess:
        print('[FAIL] ManufacturingProcess empty'); fail += 1
    if not m.WorkstationWorkerMatchingData:
        print('[FAIL] WorkstationWorkerMatchingData empty'); fail += 1
    if not m.SkillLevelType:
        print('[FAIL] SkillLevelType empty'); fail += 1

    # ── 2) ProcessNode 핵심필드 sanity
    bad_ct = [p.ProcessCode for p in m.ManufacturingProcess.values() if p.CycleTimeSec <= 0]
    if bad_ct:
        print(f'[WARN] CycleTimeSec<=0 : {bad_ct[:5]}{"..." if len(bad_ct)>5 else ""}')

    bad_dr = [p.ProcessCode for p in m.ManufacturingProcess.values()
              if not (0.0 <= p.DefectRate <= 1.0)]
    if bad_dr:
        print(f'[WARN] DefectRate out of [0,1] : {bad_dr[:5]}')

    dep_types = Counter(p.DepType for p in m.ManufacturingProcess.values())
    print(f'  DepType distribution          : {dict(dep_types)}')

    # ── 3) group_to_workstation 커버리지
    groups_in_process = {p.GroupIdShort for p in m.ManufacturingProcess.values()}
    uncovered = groups_in_process - set(m.group_to_workstation.keys())
    if uncovered:
        print(f'[FAIL] groups without workstation : {uncovered}'); fail += 1

    # ── 4) ProcessNode.WorkstationId ∈ WWM keys
    ws_keys = set(m.WorkstationWorkerMatchingData.keys())
    bad_ws = [(p.ProcessCode, p.WorkstationId)
              for p in m.ManufacturingProcess.values()
              if p.WorkstationId and p.WorkstationId not in ws_keys]
    if bad_ws:
        print(f'[FAIL] ProcessNode.WorkstationId not in WWM : {bad_ws[:5]}'); fail += 1

    # ── 5) DepPrev orphan
    proc_keys = set(m.ManufacturingProcess.keys())
    orphans = []
    for p in m.ManufacturingProcess.values():
        for prev in p.DepPrev:
            if prev not in proc_keys:
                orphans.append((p.ProcessCode, prev))
    if orphans:
        print(f'[WARN] DepPrev orphan refs ({len(orphans)}) : {orphans[:5]}')

    # ── 6) BomItem.item_code 토큰화
    iri_bom = []
    for p in m.ManufacturingProcess.values():
        for b in p.InputBOM:
            if looks_like_iri(b.item_code):
                iri_bom.append((p.ProcessCode, b.item_code))
    if iri_bom:
        print(f'[FAIL] BomItem.item_code looks like IRI ({len(iri_bom)}) : {iri_bom[:3]}'); fail += 1

    # ── 7) HierarchicalStructures.SmtComponent.item_code
    iri_smt = []
    for pcb in m.HierarchicalStructures.pcb_entries.values():
        for c in pcb.components:
            if looks_like_iri(c.item_code):
                iri_smt.append((pcb.idShort, c.item_code))
    if iri_smt:
        print(f'[WARN] SmtComponent.item_code looks like IRI ({len(iri_smt)}) : {iri_smt[:3]}')

    # ── 8) WorkstationData.SkillLevel ∈ SkillLevelType.rank
    rank_set = {sl.rank for sl in m.SkillLevelType.values()}
    bad_skill = [(w.WorkstationId, w.SkillLevel)
                 for w in m.WorkstationWorkerMatchingData.values()
                 if w.SkillLevel not in rank_set]
    if bad_skill:
        print(f'[WARN] WorkstationData.SkillLevel not in known ranks : {bad_skill}')

    # ── 9) schedule
    if not m.schedule:
        print('[FAIL] schedule empty'); fail += 1
    else:
        s = m.schedule
        if not (s.get('WorkStartTime', 0) < s.get('WorkEndTime', 0)):
            print(f'[WARN] schedule start>=end : {s}')

    # 샘플 출력
    print('\n  ── sample ProcessNode ──')
    sample = next(iter(m.ManufacturingProcess.values()))
    print(f'   ProcessCode={sample.ProcessCode!r}')
    print(f'   GroupIdShort={sample.GroupIdShort!r}  ProcessGroup={sample.ProcessGroup!r}')
    print(f'   WorkstationId={sample.WorkstationId!r}  CT={sample.CycleTimeSec}s  DR={sample.DefectRate}')
    print(f'   DepType={sample.DepType!r}  DepPrev={sample.DepPrev}')
    print(f'   InputBOM(n={len(sample.InputBOM)}) head={[(b.item_code, b.Quantity) for b in sample.InputBOM[:3]]}')

    print('\n  ── sample WorkstationData ──')
    if not m.WorkstationWorkerMatchingData:
        print('   (empty)')
        return fail
    ws = next(iter(m.WorkstationWorkerMatchingData.values()))
    print(f'   WorkstationId={ws.WorkstationId!r}')
    print(f'   Work={ws.WorkStartTime}~{ws.WorkEndTime}  Break={ws.BreakDurationMin.min}~{ws.BreakDurationMin.max}')
    print(f'   Records={ws.WorkstationConfigurationRecords}  Skill={ws.SkillLevel}')
    print(f'   WorkerIds={ws.WorkerIds[:5]}  AssignedGroups(n={len(ws.AssignedProcessGroups)})')

    if m.HierarchicalStructures.pcb_entries:
        print('\n  ── sample PcbEntry ──')
        pcb = next(iter(m.HierarchicalStructures.pcb_entries.values()))
        print(f'   idShort={pcb.idShort!r}  Side={pcb.SMT_Side!r}  Qty={pcb.Quantity}  components={len(pcb.components)}')
        if pcb.components:
            c = pcb.components[0]
            print(f'   sample comp: item_code={c.item_code!r}  Qty={c.Quantity}  Cat={c.Category!r}')

    print(f'\n  → FAIL count for {model_id} : {fail}\n')
    return fail


def main():
    total = 0
    for mid, path in MODELS:
        total += check_model(mid, path)
    print('=' * 78)
    print(f'TOTAL FAIL : {total}')
    return 0 if total == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
