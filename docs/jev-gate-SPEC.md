# SPEC: Jev Gate

문서 번호: SPEC-JEV-GATE-0.1  
작성: 2026-09-20  
상태: 초안  
관련: `jev-gate-PRD.md`

## 1. 경계

```
Codex App / CLI / 기타 OpenAI 호환 클라이언트
        |
        |  Base URL http://127.0.0.1:10101/v1
        v
   [Jev Gate]  분류 + model rewrite 또는 pass
        |
        |  http://127.0.0.1:10100
        v
   [OpenCodex]
        v
   실제 제공자
```

게이트는 OpenCodex를 대체하지 않는다. 인증·쿼터·카탈로그는 OpenCodex 것이다.

ChatGPT 웹/Work는 이 경로가 아니다.

## 2. 프로세스와 포트

| 항목 | 기본 |
|---|---|
| 게이트 listen | `127.0.0.1:10101` |
| 업스트림 | `http://127.0.0.1:10100` (설정 가능) |
| GUI | `http://127.0.0.1:10101/` |
| 팩 파일 | `~/.config/jev-gate/pack.json` |
| Jev | `POST https://api.typesafe.ai/v1/systemone` model `jev-latest` |

루프백만. 외부 바인드 없음 (v1).

## 3. 팩 스키마

```json
{
  "home_model": "gpt-5.6-sol",
  "confidence_floor": 0.6,
  "enabled": true,
  "max_task_chars": 2000,
  "roles": {
    "implement": {
      "when": "Write or edit code in the repo.",
      "model": "gpt-5.6-terra"
    },
    "research": {
      "when": "Look up current facts, prices, or docs.",
      "model": "xai/grok-4.5"
    },
    "write": {
      "when": "Draft or edit prose. Korean quality may matter.",
      "model": "gpt-5.6-sol"
    }
  }
}
```

규칙:

- `home_model`은 OpenCodex 카탈로그 id여야 한다
- `roles.*.model`도 카탈로그 id. 빈 칸은 생략
- 역할 id는 영문 슬러그. Jev Choice 키와 동일
- `when`은 영어 한 줄. Jev instructions/criteria용
- 역할 1~4개. 0개면 게이트는 순수 프록시

## 4. Jev 질문

모델 id, 가격, 카탈로그를 state에 넣지 않는다.

```json
{
  "model": "jev-latest",
  "state": {
    "task": "<첫 user 텍스트, max_task_chars>"
  },
  "questions": {
    "role": {
      "type": "choice",
      "instructions": "What is the primary job of `state.task`?",
      "criteria": {
        "implement": "<pack.roles.implement.when>",
        "research": "<pack.roles.research.when>",
        "write": "<pack.roles.write.when>",
        "other": "None of the other options fit, mixed, or unclear."
      }
    },
    "needs_korean": {
      "type": "noul",
      "instructions": "Is Korean language quality central to completing `state.task` well?",
      "criteria": {
        "true": "The output must be good Korean, or the source is Korean.",
        "false": "Korean is incidental or unused."
      }
    }
  }
}
```

`criteria`의 역할 키는 팩에 모델이 채워진 칸만 넣는다. `other`는 항상 있다.

`needs_korean` noul ≥ floor 이고 `write` 역할이 있으면, Choice가 `implement`여도 `write`로 보낸다. (한글 교정·안내문을 코딩 모델에 안 태우기)

## 5. 분기

입력: `incoming_model`, `task`, `thread_key`

```
enabled == false                    → pass
Jev 실패/무키/타임아웃               → pass
thread_key가 sticky에 있음          → rewrite to sticky.model  (표시 sticky)
incoming_model != home_model        → pass   (사용자가 픽커를 바꿈)
role == other                       → pass
role.confidence < floor             → pass
role에 해당하는 pack.roles 없음     → pass
그 외                               → rewrite to pack.roles[role].model
                                     sticky[thread_key] = that model
```

v1은 병렬/리뷰 실행 없음. `needs_review` 질문은 v2.

## 6. 프록시 동작

### 6.1 통과
`GET /v1/models`, `GET /healthz`, OPTIONS, 그 외 GET/HEAD는 바이트 단위 업스트림.

### 6.2 패치 대상 POST
- `/v1/chat/completions`
- `/v1/responses`

바디 JSON의 `model` 필드를 규칙대로 바꿀 수 있다. 스트리밍(`stream: true`)은 업스트림 스트림을 그대로 파이프.

Anthropic 호환 경로가 OpenCodex에 있으면 v1에서 같은 규칙으로 `model`만 패치. 모르면 pass.

### 6.3 task 추출
`messages` 배열에서 role=user인 마지막 텍스트.  
`input` / `instructions`가 있는 responses 바디도 동일하게 첫 텍스트 블록.

이미지나 도구 결과만 있으면 pass.

### 6.4 thread_key
우선순위:

1. 헤더 `X-Session-Id` / `Session-Id` / `Thread-Id`
2. 없으면 `sha256(home_model + 첫 task)[:16]` 을 약 sticky로 쓰지 말고 **pass** (오결합 방지)

Codex App이 세션 헤더를 안 주면 v1은 매 요청 분류한다. 헤더가 있으면 sticky. 구현 시 실측 후 SPEC에 헤더 이름을 고정한다.

### 6.5 응답 헤더 (클라이언트에 노출)
- `X-Jev-Gate: pass | rewrite | sticky | error-pass`
- `X-Jev-Role: implement | research | write | other | -`
- `X-Jev-Confidence: 0.00–1.00`
- `X-Jev-Model-In: ...`
- `X-Jev-Model-Out: ...`

프롬프트 미포함.

## 7. GUI

`GET /` 단일 페이지. 외부 CDN 없이.

필수 화면:

1. OpenCodex 연결 상태 (`/healthz` 프록시)
2. 모델 목록 새로고침 (`/v1/models`)
3. `home_model` 셀렉트
4. 역할 3칸 셀렉트 (implement / research / write)
5. `enabled`, `confidence_floor` 슬라이더
6. 저장 → `pack.json`
7. 최근 20개 게이트 이벤트 테이블 (시각, in/out model, role, confidence, 판정). task 텍스트 없음

저장 API: `PUT /api/pack` 로컬만.

## 8. 설정과 시크릿

- `TYPESAFE_API_KEY` 환경변수. 팩 파일에 넣지 않음
- OpenCodex admin 토큰 불필요 (`/v1/models` 실측 200)
- 게이트는 OpenCodex API 키를 새로 만들지 않음. 클라이언트 Authorization을 그대로 전달

## 9. 실패 모드

| 상황 | 동작 |
|---|---|
| OpenCodex 다운 | 업스트림 오류를 그대로 클라이언트에 |
| 팩 손상 | enabled 무시하고 pass, GUI에 오류 |
| Jev 3초 초과 | error-pass |
| rewrite 대상 id가 현재 `/v1/models`에 없음 | pass |
| 본문이 model 없는 POST | pass |

## 10. 테스트

유닛:

- 팩 역할로 Jev criteria 생성. 빈 칸 제외
- incoming != home → pass
- confidence 0.41 → pass
- research 0.82 + home sol → out grok
- korean noul 높고 write 있음 + implement choice → write
- Jev throw → pass

스모크 (로컬):

- `GET :10101/v1/models` 개수 = `:10100/v1/models`
- Codex CLI `-m gpt-5.6-sol` 검색 문장 → 로그 rewrite
- 게이트 종료 후 CLI를 `:10100`으로 되돌리면 평소와 동일

## 11. v2 (명시적으로 미구현)

- Herdr: review 역할 CLI를 옆 팬에 띄우기
- 스레드 중 재분류 버튼
- 역할 칸 사용자 정의 추가
- Orca dispatch

## 12. 구현 순서

1. 순수 프록시 `:10101` → `:10100` (스트리밍)
2. pack.json + GUI 셀렉트
3. Jev 분류 + rewrite 규칙
4. 헤더·이벤트 테이블
5. Codex App `/v1/responses` 실측 후 thread_key 고정
