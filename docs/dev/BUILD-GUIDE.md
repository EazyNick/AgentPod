# 자율 에이전트 컨테이너 — 빌드 가이드

> 이 문서는 [ccc-extract.html](ccc-extract.html)의 설계 자산 분석과, 그 위에서 내린 프로젝트별 결정을 종합한 **구현 명세서**다.
> 목표: Docker로 격리된 **자율 AI 코딩 에이전트 실행 환경**을 처음부터 구축한다.
> 참조 구현: `claude-code-container`(ccc) 저장소 — 검증된 패턴의 출처. `파일:라인`은 그 저장소 기준.
> **언어 주의**: ccc는 TypeScript다. 이 프로젝트는 **Python으로 재구현**하므로, ccc 참조는 *동작·규칙의 근거*이지 코드 이식이 아니다. TS 함수명(`cleanupSession()` 등)은 "그 로직을 Python으로 다시 구현하라"는 뜻.

---

## 0. 한 문장 요약

**"위험한 자율 실행 플래그를 Docker 격리로 감싸고, 필요한 모든 것(env·MCP·skills·컨텍스트)은 호스트 상태가 아니라 파일에 선언해 두며, 다 쓴 컨테이너는 세션 카운팅으로 자동 정리한다. 격리된 에이전트 컨테이너를 CLI로 쉽게 여러 개 띄워 쓰고, 각 컨테이너는 자기 MD 컨텍스트와 사용자 명령으로만 움직인다."**

> **자족성 원칙**: 이 문서 하나만 보고 구현 가능해야 한다. 형식·경로·수명주기 규칙을 구체적으로 명시한다. 애매하면 참조 구현(`ccc` 저장소의 `파일:라인`)을 따른다.
> **범위 원칙**: 웹 UI·채팅·자동 잡 큐는 만들지 않는다. 진입점은 **CLI 하나**. 사용자가 명령으로 에이전트를 움직이고, 컨테이너마다 다른 MD 컨텍스트를 본다. "쉽게 다수 실행"이 목표.

---

## 1. 설계 철학 (움직이지 않는 원칙)

| 원칙 | 의미 | 근거 |
|------|------|------|
| **격리가 자율성을 가능하게 한다** | `--dangerously-skip-permissions`(무인 실행)를 컨테이너로 폭발 반경을 가둬 안전하게 만든다 | 격리 없이 이 플래그를 쓰면 재앙 |
| **호스트 독립 (선언적)** | env·MCP·skills를 호스트에서 자동으로 긁어오지 않는다. 파일에 **적어두면** 자동으로 갖춰진다 | 어디서 빌드해도 동일하게 재현 |
| **컨테이너는 일회용, 상태는 볼륨/바인드로 영속** | 컨테이너는 언제든 버릴 수 있고, 로그인·캐시 등 무거운 상태는 밖으로 빼서 유지 | 재실행 시 즉시 복원 |
| **단일 타깃으로 좁힌다** | 리눅스 + Docker 고정. 멀티 런타임/멀티 OS 보정 안 함 | 복잡도 제거 |
| **완전한 호스트 독립** | git 신원조차 전용 봇 계정으로. 호스트 상태에 의존하는 부분이 없다 | 감사(audit) 명확 + 어디서 실행해도 동일 |
| **에이전트 컨테이너는 격리, docker는 바깥에서** | 컨테이너를 스폰·관리하는 docker 명령은 호스트 오케스트레이션 층이 실행. 에이전트 컨테이너 안엔 `docker.sock` 없음 | 격리 유지 |

---

## 2. 확정된 설계 결정 (ccc 대비)

이 프로젝트는 ccc를 그대로 베끼지 않는다. 아래는 **의도적으로 다르게** 가거나 **뺀** 것들이다.

### 2.1 가져오는 것 (ccc 그대로 / 거의 그대로)

- **경로 해시 기반 결정적 컨테이너 이름** — `agent-<project>-<hash>`
- **세션 락파일 + 레퍼런스 카운팅 + 자동 정리** — 마지막 세션이 나가면 컨테이너 stop
- **크래시 복구** — PID liveness 체크로 stale 락 청소
- **시그널 핸들링** — SIGINT/TERM/HUP → cleanup
- **격리된 크레덴셜 저장** — 호스트 `~/.claude`가 아닌 앱 전용 저장소
- **프로파일 — 다중 신원 분리** — 봇 계정 vs 개인 계정 공존
- **mise 프로젝트별 툴 버전 + 볼륨 캐시**
- **런타임 바이너리 설치 + 볼륨 캐싱** — 이미지에 굽지 않고 런타임 설치 → 자동 업데이트 지속
- **캐시 친화적 멀티스테이지 Dockerfile**
- **이미지 재빌드 시 컨테이너 자동 업그레이드**
- **멀티 에이전트 registry** (claude/gemini/codex/opencode) — 도구별 플래그·크레덴셜·설치를 단일 registry로 (참조: `tool-registry.ts:33`)

### 2.2 다르게 가는 것 (divergence)

| 영역 | ccc 방식 | 이 프로젝트 방식 | 이유 |
|------|----------|------------------|------|
| **환경변수** | 호스트 env를 denylist로 걸러 자동 포워딩 | **`.env` 파일에 명시** (`--env-file`) | 무엇이 들어가는지 명시적·재현 가능 |
| **MCP** | 호스트 `~/.claude.json`에서 포워딩 | **`.mcp.json` 매니페스트에 선언 → 빌드 시 설치** | 호스트 독립 |
| **skills** | (해당 없음) | **매니페스트에 목록 선언 → 설치** | 선언적 설치 |
| **localhost** | `host.docker.internal`로 재작성 | **재작성 안 함 — localhost = 컨테이너 자신** | 에이전트가 컨테이너 안에서 자기 서버 운용 |
| **네트워크** | `--network host` + iptables 투명 프록시 | **기본 bridge 네트워크** | 더 격리됨. 웹서버 안 띄움 |
| **런타임** | docker/podman 추상화 | **`docker` 고정** | 리눅스 Docker 단일 타깃 |
| **브라우저** | Chromium + X11 + 클립보드 스택 전부 | **헤드리스 Chromium + 폰트만 내장** | MCP 대비 필요, GUI 스택 불필요 |
| **git 신원** | 호스트 gitconfig + SSH agent 포워딩 | **전용 봇 신원** (deploy key/토큰 + 봇 `user.name`/`user.email`) | 감사 명확 · 완전한 호스트 독립 |

### 2.3 빼는 것 (제외)

- 원격 개발 (Tailscale + Mutagen)
- localhost 투명 프록시 (iptables + Go)
- 런타임 추상화 (podman 지원)
- 호스트 MCP 포워딩 (`mcp-forward.ts:39`)
- 관리형 MCP 강제 주입 + localhost 재작성 (`mcp-forward.ts:54`)
- X11 디스플레이 서버 / xvfb / 클립보드 브리지 / computer-use

### 2.4 확정된 운영 모델

- **병렬 처리 = 모델 A**: 한 컨테이너 안에서 여러 Claude(도구) 프로세스 동시 실행. 충돌 방지 위해 **worktree 필수** (§5.5).
- **Docker 명령**: 에이전트 컨테이너 안에서 실행하지 않는다. 컨테이너를 스폰·관리하는 docker는 **호스트 오케스트레이션 층**(§5)이 실행. 따라서 에이전트 컨테이너엔 `docker.sock`을 마운트하지 않으며 **DooD는 채택 안 함** → 격리 유지.

> ⚠️ **왜 DooD를 안 쓰나**: `docker.sock`을 컨테이너에 마운트하면 그 컨테이너는 사실상 호스트 루트 권한을 얻어 격리가 뚫린다. 자율 에이전트 + `--dangerously-skip-permissions` 조합에선 치명적. docker 실행 권한은 신뢰할 수 있는 바깥쪽 오케스트레이터에만 둔다.

---

## 3. 목표 아키텍처

### 3.1 디렉토리 레이아웃 (호스트)

```
~/.agent/                       # 앱 데이터 루트 (ccc의 ~/.ccc에 해당)
├── claude/                     # 디폴트 = 호스트 AI Agent 계정 (사람 ~/.claude와 별개!)
├── claude.json                 # onboarding 상태
├── profiles/
│   ├── bot/claude/             # "bot" 프로파일 크레덴셜
│   └── <name>/claude/
└── locks/                      # 세션 락파일
    ├── <proj>-<hash>--<sessionId>.lock
    └── <proj>--p--bot-<hash>--<sessionId>.lock

Docker named volume:
└── agent-mise-cache            # mise 툴 캐시 (공유, 영속)
└── agent-bin-cache             # claude 바이너리 캐시 (자동 업데이트 영속)

프로젝트 루트 (사용자 저장소):
├── .env                        # 비밀 값. gitignore.
├── .env.example                # 필요한 키 명세. 커밋.
├── .mcp.json                   # 설치할 MCP 서버 목록. 커밋.
├── agent.toml (또는 skills 목록) # 설치할 skills 목록. 커밋.
└── mise.toml                   # 프로젝트 toolchain
```

### 3.2 컨테이너 레이아웃

```
컨테이너 agent-<project>-<hash>[--p--<profile>]
├── /project/<project>-<hash>   # 프로젝트 경로 bind mount, -w 작업 디렉토리
├── /home/agent/.claude         # 도구별 크레덴셜 (호스트 ~/.agent/claude 또는 profiles/<p>/claude)
│   (gemini→~/.gemini, codex→~/.codex 등 도구별 마운트는 registry가 정의 — §4.10)
├── /home/agent/.claude.json    # onboarding 상태
├── /home/agent/.ssh/id_ed25519 # 봇 deploy key (SSH 방식일 때, .env에서 배치 — 호스트 ~/.ssh 아님)
├── /home/agent/.local/share/mise  # named volume (agent-mise-cache)
└── (docker.sock 마운트 없음 · 호스트 gitconfig/ssh 마운트 없음)
```

### 3.3 기술 스택

**오케스트레이터 / 코어 (호스트측 — 우리가 만드는 것): Python**
- **언어**: Python 3.12+
- **docker 제어**: `subprocess`로 docker CLI 호출 (권장, 투명함) 또는 docker SDK for Python.
- **동시성**: `asyncio` — 여러 컨테이너/프로세스 동시 실행·출력 관리. 동시 실행 상한은 세마포어로 (§4.12).
- **CLI 런처**: Typer 또는 Click.

**컨테이너 내부 (AI 도구 실행 환경):**
- 베이스: `ubuntu:24.04`
- **Node.js 필요**: claude/gemini/codex CLI와 `npx` 기반 MCP 서버 구동용(mise 또는 apt로 제공). ← 오케스트레이터가 Python인 것과 **무관**하게, 컨테이너 안 도구들은 Node 런타임이 필요하다.
- Chromium(headless) 등 — §4.1.

**공통:**
- 컨테이너 런타임: Docker (리눅스 고정)
- 네트워크: 기본 bridge (필요 시 `-p` 포트 매핑)

---

## 4. 구성 요소별 명세

### 4.1 이미지 (Dockerfile)

멀티스테이지 + "안 바뀜 → 가끔 바뀜" 레이어 순서로 리빌드 최소화.

**포함:**
- 베이스: `ubuntu:24.04`
- 기본 의존성: `curl git ca-certificates unzip`
- locales + tzdata (자주 쓰는 로케일 미리 생성)
- **Node.js** (mise 또는 apt) — AI CLI(claude/gemini/codex)와 `npx` 기반 MCP 구동에 필요
- **Chromium (headless) + 폰트** — MCP 미동작 시 브라우저 대비책
- **mise** + 전역 툴 (필요 시)
- 비루트 사용자 `agent` (uid 1000) + 홈
- entrypoint 스크립트 (§4.6)
- (오케스트레이터 Python은 **호스트**에 있고 컨테이너 안엔 불필요)

**포함 안 함:**
- X11/xvfb/클립보드/computer-use 스택
- iptables/프록시 데몬
- Docker CLI (DooD OFF 기본)

**런타임 설치 (이미지에 안 굽고, 첫 실행 시 볼륨에 설치):**
- `claude` 네이티브 바이너리 → `agent-bin-cache` 볼륨. `claude update`가 지속되도록.

레이어 순서 예시:
```dockerfile
FROM ubuntu:24.04
# LAYER 1 (거의 안 바뀜): apt 의존성, locales, tzdata
# LAYER 2 (가끔): Chromium + 폰트
# LAYER 3 (가끔): mise + 전역 툴
# LAYER 4 (가끔): agent 사용자 생성, 홈 셋업, passwordless sudo(필요 시)
# LAYER 5 (자주): entrypoint 스크립트 COPY, .bashrc(mise activate)
ENTRYPOINT ["/usr/local/bin/agent-entrypoint.sh"]
```

### 4.2 설정 파일 (선언적 계약)

**`.env`** — 비밀 값만. `KEY=VALUE`. gitignore 필수.
```
ANTHROPIC_API_KEY=sk-...
GITHUB_TOKEN=...
# MCP가 요구하는 키도 여기
```
주입: `docker run --env-file .env ...` (compose면 `env_file:`).
**금지:** Dockerfile `ENV`에 비밀 넣기(이미지에 박힘), compose `environment:`에 값 하드코딩(저장소에 남음).

**`.env.example`** — 커밋. 값 없이 키 이름만. "무슨 키가 필요한가"의 명세.

**`.mcp.json`** — 설치할 MCP 서버. Claude 표준 포맷 재사용.
```json
{
  "mcpServers": {
    "playwright": { "command": "npx", "args": ["-y", "@playwright/mcp", "--headless"] },
    "chrome-devtools": { "command": "npx", "args": ["-y", "chrome-devtools-mcp", "--headless"] }
  }
}
```
- 브라우저 MCP는 여기 **기본값**으로 넣되, headless Chromium이 이미지에 있으니 MCP가 죽어도 직접 구동 대비책이 있다.
- localhost URL **재작성하지 않는다**. 컨테이너 내부 서비스는 컨테이너의 localhost가 맞다.

**skills 목록** — 설치할 skills (이름/repo). 별도 파일 또는 `agent.toml`의 한 섹션.

### 4.3 컨테이너 수명주기

**이름 생성** (참조: `docker.ts:183`, `utils.ts:74`)
```
projectId = <basename(경로) 소문자·정규화>-<sha256(절대경로)[:12]>
컨테이너명 = agent-<projectId>[--p--<profile>]
```
결정적 → 같은 프로젝트는 항상 같은 컨테이너 → `claude --continue`/`--resume` 동작.

**세션 락파일** (참조: `session.ts:38`)
- 실행마다 `~/.agent/locks/<prefix>--<sessionId>.lock` 생성, 내용 = PID.
- `prefix` = 프로파일 있으면 `<projectId>--p--<profile>`, 없으면 `<projectId>`.

**레퍼런스 카운팅 + 자동 정리** (참조: `session.ts:136`)
```
종료 시:
  1. 다른 활성 세션 있나? (같은 prefix의 락파일 중 살아있는 PID)
  2. 내 락파일 삭제
  3. 다른 세션 없으면 → 컨테이너 stop (+ claude 바이너리 볼륨 저장)
```

**크래시 복구** (참조: `session.ts:57`, `getActiveSessionsForContainer`)
- 락파일 열거 시 PID 생존 확인 — Python: `os.kill(pid, 0)` → `ProcessLookupError`면 죽음, `PermissionError`면 살아있음.
- 죽은 PID의 stale 락은 즉시 삭제 → 유령 세션이 컨테이너를 붙잡지 않게.

**시그널 핸들링** (참조: `session.ts:170`)
- `SIGINT`/`SIGTERM`/`SIGHUP` → cleanup → 종료. Python: `signal.signal(...)` + `atexit`.
- "이미 정리함" 플래그로 중복 정리 방지.

**고아(orphan) GC** — 세션 카운팅 보완
- 세션 카운팅은 "정상/시그널 종료"를 잡지만, 오케스트레이터·호스트가 강제 종료되면 컨테이너가 남을 수 있다.
- 주기적(또는 부팅 시) GC: 활성 락파일이 하나도 없는데 실행 중인 `agent-*` 컨테이너 → stop/rm.
- 참조하는 소스가 사라진 worktree, 오래된 로그도 함께 청소. 캐시 볼륨(mise/bin)은 보존.

### 4.4 크레덴셜 격리 + 프로파일 (AI 계정)

**로그인은 항상 공유, 플러그인/스킬 설치 상태는 프로젝트별로 기본 격리.** 이 둘은 서로 다른 마운트/분리 규칙을 따른다 (2026-07 변경 — 예전엔 둘 다 프로파일 미지정 시 통째로 공유했다).

- **로그인(`.claude.json`)**: `--profile` 지정 여부와 무관하게 항상 `~/.agent/claude.json`(또는 `--profile <name>` 지정 시 `~/.agent/profiles/<name>/claude.json`)에 공유. 한 번 로그인하면 그 프로파일을 쓰는 모든 프로젝트에서 그대로 유효 — 재로그인 강제 없음.
- **플러그인/스킬 설치 상태(`.claude` 디렉토리)**: **디폴트(미설정)**는 `project_id` 기준 자동 분리 = `~/.agent/profiles/<project_id>/claude` → 컨테이너 `/home/agent/.claude` bind mount. 한 프로젝트 컨테이너에서 설치한 플러그인이 다른 프로젝트 컨테이너로 새지 않는다.
- **명시적 공유(`--profile <name>` 또는 `AGENT_PROFILE`)**: `~/.agent/profiles/<name>/claude`로 대체 — 같은 이름을 여러 프로젝트에 쓰면 그 프로젝트들끼리 플러그인 상태를 의도적으로 공유/복사하는 효과. 컨테이너 이름에도 `--p--<name>` 접미사가 붙는다.
- 첫 사용 시 그 컨테이너 안에서 1회 로그인 → bind mount로 영속. 컨테이너가 죽어도 로그인 유지.
- 멀티툴(§4.10)이면 계정 저장소는 도구별로 분리(claude→`.claude`, codex→`.codex` …). 이 프로젝트별 자동 분리 규칙은 모든 도구의 크레덴셜 디렉토리에 동일하게 적용된다 (로그인 공유 예외는 claude의 `.claude.json`에만 해당).
- **호스트 사전 설치 (`src/agentpod/plugins.py: seed_superpowers`)**: 컨테이너가 뜨기 직전, 호스트에 있는 `claude` CLI로 그 프로젝트의 격리된 creds 디렉토리에 superpowers를 미리 설치·활성화해둔다(`CLAUDE_CONFIG_DIR` 환경변수로 대상 지정) — 그러면 컨테이너 안 entrypoint(§4.6)의 설치 단계는 대부분 "이미 있음"을 보고 건너뛰어, 매 컨테이너 부팅마다 git clone하지 않아도 된다. best-effort: 호스트에 `claude`가 없거나, 설치 결과가 불완전하면(예: 크로스-OS `claude` 바이너리가 `CLAUDE_CONFIG_DIR`를 잘못 해석해 마켓플레이스 등록만 되고 실제 플러그인 파일은 못 받아온 경우) 만든 것을 전부 롤백하고 컨테이너 entrypoint의 설치로 폴백한다.
- **팀원과 공유 (`agentpod export`)**: 위 상태는 전부 호스트에만 남아 `git clone`으로 안 옮겨진다. `agentpod export`가 현재 프로젝트에 설치된 플러그인/스킬(baseline인 superpowers는 제외)을 `agent.toml`의 `[[skills]]`로, `claude mcp add`로 붙인 MCP 서버를 `.mcp.json`으로 스냅샷한다. MCP의 `env`/헤더 값은 `${VAR}` 플레이스홀더로 치환되고 실제 값은 `.env`(gitignore)로 분리되어 시크릿이 커밋 파일에 박히지 않는다.

### 4.5 Git 신원 (전용 봇 신원 — 호스트 의존 없음)

호스트의 사람 신원을 빌려오지 않는다. 자율 에이전트는 **전용 봇 계정**으로 커밋·push한다.

**인증 (push/pull)** — 둘 중 택1, `.env`로 주입:
- **PAT/토큰 방식**: `GITHUB_TOKEN`(또는 GitLab 등) → `.env`. git이 `https://x-access-token:$TOKEN@github.com/...` 형태로 사용하거나 `gh auth`로 설정.
- **SSH deploy key 방식**: 봇 전용 개인키를 `.env`(base64) 또는 시크릿 마운트로 주입 → 컨테이너 안 `~/.ssh/id_ed25519`에 배치, `GIT_SSH_COMMAND`로 지정. 호스트 `~/.ssh`는 **마운트하지 않는다.**

**신원 (커밋 작성자)** — 매니페스트/설정에 봇 값 명시:
```
user.name  = "agent-bot"
user.email = "agent-bot@users.noreply.github.com"
```
컨테이너 초기화 시 `git config --global user.name/email`로 설정 + `git config --global --add safe.directory '*'`.

**이점**
- 커밋 히스토리에서 "봇이 한 일"과 "사람이 한 일"이 명확히 구분됨 (감사).
- 사람 개인키를 자율 에이전트에 노출하지 않음.
- 호스트 gitconfig/ssh에 의존하지 않음 → 어디서 실행해도 동일. **§1 "완전한 호스트 독립" 달성.**

> 봇 계정에 부여하는 권한은 최소로 (필요한 repo만 push). 토큰/키 회전 정책도 세울 것.

### 4.6 entrypoint

컨테이너 시작 시 1회 실행 (참조: `agent-entrypoint.sh`).
```bash
#!/bin/bash
set -euo pipefail
# 1. 봇 git 신원 설정: git config --global user.name/email (봇 값) + safe.directory '*'
# 2. 봇 인증 배치: .env의 SSH deploy key를 ~/.ssh/에 쓰거나 토큰 기반 credential 설정
# 3. .mcp.json / skills 매니페스트 읽어 MCP·skills 설치
# 4. (프록시/iptables 없음 — 이 프로젝트는 제외)
# 5. exec "$@"   # 사용자/디스패처 명령 실행
```
- iptables/프록시 로직 전부 제거 (기본 bridge 네트워크).
- 호스트 gitconfig/ssh 스테이징 없음 (봇 신원으로 대체).

### 4.7 네트워크

- **기본 bridge.** `--network host` 안 씀.
- 컨테이너 내부에서 `localhost` = 컨테이너 자신. 재작성 없음.
- 호스트에서 접속이 필요해지면 그때만 `-p <host>:<container>` 포트 매핑 추가.

### 4.8 MCP / skills 자동 설치

- 컨테이너 빌드/셋업(또는 entrypoint 이후 초기화 단계)에서 `.mcp.json` + skills 목록을 읽어 설치.
- MCP: Claude가 읽는 위치(`~/.claude.json`의 `mcpServers` 또는 프로젝트 `.mcp.json`)에 배치.
- MCP가 요구하는 API 키는 `.env`에서 이미 주입됨.
- skills: 이름/repo 기반 설치 (plugin/디렉토리).

**skills 매니페스트 스키마** (예 — `agent.toml`의 한 섹션 또는 별도 `skills.toml`):
```toml
[[skills]]
name = "my-skill"           # 식별자
source = "github:org/repo"  # git repo, 또는 "npm:pkg", 또는 로컬 경로
ref = "main"                # (선택) 브랜치/태그/커밋
enabled = true
```
- 설치 단계(entrypoint 또는 셋업)가 이 목록을 순회하며 clone/설치 → Claude가 읽는 skills 위치에 배치.
- 컨테이너별 MD 컨텍스트(§4.11)와 별개: skills는 "실행 능력", MD 컨텍스트는 "참고 문서".

### 4.9 mise 통합

- 프로젝트 `mise.toml`로 toolchain 선언 (참조: CLAUDE.md).
- `mise install`을 에이전트 실행 전에 자동 수행.
- 캐시는 named volume `agent-mise-cache`에 → 컨테이너 재생성해도 재사용.
- `MISE_TRUSTED_CONFIG_PATHS`를 컨테이너 생성 시 주입해 `mise trust` 생략 (참조: `docker.ts:137`).

### 4.10 멀티 에이전트 registry

여러 AI 코딩 CLI(claude/gemini/codex/opencode)를 지원한다. 도구별 차이를 **단일 registry에 데이터로** 모아, 나머지 코드는 도구 종류를 구분하지 않게 한다 (참조: `tool-registry.ts:33`).

**도구 하나의 정의 (`ToolDefinition`)** — 참조: `tool-registry.ts:12`
```
name              # "claude" | "gemini" | "codex" | "opencode"
binary            # 실행 바이너리 경로
defaultFlags      # 자율 실행 플래그 (claude: --dangerously-skip-permissions,
                  #   gemini: --yolo, codex: --dangerously-bypass-approvals-and-sandbox)
credentialMounts  # 도구별 크레덴셜 마운트 (호스트 경로 ↔ 컨테이너 경로)
installCommand    # 설치 명령 (curl|bash 또는 npm i -g ...)
updateCommand     # 업데이트 명령
subcommands?      # (codex처럼) 서브커맨드별 플래그 처리 특수성 흡수
```

**핵심 원칙 (개방-폐쇄)**: 새 도구 추가 = registry 배열에 객체 하나 추가. 실행/마운트/설치 로직은 수정 불필요.

**주의 — 도구별 자율 플래그**: 각 도구의 "자율 실행 플래그"는 §1 원칙(격리로 감싼다)이 그대로 적용된다. 어느 도구든 컨테이너 밖에서 이 플래그를 쓰면 안 된다.

**도구 선택**: `--tool <name>` 또는 요청 메타데이터로 지정. 미지정 시 기본값(claude).

### 4.11 컨테이너별 MD 컨텍스트

각 컨테이너(=프로젝트)가 **자기만의 MD 문서 세트**를 참조하게 한다. 컨테이너마다 바라보는 지침/문서가 다르고, 파일·폴더로 쉽게 만들고 관리한다.

**호스트 구조** — **컨테이너별 완전 독립 폴더** (공통/오버라이드 계층 없음):
```
~/.agent/contexts/
├── <projectId>/                     # 이 컨테이너만 바라보는 MD
│   ├── CLAUDE.md                    # 에이전트 지침
│   └── *.md                         # 참고 문서
└── <projectId>--p--<profile>/       # 프로파일 컨테이너는 별도 독립 폴더
```
- 폴더 하나 = 컨테이너 하나. 다른 컨테이너의 MD를 상속·참조하지 않는다. (요구사항: 완전 독립)

**마운트 & 인식**
- 컨테이너 식별자에 해당하는 폴더 **하나만** 컨테이너 고정 경로(예: `/home/agent/context`)에 bind mount.
- 폴더가 없으면 빈 컨텍스트(마운트 생략 또는 빈 폴더). 폴백 없음.
- 에이전트가 읽도록: 프로젝트 루트 `CLAUDE.md`로 심거나 컨텍스트 디렉토리를 실행 인자로 지정.

**관리 용이성 (요구사항)**
- 평범한 `.md` 파일 + 폴더 하나 = 새 컨테이너 컨텍스트. 코드 수정 없음.
- 컨테이너 식별자 규칙(§3.1)과 폴더명을 1:1 매칭 → "어느 컨테이너가 무슨 MD를 보는지" 자명.
- 컨텍스트 폴더는 호스트의 평범한 디렉토리 → 에디터·CLI로 직접 편집. 런처에 `agent context <id>`(경로 출력/열기) 같은 명령을 두면 더 편함.

### 4.12 리소스 제한 & 격리 상한 (자율 실행 필수)

ccc는 리소스 무제한(호스트 공유)이지만, **자율 폭주가 호스트를 마비시킬 수 있으므로 상한이 필수**다.

- **컨테이너별 상한** (`docker run` 시): `--memory`, `--cpus`, `--pids-limit`. 프로젝트/프로파일별로 다르게 설정 가능.
- **호스트 전체 상한** (오케스트레이터가 강제):
  - 동시 실행 **컨테이너 수** 상한.
  - **컨테이너당 동시 태스크(프로세스) 수** 상한 (모델 A — 한 컨테이너 다중 프로세스).
  - 초과 시 대기 또는 거부 (§5.6).
- 디스크: mise/bin 캐시 볼륨은 공유(영속)지만, worktree·로그는 주기적 GC(§4.3).

---

## 5. 다중 격리 에이전트 실행 (사용자 명령 기반)

목표: **격리된 에이전트 컨테이너를 CLI로 쉽게 여러 개** 띄우고 다룬다. 각 컨테이너의 에이전트는 **자기 MD 컨텍스트(§4.11) + 사용자 명령**으로만 움직인다. 웹 UI·채팅·자동 잡 큐는 없다.

> 여기서 "자율"은 *에이전트가 한 태스크 안에서 권한 확인 없이 스스로 수행*(§1, `--dangerously-skip-permissions`)을 뜻하지, *시스템이 알아서 일감을 만든다*는 뜻이 아니다. **트리거는 항상 사용자**.

### 5.1 실행 흐름

```
사용자 (CLI)
   │  agent [--tool T] [--profile P] ["<명령>"]     # 프로젝트 경로 기준
   ▼
런처(호스트, Python): 컨테이너 이름 계산 → 스폰/재사용 (docker)
   │
   ▼
컨테이너 안에서 도구 실행 (MD 컨텍스트 §4.11 + 사용자 명령)
   ├─ 인터랙티브:  agent / agent shell      (사람이 대화하며 진행)
   └─ 헤드리스 1회: agent -p "<task>"        (실행 후 결과 출력)
   │
   ▼
결과·로그 → stdout + 로그 파일 (§5.6)
```
- 진입점은 **CLI 하나**. 웹·채팅·큐 없음. 여러 컨테이너를 쉽게 관리(§5.3).

### 5.2 실행 모드 (사용자 선택)

- **인터랙티브**: `agent`(기본 도구로 대화) / `agent shell`(컨테이너 셸). ccc처럼 사람이 붙어서 진행.
- **헤드리스 1회**: `agent -p "<task>"` — 도구를 print 모드로 실행 후 결과 출력.
  ```bash
  # 런처가 컨테이너 안에서 조립·실행
  claude -p "<task>" --dangerously-skip-permissions \
    --output-format stream-json --allowedTools "Read,Write,Edit,Bash"
  ```
  - `stream-json`으로 진행/결과를 구조적으로 캡처 → 로그 저장(§5.6).
  - **참고 자산**: ccc는 이미 `claude -p --allowedTools Read,Write`를 `mise.toml` 자동 생성에 쓴다(`index.ts`) — 작동하는 헤드리스 예시.
  - 멀티툴: gemini/codex는 자율 플래그·출력 포맷이 다름 → registry(§4.10)로 조립. 정확한 플래그는 각 도구 `--help` 확인.

### 5.3 다중 컨테이너 관리 (핵심 편의)

"쉽게 다수 사용"의 실체 = 여러 격리 컨테이너를 한 CLI로 다루는 것. 런처는 **호스트에서 실행되는 신뢰 계층**이며 `docker`(스폰/정지/제거)는 여기서만 나간다 (§2.4).

- `agent [--tool T] [--profile P] [명령]` — 프로젝트 경로 기준으로 컨테이너 이름 계산 → 스폰/재사용 → 실행.
- `agent status` — 모든 `agent-*` 컨테이너 목록·상태.
- `agent stop <id>` / `agent rm <id>` — 개별 정리.
- 컨테이너는 결정적 이름(§4.3) → 같은 프로젝트/프로파일로 다시 들어가면 세션·컨텍스트가 이어짐.
- 도구별 실행은 registry(§4.10)에서 바이너리·플래그 조회해 조립.
- 커밋/PR 등 후처리는 사용자가 명령으로 지시 (봇 신원 §4.5).

### 5.4 복원력 (선택)

헤드리스 실행이 한 번의 오류(도구 상태 불일치 등)로 멈추지 않도록: **자동 업데이트 → 재시도 → 상태 초기화** 사다리 (참조: ccc `index.ts`). 사용자가 긴 헤드리스 작업을 돌릴 때 이식 가치.

### 5.5 병렬 처리 — 모델 A (확정)

**한 컨테이너 안에서 여러 Claude(도구) 프로세스를 동시 실행**한다. 컨테이너는 여전히 프로젝트당 1개(경로 해시), 그 안에서 태스크마다 프로세스가 뜬다.
```
컨테이너 agent-<proj>-<hash>  (프로젝트 1개)
├── claude -p "버그 수정"    → worktree /project--fix-bug   (fix-bug 브랜치)
├── claude -p "기능 추가"    → worktree /project--add-feat  (add-feat 브랜치)
└── claude -p "리팩터링"     → worktree /project--refactor  (refactor 브랜치)
   ※ .git 히스토리 공유, 작업 파일만 분리
```

**worktree 필수 (충돌 방지)**
- 여러 프로세스가 같은 작업 디렉토리를 공유하면 같은 파일을 동시 수정 → 덮어씀. 그래서 **태스크마다 별도 브랜치 + 별도 worktree**를 준다 (참조: `worktree.ts`).
- 모델 A에선 **원본 저장소와 worktree가 같은 컨테이너 파일시스템**에 있으므로, worktree의 `.git` gitlink 참조가 컨테이너 안에서 그대로 해석됨 → ccc의 교차-마운트 보정(`getWorktreeGitMounts`)이 대부분 불필요. (worktree를 컨테이너 안에서 생성하는 한.)
- `.gitignore`된 것(`node_modules` 등)은 worktree에 안 따라오므로 태스크 시작 시 필요한 설치를 다시 수행.

**세션 수명주기와의 연동**
- 각 동시 태스크 = 세션 락 1개 (§4.3). 여러 프로세스가 한 컨테이너를 공유하는 것은 ccc의 "멀티 세션 한 컨테이너" 모델 그대로.
- 마지막 태스크(세션)가 끝나면 컨테이너 stop.

**공유 상태 — 직렬화로 흡수 (허용된 방침)**: 한 컨테이너의 여러 프로세스는 홈/크레덴셜/mise 캐시를 공유하므로 race가 날 수 있다. worktree로 *작업 파일*은 이미 분리되므로, **공유 상태를 건드리는 구간(설치·로그인·mise install 등)만 컨테이너별 락으로 직렬화**하면 된다. race가 있어도 **차례차례 처리되면 무방** — 병렬을 강제하지 않는다. 필요하면 프로세스별 HOME 서브디렉토리 분리도 가능.

**주의 — 장애 격리**: 한 컨테이너를 공유하므로 컨테이너가 죽으면 그 안 프로세스 전부 죽는다. 자원 경합(CPU/메모리)도 공유 → 태스크 수 상한·리소스 제한(§4.12·§5.6).

### 5.6 실행 안전 (필수)

**최우선 불변식: 무한 멈춤(hang) 절대 금지.** race·경합은 직렬화로 흡수하면 되지만(§5.5), 멈춰서 안 끝나는 것은 안 된다.

`--dangerously-skip-permissions`로 도는 데다 컨테이너를 여러 개 띄우므로:

- **타임아웃 2종 + 강제 kill** ← 무한 로딩 방지의 핵심:
  - **벽시계 타임아웃**: 태스크 전체 실행 시간 상한.
  - **무진행(idle) 타임아웃**: stream-json 출력이 일정 시간 없으면 hang으로 간주.
  - 둘 중 하나라도 초과 → 프로세스 강제 kill + worktree 정리 + 실패 기록.
- **직렬화 락 자체에도 타임아웃**: 공유 상태 락(§5.5) 대기가 무한정 걸리지 않게 대기 상한 → 초과 시 실패 처리(교착 방지).
- **동시 실행 상한 (max concurrency)**: 호스트 동시 컨테이너 수 + 컨테이너당 동시 프로세스 수(모델 A) 상한. (§4.12)
- **리소스 제한**: 컨테이너별 `--memory`/`--cpus`/`--pids-limit`. (§4.12)
- **감사 로그(audit)**: 언제·어느 컨테이너에·무슨 명령을 실행했고 결과가 무엇인지 기록. 봇 신원(§4.5)·"감사 명확"(§1)과 연결. 프롬프트·커밋 해시·종료 코드를 남긴다.
- **관측성**: 실행 로그(stream-json 원본)를 저장하고 조회 가능한 위치에. 실패 사후 분석 경로 확보.

---

## 6. 보안 체크리스트

- [ ] 도구별 자율 플래그(`--dangerously-skip-permissions`, `--yolo` 등)는 **컨테이너 안에서만**. 호스트에서 절대 금지.
- [ ] `.env`는 gitignore. 비밀을 이미지/compose/저장소에 하드코딩하지 않음.
- [ ] `docker.sock`은 에이전트 컨테이너에 마운트하지 않음. docker 실행은 호스트 오케스트레이터에만.
- [ ] `--network host` 미사용. 기본 bridge로 네트워크 격리.
- [ ] 크레덴셜은 호스트 `~/.claude` 등이 아닌 `~/.agent/...`에 격리. 봇 AI 계정은 프로파일로 분리.
- [ ] git 인증은 **전용 봇 신원**(deploy key/토큰). 사람 개인키·호스트 gitconfig를 컨테이너에 넣지 않음.
- [ ] 봇 계정 권한 최소화(필요 repo만) + 토큰/키 회전 정책.
- [ ] **실행 권한**: 런처(호스트)를 실행 가능한 사용자만 에이전트를 구동 — 호스트 OS/도커 접근 통제에 의존.
- [ ] **감사 로그**: 시각·컨테이너·명령·결과(커밋 해시/종료 코드) 기록 (§5.6).
- [ ] **리소스 상한**: 컨테이너별 memory/cpu/pids + 동시성 상한 설정 (§4.12) — 폭주로 호스트 마비 방지.
- [ ] **태스크 타임아웃**: 멈춘/폭주 태스크를 강제 종료하는 상한 (§5.6).

---

## 7. 구현 로드맵

**Phase 1 — 최소 뼈대** (Python 코어 + 이미지)
1. Dockerfile (§4.1) — ubuntu + curl/git + Node.js + Chromium(headless) + mise + agent 사용자.
2. 컨테이너 이름/세션 수명주기 (§4.3) — 락파일, 레퍼런스 카운팅, 크래시 복구, 시그널.
3. 크레덴셜 격리 + bind mount (§4.4, 프로파일은 후순위 가능).
4. Python CLI 런처(Typer/Click): `agent`(실행), `agent shell`, `agent stop/rm/status` + 멀티툴 registry (§4.10).

**Phase 2 — 선언적 설정 + 신원 + worktree**
5. `.env` / `.mcp.json` / skills 매니페스트 로딩 + 설치 (§4.2, §4.8).
6. 전용 봇 git 신원 (토큰/deploy key + 봇 user.name/email) (§4.5).
7. mise 통합 + 볼륨 캐시 (§4.9).
8. worktree 생성/제거 (§5.5) — 태스크별 브랜치+작업폴더 격리 (모델 A 전제).
9. 컨테이너별 MD 컨텍스트 마운트 (§4.11).
10. 리소스 제한 (memory/cpu/pids) (§4.12).

**Phase 3 — 자율 오케스트레이션 + 안전장치**
11. 헤드리스 실행 (`claude -p`) + `asyncio` 동시 실행 관리 (§5) — 호스트에서 docker 스폰.
12. 한 컨테이너 안에서 태스크별 worktree + 프로세스 동시 실행 (모델 A, §5.5).
13. 결과 캡처 + 커밋/PR 후처리 (봇 신원).
14. **실행 안전 (§5.6)**: 타임아웃+kill, 동시성 상한, 감사 로그, 관측성(로그 저장).
15. 복원력 사다리 (§5.4) + 고아 GC (§4.3).

**Phase 4 — 품질**
16. 테스트 전략(pytest): 순수 함수(이름 해시·세션 카운팅·매니페스트 파싱) 유닛 + 컨테이너 수명주기 통합 테스트 (참조: ccc `__tests__/`).

---

## 8. 결정 완료 (초기 열린 질문의 답)

1. **병렬 처리 → 모델 A 확정**: 한 컨테이너 안에서 여러 Claude(도구) 프로세스를 동시 실행. 충돌 방지를 위해 **worktree 필수** → Phase 2로 편입. (§5.5)
2. **DooD → 채택 안 함**: docker 명령은 호스트 오케스트레이션 층이 실행. 에이전트 컨테이너엔 `docker.sock` 없음. (§2.4)
3. **멀티툴 → 채택**: claude/gemini/codex/opencode를 registry로 지원. (§4.10)
4. **git 신원 → 전용 봇 신원**: deploy key/토큰 + 봇 user.name/email. 완전한 호스트 독립. (§4.5)

---

*근거 참조(`파일:라인`)는 claude-code-container 저장소 기준. 이 가이드의 결정 사항은 [ccc-extract.html](ccc-extract.html)의 티어 분석과 이 프로젝트의 divergence 결정을 반영한다.*
