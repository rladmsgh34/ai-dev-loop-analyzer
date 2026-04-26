"""
코드 전용 토크나이저.

일반 NLP 토크나이저는 `linux-musl-openssl-3.0.x` 같은 기술 키워드를
하나의 토큰으로 취급해 BM25 검색에서 누락시킨다.
하이픈/언더바/점/슬래시와 CamelCase 경계로 추가 분리해
개별 토큰으로 색인한다.
"""

import re


def code_tokenizer(text: str) -> list[str]:
    """
    코드 및 diff 텍스트를 BM25 색인용 토큰 리스트로 변환한다.

    분리 기준: 공백, 하이픈, 언더바, 마침표, 슬래시, 콜론, @, 괄호, 따옴표,
               등호, 부등호, 파이프, 앰퍼샌드 등 기호 문자.
    추가 분리: CamelCase 경계 (예: BinaryTargets → binary targets).
    """
    # 기호 문자로 분리
    parts = re.split(r'[\s\-_./:\\@\[\]{}()\'"=<>|&^%#!?;,~`]+', text)
    result = []
    for part in parts:
        if not part:
            continue
        # CamelCase → 소문자 토큰 분리
        camel_expanded = re.sub(r'([a-z])([A-Z])', r'\1 \2', part)
        for token in camel_expanded.split():
            token = token.lower()
            if token:
                result.append(token)
    return result
