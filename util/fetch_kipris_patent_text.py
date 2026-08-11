"""KIPRIS 목록의 제목·출원인으로 Google Patents 명세서·청구항을 받는다.

KIPRIS 는 목록만 자동화가 쉽고 상세는 새 창으로 열려 번거롭다.
Google Patents 는 HTTP 로 전문을 준다. 그래서 발굴은 KIPRIS, 전문은 Google Patents 로 나눈다.

주의: KIPRIS '출원번호' 는 Google Patents 의 '공개번호' 가 아니다.
      번호를 변환해 붙이면 전혀 다른 특허가 잡힌다(실제로 겪었다).
      그래서 제목+출원인으로 검색해 공개번호를 먼저 찾는다.
"""

import json
import os
import random
import re
import sys
import time

import requests

BASE = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package"
SRC = os.path.join(BASE, r"docs\원본자료\keti-fab\특허수집")
OUT = os.path.join(SRC, "명세서")
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 장비가 조정하는 값을 나타내는 표현. 측정 결과(막 두께 실측·XRD 피크)는 노린 것이 아니다.
SPEC = re.compile(
    r"(?:온도|압력|속도|파워|전력|주파수|유량|간격|각도|두께|시간|농도|회전수|전압|전류)"
    r"[^.。\n]{0,20}?(?:범위|제어|조절|유지|설정|이내|이상|이하|내지)"
    r"|\d[\d.,]*\s*(?:℃|㎜|mm|㎛|um|nm|Torr|mTorr|sccm|slm|kW|W|MHz|kHz|rpm|%|kPa|MPa|bar)"
)


class Blocked(Exception):
    pass


def norm(s):
    return re.sub(r"[^0-9a-z가-힣]", "", (s or "").lower())


def search(title, assignee, sess):
    """제목+출원인으로 공개번호를 찾는다. 제목이 가장 비슷한 것을 고른다."""
    inner = f"q={title}&assignee={assignee}"
    url = "https://patents.google.com/xhr/query?url=" + requests.utils.quote(inner)
    r = sess.get(url, headers=HDR, timeout=30)
    if "<title>Sorry" in r.text[:2000]:
        raise Blocked(title)
    if r.status_code != 200:
        return None
    try:
        d = r.json()
    except Exception:
        return None
    want = norm(title)
    best, best_score = None, -1
    for c in d.get("results", {}).get("cluster", []):
        for res in c.get("result", []):
            p = res.get("patent", {})
            pn = p.get("publication_number", "")
            ti = norm(re.sub("<[^>]+>", "", p.get("title", "")))
            if not pn:
                continue
            # 제목이 서로를 포함하면 같은 건으로 본다
            score = 2 if (want and (want in ti or ti in want)) else (1 if want[:8] and want[:8] in ti else 0)
            if score > best_score:
                best, best_score = (pn, p.get("title", "")), score
    return best if best_score > 0 else None


def fetch(pubno, sess):
    url = f"https://patents.google.com/patent/{pubno}/ko"
    r = sess.get(url, headers=HDR, timeout=30)
    r.encoding = "utf-8"                      # 지정하지 않으면 한글이 깨진다
    if "<title>Sorry" in r.text[:2000]:
        raise Blocked(pubno)
    if r.status_code != 200:
        return None
    out = {"공개번호": pubno, "url": url}
    for key, mark in (("명세서", 'itemprop="description"'), ("청구항", 'itemprop="claims"')):
        if mark not in r.text:
            out[key] = ""
            continue
        seg = r.text.split(mark, 1)[1].split("</section>", 1)[0]
        out[key] = re.sub(r"\n{2,}", "\n", re.sub(r"<[^>]+>", "\n", seg)).strip()
    m = re.search(r'<meta name="DC.title" content="([^"]+)"', r.text)
    out["제목"] = m.group(1).strip() if m else ""
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    tasks = []
    for f in sorted(__import__("glob").glob(os.path.join(SRC, "kipris_*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        maker = os.path.basename(f).replace("kipris_", "").replace(".json", "").split("_")[0]
        for r in d.get("목록", []):
            t = (r.get("제목") or "").strip()
            t = re.sub(r"^\[\d+\]\s*", "", t)
            if t:
                tasks.append((maker, t, r.get("출원번호", "")))
    seen, uniq = set(), []
    for m, t, a in tasks:
        if (m, t) in seen:
            continue
        seen.add((m, t))
        uniq.append((m, t, a))

    done = {p.replace(".json", "") for p in os.listdir(OUT)}
    print(f"KIPRIS 목록 {len(tasks)} → 고유 {len(uniq)} / 이미 받음 {len(done)}")

    sess = requests.Session()
    ok = miss = 0
    for i, (maker, title, appno) in enumerate(uniq, 1):
        key = f"{maker}__{re.sub(r'[^0-9A-Za-z가-힣]', '_', title)[:50]}"
        if key in done:
            continue
        try:
            hit = search(title, maker, sess)
            time.sleep(7 + random.random() * 3)
            if not hit:
                miss += 1
                print(f"  [{i}] 못 찾음  {maker} / {title[:34]}")
                continue
            got = fetch(hit[0], sess)
        except Blocked:
            print(f"  [{i}] 차단됨 — 60분 뒤 재시도 필요. 중단")
            break
        except Exception as e:
            miss += 1
            print(f"  [{i}] 실패 {str(e)[:40]}")
            time.sleep(6)
            continue
        if not got or not got["명세서"]:
            miss += 1
        else:
            got.update({"제조사": maker, "KIPRIS_제목": title, "KIPRIS_출원번호": appno})
            got["사양표현수"] = len(SPEC.findall(got["명세서"] + got["청구항"]))
            with open(os.path.join(OUT, key + ".json"), "w", encoding="utf-8") as fp:
                json.dump(got, fp, ensure_ascii=False, indent=1)
            ok += 1
            print(f"  [{i}/{len(uniq)}] {maker:8} {got['제목'][:30]:32} "
                  f"{len(got['명세서']):>6}자 사양 {got['사양표현수']:>3}")
        time.sleep(7 + random.random() * 3)

    print(f"\n성공 {ok} / 실패·미발견 {miss}")


if __name__ == "__main__":
    main()
