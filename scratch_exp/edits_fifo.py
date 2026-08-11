import json

SHEET = '2) PO납기일 기반 생산계획'
RUN = 'result/runs/q540s__fifo-due4__realloc-none'

C0, R0 = 8, 5            # 타임라인 좌상단 H5
RMA = 8                  # 시트에 RMA 열이 없음 → payload의 RMA(9번째)만 제외
POST_TOP, POST_BOT = 81, 157      # 기존 '강화학습 후' 블록 (H~AL)
SHIFT = 23                        # 강화학습 전이 97행이라 아래로 밀어냄

DAY, WS_S, WS_E, LB, LE = 86400, 32400, 64800, 43200, 46800
WPD = (WS_E - WS_S) - (LE - LB)


def _cl(col):
    s = ''
    while col:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


def _work_h(sec):
    d = int(sec // DAY)
    s = sec - d * DAY
    if s < WS_S:     x = 0.0
    elif s < LB:     x = s - WS_S
    elif s < LE:     x = float(LB - WS_S)
    elif s < WS_E:   x = (s - LE) + (LB - WS_S)
    else:            x = float(WPD)
    return (d * WPD + x) / 3600.0


def _drop_rma(seq):
    return [v for i, v in enumerate(seq) if i != RMA]


def apply(app, doc, kind):
    pl = json.load(open(f'{RUN}/xlsx_payload.json', encoding='utf-8'))
    s = json.load(open(f'{RUN}/summary.json', encoding='utf-8'))
    rows = [[b['wh'], *b['cum'], *_drop_rma(b['idle']), b['base'], *b['smt'], *_drop_rma(b['asm'])]
            for b in pl['buckets']]
    n, w = len(rows), len(rows[0])            # w = 30 (wh1+cum3+idle9+base1+smt7+asm9)

    ws = doc.Worksheets(SHEET)

    # '강화학습 후' 블록을 아래로 이동 (덮어쓰기 방지 — 먼저 비켜준다)
    src = ws.Range(f'{_cl(C0)}{POST_TOP}:{_cl(C0 + w)}{POST_BOT}')
    src.Cut(ws.Range(f'{_cl(C0)}{POST_TOP + SHIFT}'))

    # 강화학습 전 타임라인
    ws.Range(ws.Cells(R0, C0), ws.Cells(R0 + 400, C0 + w)).ClearContents()
    ws.Range(ws.Cells(R0, C0), ws.Cells(R0 + n - 1, C0 + w - 1)).Value = rows

    cb = C0 + 13                              # 기저부하량 열(U)
    for i in range(n):
        r = R0 + i
        ws.Cells(r, C0 + w).Formula = f'=SUM({_cl(cb)}{r}:{_cl(cb + 16)}{r})'  # 기저+SMT7+조립9

    # 강화학습 전 지표 (B44 헤더 아래 row45)
    ws.Range('C45').Value = round(_work_h(s['makespan_sec']), 2)
    ws.Range('D45').Value = s['total_energy_kwh']
