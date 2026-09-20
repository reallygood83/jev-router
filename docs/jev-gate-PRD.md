# PRD: Jev Gate

문서 번호: PRD-JEV-GATE-0.1  
작성: 2026-09-20  
상태: 초안  
관련: `jev-gate-SPEC.md`  
전제: 로컬 OpenCodex (`http://127.0.0.1:10100`, 실측 2026-09-20 v2.41.0)

## 1. 한 줄

OpenCodex 앞에 아주 얇은 게이트를 둔다. GUI에서 역할별 모델을 미리 고르고, 요청이 들어오면 Jev가 **이번 프롬프트가 어느 역할인지**만 찍어서 `model`을 바꾼다.

Jev는 모델을 고르지 않는다. 칸을 고른다.

## 2. 문제

OpenCodex는 프롬프트를 읽지 않는다. 요청에 적힌 `model` 그대로 보낸다.

실측: `GET /v1/models` 78개, 토큰 없이 200. 자동 전환 없음.

그래서 Codex 픽커를 `gpt-5.6-sol`에 두면 검색 문장도 sol로 간다. 매 턴 픽커를 바꾸기 싫으면, 지금 문장이 구현인지 검색인지를 값싸게 구분해 `model`만 갈아끼워야 한다.

## 3. 사용자

| 역할 | 설명 |
|---|---|
| 본인 / 멀티모델 사용자 | OpenCodex에 Codex·Grok·Solar 등을 이미 붙인 사람. Codex App/CLI를 프론트도어로 씀 |
| 대상 아님 | OpenCodex 없는 사람, ChatGPT 웹/앱 (localhost:10100을 안 탐) |

## 4. 해야 할 것 (Must)

### FR-01 역할 프리셋 GUI
로컬 GUI가 OpenCodex `GET /v1/models`를 읽어 드롭다운을 채운다. 역할 칸은 최대 4개.

기본 칸:

| 역할 id | 의미 | 기본 `when` (Jev criteria) |
|---|---|---|
| `home` | 픽커에 두고 다니는 기본 | (매핑만. Jev 선택지가 아님) |
| `implement` | 코드 작성·수정·테스트 | Write or edit code in the repo. |
| `research` | 최신 정보·가격·문서 확인 | Look up current facts, prices, or docs. |
| `write` | 글·톤·교정 | Draft or edit prose. Korean quality may matter. |

사용자는 각 칸에 OpenCodex 모델 id 하나를 고른다. 비어 있으면 그 역할은 없다.

### FR-02 얇은 프록시
게이트는 OpenCodex 앞 포트에서 OpenAI 호환 요청을 받는다. 기본 `:10101` → `:10100`.

하는 일:

1. 첫 user 메시지에서 역할 분류 (Jev)
2. confidence가 문턱 이상이고, 들어온 `model`이 `home`이면, 역할에 묶인 id로 `model` 교체
3. 그 외는 원본 그대로 OpenCodex에 전달

그 외 헤더·바디·스트리밍은 통과.

### FR-03 Jev는 역할만
TypeSafe System One. 모델 id를 state/questions에 넣지 않는다.

한 호출에:

- Choice: `implement` / `research` / `write` / `other` (팩에 있는 칸만 + other)
- Noul: 한국어 품질이 핵심인가
- 각 confidence

`other` 또는 confidence < 문턱(기본 0.6)이면 교체하지 않는다.

### FR-04 home 모델일 때만 교체
들어온 `model`이 GUI의 `home`과 같을 때만 바꾼다. 사용자가 terra/Grok을 일부러 고른 턴은 이기지 않는다.

### FR-05 스레드 고정
같은 Codex 스레드(`thread` / `session` 헤더 또는 메시지 해시)는 **첫 분류만** 한다. 이후 턴은 그 스레드에 고정한 모델을 쓴다. 주제가 바뀌면 새 스레드가 정답이다.

### FR-06 실패 시 통과
Jev 키 없음, 타임아웃, HTTP 오류, 빈 답 → **원본 요청 그대로** OpenCodex. 게이트가 호출을 죽이면 안 된다.

### FR-07 표시
GUI 또는 응답 헤더로 이번 턴이 `pass` / `rewrite` / `sticky`인지, 역할·confidence를 보여 준다. 프롬프트 본문은 로그에 저장하지 않는다.

## 5. 하면 안 되는 것 (v1 Non-goals)

- OpenCodex 포크, 대시보드 교체
- ChatGPT 웹/앱 가로채기
- 79개 모델 자동 승인
- Jev에게 모델 이름을 고르게 하기
- implement 다음 sonnet 리뷰를 프록시가 실행하기 (Herdr/Orca는 v2)
- 품질이 올라간다는 효과 주장
- 매 턴 TypeSafe로 전체 대화 보내기

## 6. 사용자 시나리오

1. GUI에서 home=`gpt-5.6-sol`, implement=`gpt-5.6-terra`, research=`xai/grok-4.5`, write=`gpt-5.6-sol` (또는 Solar)
2. Codex App Base URL을 `http://127.0.0.1:10101/v1`로 둔다. 픽커는 sol.
3. `Upstage 가격 지금 얼마야` → Jev research 0.8+ → OpenCodex로 `xai/grok-4.5`
4. `파서 함수 짜고 테스트` → implement → `gpt-5.6-terra`
5. `이거 좀 이상한데` → other 또는 낮은 confidence → sol 그대로
6. 픽커를 Grok으로 바꾼 턴 → 게이트 손 안 댐

## 7. 성공 기준

- OpenCodex 없이 게이트만 켜면 클라이언트가 바로 실패를 본다 (숨기지 않음)
- OpenCodex 있으면 `/v1/models`가 게이트를 통해서도 동일 목록
- home=sol인 채 검색 문장 스모크가 research 모델로 나감 (로그의 `x-jev-gate: rewrite`)
- 애매한 문장은 `pass`
- Jev를 끄면 Codex 사용에 차이가 없음 (순수 프록시)

## 8. 리스크

| 리스크 | 대응 |
|---|---|
| 프롬프트가 TypeSafe로 감 | 옵트인, 첫 턴·앞 2000자만, 본문 미저장 |
| Codex App이 `/v1/responses` 사용 | completions와 responses 둘 다 같은 규칙 |
| 스레드 중 주제 변경 | v1은 고정. 새 스레드 |
| 분류 오탐 | 문턱 + home일 때만 교체 + pass 기본 |

## 9. 구현 가능 여부

가능. v1은 로컬 프로세스 하나다.

- 프록시: OpenCodex로 스트리밍 패스스루 + POST 시 model 패치
- GUI: 같은 프로세스가 정적 페이지. 모델 목록은 `/v1/models` 프록시
- 키: `TYPESAFE_API_KEY`. 팩: `~/.config/jev-gate/pack.json`

Herdr 리뷰 팬은 v2. v1에 넣지 않는다.
