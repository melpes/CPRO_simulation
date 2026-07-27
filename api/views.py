# -*- coding: utf-8 -*-
# 산출물(artifacts) → 대시보드별 응답. 순수 함수만. GET 1개 = 대시보드 1개, 가공 없이 그대로 그린다.
# 시간축 = 시뮬레이션 경과 시간 dd:hh:mm (휴게·비근무 시간 포함, 버킷 생략 없음).
# 대외 표기: 라인명 = 내부 워크스테이션 id 에서 'WWM_' 접두사 제거 (FwInputLine 등, API.xlsx 용어).

ASSEMBLY_LINES = ['FwInputLine', 'LensHolderLine', 'FocusLine', 'SemiAssemblyLine',
                  'SetAssemblyLine', 'InspectionLine', 'AgingLine', 'OqcLine',
                  'RMALine', 'PackagingLine']

_WS = {line: f'WWM_{line}' for line in ASSEMBLY_LINES}


def _ddhhmm(seconds: float) -> str:
    minutes = int(round(seconds / 60.0))
    return f'{minutes // 1440:02d}:{minutes % 1440 // 60:02d}:{minutes % 60:02d}'


def _series(artifacts: dict):
    """공통 시간축 — 시뮬레이션 경과 시간 dd:hh:mm. 모든 대시보드가 같은 축을 공유한다."""
    series   = artifacts['timeseries']
    features = series['features']
    lines    = [line for line in ASSEMBLY_LINES
                if _WS[line] in features['energy_kwh_by_source']]
    axis = [_ddhhmm(t) for t in series['t_sec']]
    return features, axis, lines


def _envelope(artifacts: dict, axis: list, data: dict) -> dict:
    sample_sec = artifacts['timeseries']['sample_sec']
    return {'샘플링 주기(dd:hh:mm)': _ddhhmm(sample_sec),
            '시뮬레이션 시간(dd:hh:mm)': axis, **data}


# 대시보드 1 · 모델별 생산량
def production_by_model(artifacts: dict) -> dict:
    features, axis, _ = _series(artifacts)
    by_model = features['cumulative_completed_by_model']
    return _envelope(artifacts, axis, {
        '모델별 누적 생산량': {m: by_model[m] for m in sorted(by_model)}})


# 대시보드 2 · 라인별 작업자 점유비율 (0~1 = 작업 인원·시간 ÷ 정원·구간 길이, 비근무 구간은 0)
def line_occupancy(artifacts: dict) -> dict:
    features, axis, lines = _series(artifacts)
    occupancy = features['line_occupancy']
    return _envelope(artifacts, axis, {
        '라인별 작업자 점유비율': {line: occupancy[_WS[line]] for line in lines}})


# 대시보드 3 · 생산 진행 수량 (전체) — 착수 후 미완료 수량
def wip_total(artifacts: dict) -> dict:
    features, axis, _ = _series(artifacts)
    return _envelope(artifacts, axis, {'생산 진행 수량': features['wip']})


# 대시보드 3b · 생산 진행 수량 (모델별)
def wip_by_model(artifacts: dict) -> dict:
    features, axis, _ = _series(artifacts)
    by_model = features['wip_by_model']
    return _envelope(artifacts, axis, {
        '모델별 생산 진행 수량': {m: by_model[m] for m in sorted(by_model)}})


# 대시보드 4 · 공장 가동 전력 (kW)
def instant_power(artifacts: dict) -> dict:
    features, axis, _ = _series(artifacts)
    return _envelope(artifacts, axis, {'공장 가동 전력(kW)': features['instant_power_kw']})


# 대시보드 5 · 전력 사용 비율(%) — 파이 3종, 각 시점의 시작~현재 누적 에너지 기준 비율
#   ① 전체(조립 공정/SMT 공정/기저 부하) ② 조립 라인별(분모=조립 공정) ③ SMT 설비별(분모=SMT 공정)
def power_usage_ratio(artifacts: dict) -> dict:
    features, axis, lines = _series(artifacts)
    energy = features['energy_kwh_by_source']
    smt_equipment = features['smt_equipment_kwh']

    def cumulative(values):
        out, total = [], 0.0
        for value in values:
            total += value
            out.append(total)
        return out

    def percent(numerators: dict) -> dict:
        totals = [sum(series[i] for series in numerators.values())
                  for i in range(len(axis))]
        return {name: [round(series[i] / totals[i] * 100, 2) if totals[i] else 0.0
                       for i in range(len(axis))]
                for name, series in numerators.items()}

    overall = percent({
        '조립 공정': cumulative([sum(energy[_WS[line]][i] for line in lines)
                                for i in range(len(axis))]),
        'SMT 공정' : cumulative(energy['SMT']),
        '기저 부하': cumulative(energy['base']),
    })
    by_line = percent({line: cumulative(energy[_WS[line]]) for line in lines})
    by_equipment = percent({
        (name[:-len('Process')] if name.endswith('Process') else name):
            cumulative(smt_equipment[name])
        for name in sorted(smt_equipment)})
    return _envelope(artifacts, axis, {'전력 사용 비율(%)': {
        '전체': overall, '조립 라인별': by_line, 'SMT 설비별': by_equipment}})
