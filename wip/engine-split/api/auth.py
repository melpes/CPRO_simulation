# -*- coding: utf-8 -*-
# 인증 훅 — 지금은 통과(no-op). 외부 공개 정책이 정해지면 이 파일만 채우면
# 전 라우터(dependencies=[Depends(require_api_key)])에 일괄 적용된다.
def require_api_key() -> None:
    return None
