# JobFlow

> **Migration status:** this README documents the reviewed rolling-plan implementation at baseline `767fc1ac4a4ae38351cfb925ec29eb91ef2162ef`. All `2주`/`14일` statements below are historical baseline behavior, not the normative target. The approved selected-calendar-month contract and downstream migration requirements are in `docs/architecture.md`; frontend implementation will update this README after the backend month schema is approved.

JobFlow는 한국어로 입력한 취업 준비 작업을 편집 가능한 구조로 검토한 뒤, 2주 동안의 충돌 없는 `규칙 기반 일정`으로 배치하는 로컬 Gradio MVP입니다.

## 무엇을 하나요

1. 한국어 원문과 기준 시각, 계획 시작일을 입력합니다.
2. `Parse — AI로 구조화`를 눌러 마감 작업, 반복 일정, 가능 시간, 고정 일정을 추출합니다.
3. 네 개의 표와 필드·항목 진단을 검토하고 필요한 값을 수정합니다.
4. 모든 결정적 검증을 통과한 뒤 `검토 완료`를 체크합니다.
5. `규칙 기반 일정 만들기`를 눌러 2주 일정, 미배치 사유, 분 단위 통계를 확인합니다.

일정 생성은 30분 격자, `Asia/Seoul`, 가능 시간, 고정 일정, 마감, 반복 허용 시간, 작업별·전체 일일 제한을 결정적으로 적용합니다. 반복 일정의 제한된 발생분을 먼저 배치하고, 마감 작업은 이른 마감순으로 배치합니다.

## 개인정보, 외부 전송, 비용

- 한국어 원문은 사용자가 Parse 버튼을 누를 때만 로컬 `.env`에 설정한 OpenAI API로 전송됩니다.
- OpenAI API 사용에는 계정 설정에 따른 비용이 발생할 수 있습니다. 기본 모델은 `gpt-4.1-mini`입니다.
- 구조화 검토 뒤의 검증, 일정 생성, 요약에는 모델 호출이나 추가 API 비용이 없습니다.
- API 키는 브라우저 입력, Gradio 상태, 결과에 포함하지 않습니다.
- JobFlow는 원문, 검토 데이터, 결과를 파일이나 데이터베이스에 저장하지 않습니다. Gradio 분석 전송과 실행 기록도 비활성화하며, 새로고침하거나 프로세스를 종료하면 세션 데이터가 사라집니다.
- 자동 테스트는 가짜 Runnable과 구조화 fixture만 사용하며 실제 OpenAI 네트워크 호출을 하지 않습니다.

## 한계

- 이 MVP의 스케줄러는 설명 가능한 greedy 규칙을 사용합니다. 전체 배치량을 최대화하지 않으며, 다른 재배치가 더 많은 작업을 담을 수도 있습니다. 배치하지 못한 작업은 사유와 남은 시간을 별도 표에 항상 표시합니다.
- 시간대는 `Asia/Seoul`, 계획 범위는 14일, 시간 격자는 30분으로 고정됩니다.
- 자정이 넘어가는 가능 시간은 지원하지 않으므로 날짜별 규칙으로 나눠 입력해야 합니다.
- 계정, 데이터베이스, 지속 저장, 알림, Google Calendar 연동, ICS 내보내기, 드래그앤드롭, 배포 기능은 포함하지 않습니다.
- LLM은 텍스트 구조화만 담당합니다. 충돌, 용량, 반복, 마감, 시간대의 최종 판단은 Pydantic 검증과 결정적 스케줄러가 담당합니다.

## 로컬 설치

Python 3.11 또는 3.12가 필요합니다. 저장소 루트에서 실행하세요.

```bash
cd /mnt/hermes-data/jobflow-calendar
python3 -m venv .venv
PIP_CACHE_DIR=$PWD/.cache/pip XDG_CACHE_HOME=$PWD/.cache \
  .venv/bin/python -m pip install -e '.[dev]'
```

## OpenAI 설정

실제 Parse 기능을 사용할 때만 프로젝트 로컬 환경 파일을 만듭니다.

```bash
cp .env.example .env
```

`.env`에 본인이 소유한 키를 입력합니다.

```dotenv
OPENAI_API_KEY=your-own-key
OPENAI_MODEL=gpt-4.1-mini
```

`.env`는 Git에서 제외됩니다. 공유 키, 수업용 키, Hermes/Codex 인증 정보를 복사하지 마세요. 키가 없어도 앱은 정상적으로 실행되고 구조화 데모와 일정 생성은 사용할 수 있습니다. 키 없이 Parse를 누르면 안전한 한국어 설정 안내가 표시됩니다.

## 실행

```bash
.venv/bin/python -m jobflow.app
```

기본값은 로컬 컴퓨터에서만 접근 가능한 `127.0.0.1` 주소입니다. 터미널에 표시된 URL을 브라우저에서 여세요.

## 키 없는 canonical 데모

1. 앱을 실행합니다.
2. `키 없이 구조화 데모 불러오기`를 누릅니다.
3. 기준 컨텍스트가 2026-03-02 KST, 계획 시작일이 2026-03-02인지 확인합니다.
4. 두 마감 작업, 월·수·금 면접 연습, 평일 저녁·토요일 오전 가능 시간, 2026-03-04 스터디를 검토합니다.
5. `검토 완료`를 체크하고 `규칙 기반 일정 만들기`를 누릅니다.
6. 요청 960분, 배치 960분, 미배치 0분과 면접 연습 6회가 표시되는지 확인합니다.
7. 표를 수정하면 이전 결과와 검토 완료가 즉시 무효화됩니다. 예를 들어 반복 일정의 한 날짜에 허용 시간 전체를 덮는 고정 일정을 추가하면 미배치 표에 정확한 사유와 남은 시간이 표시됩니다.

## 테스트와 품질 검사

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest --cov=jobflow --cov-report=term-missing
.venv/bin/ruff check src tests
.venv/bin/mypy src/jobflow
```

실제 HTTP 준비 상태를 확인하려면 앱을 실행한 터미널과 별도로 다음을 실행합니다. 포트는 실행 로그에 표시된 값으로 바꾸세요.

```bash
curl --fail http://127.0.0.1:7860/
```

## 구조

- `src/jobflow/extraction.py`: 선택적 OpenAI/LangChain 구조화 경계
- `src/jobflow/validation.py`: 편집 데이터의 결정적 검증과 요청 변환
- `src/jobflow/scheduler.py`: 순수하고 결정적인 규칙 기반 스케줄러
- `src/jobflow/services.py`: Parse/검토/일정 서비스 경계
- `src/jobflow/ui.py`: Gradio Blocks, 세션 상태, 표·진단·결과 변환
- `src/jobflow/app.py`: `.env` 로드와 loopback 실행 진입점
- `docs/architecture.md`: 공유 모델과 정책의 규범 문서
