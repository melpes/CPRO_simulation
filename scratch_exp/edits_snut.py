import json

SH_NONE = '2) PO납기일 기반 생산계획'          # 미이동
SH_BEST = '2-1) PO납기일 기반 생산계획'        # 최적 = 4,1,1,1,2 (SEMI 잔류 2)

# 시계열 블록: (첫 열, 첫 행) — wh | cum×3 | idle×10 | base | smt×7 | asm×10 | 전체
TS = {SH_NONE: (14, 4),                        # N4
      SH_BEST: (18, 4)}                        # R4
# 결과 KPI: wall(h) / 작업(h) / 총 에너지 셀
KPI = {SH_NONE: ('L3', 'L4', 'L5'),
       SH_BEST: ('P5', 'P6', 'P7')}

# 2-1 배분표 (헤더 row12) — 시트에 적힌 배분 순서 그대로
QUOTA_ROWS = [(13, '41113'), (14, '31114'), (15, '51112'), (16, '22222'),
              (17, '41122'), (18, '21124'), (19, '61111'), (20, '41112-semi2')]
QUOTA_COL = 13                                 # M열 = 총 작업시간[h]

RUN = {SH_NONE: 'none', SH_BEST: '41112-semi2'}
DAY, WS_S, WS_E, LB, LE = 86400, 32400, 64800, 43200, 46800
WPD = (WS_E - WS_S) - (LE - LB)


def _dir(tag):
    return f'result/runs/q540s__compbase-due4__realloc-{tag}'


def _cl(col):
    """열 번호 → 열 문자 (A1 표기)."""
    s = ''
    while col:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


def _work_h(sec):
    """wall초 → 작업시간(h). 근무 09:00~18:00, 점심 12:00~13:00 제외."""
    d = int(sec // DAY)
    s = sec - d * DAY
    if s < WS_S:     x = 0.0
    elif s < LB:     x = s - WS_S
    elif s < LE:     x = float(LB - WS_S)
    elif s < WS_E:   x = (s - LE) + (LB - WS_S)
    else:            x = float(WPD)
    return (d * WPD + x) / 3600.0


def _summary(tag):
    return json.load(open(f'{_dir(tag)}/summary.json', encoding='utf-8'))


def apply(app, doc, kind):
    work_h = {tag: round(_work_h(_summary(tag)['makespan_sec']), 2)
              for _, tag in QUOTA_ROWS + [(0, 'none')]}

    for sheet, (c0, r0) in TS.items():
        tag = RUN[sheet]
        pl = json.load(open(f'{_dir(tag)}/xlsx_payload.json', encoding='utf-8'))
        rows = [[b['wh'], *b['cum'], *b['idle'], b['base'], *b['smt'], *b['asm']]
                for b in pl['buckets']]
        n, w = len(rows), len(rows[0])         # w = 31

        ws = doc.Worksheets(sheet)
        ws.Range(ws.Cells(r0, c0), ws.Cells(r0 + 400, c0 + w)).ClearContents()
        ws.Range(ws.Cells(r0, c0), ws.Cells(r0 + n - 1, c0 + w - 1)).Value = rows

        cb = c0 + 14                           # 기저부하량 열
        for i in range(n):
            r = r0 + i
            ws.Cells(r, c0 + w).Formula = (    # 전체 = 기저 + SMT7 + 조립10
                f'=SUM({_cl(cb)}{r}:{_cl(cb + 17)}{r})')

        s = _summary(tag)
        c_wall, c_work, c_e = KPI[sheet]
        ws.Range(c_wall).Value = s['makespan_h']
        ws.Range(c_work).Value = work_h[tag]
        ws.Range(c_e).Value = s['total_energy_kwh']

    ws = doc.Worksheets(SH_BEST)
    for row, tag in QUOTA_ROWS:
        ws.Cells(row, QUOTA_COL).Value = work_h[tag]
        ws.Cells(row, QUOTA_COL).NumberFormat = '0.00'

    ws.Range('I5').Value = work_h['none']      # 작업자 이동 없음
    ws.Range('I6').Value = work_h['22222']     # 균등 분배 2/2/2/2/2
    ws.Range('I5:I6').NumberFormat = '0.00'
    ws.Range('J6').Formula = '=(I6-I5)/I5'
    ws.Range('J6').NumberFormat = '0.0%'
