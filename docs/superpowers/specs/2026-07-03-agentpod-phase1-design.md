# AgentPod — Phase 1 설계 스펙

> 상위 명세: [BUILD-GUIDE.md](../../dev/BUILD-GUIDE.md)
> 이 문서는 BUILD-GUIDE의 **Phase 1 + 컨테이너별 MD 컨텍스트(§4.11)** 범위를 이번 마일스톤의 구현 스펙으로 좁힌 것이다.
> 언어: 오케스트레이터는 Python, 컨테이너 내부 도구는 Claude Code(Node 런타임).

---

## 0. 이번 마일스톤의 한 문장

**"WSL2/Linux 호스트에서 `agentpod` CLI가 프로젝트마다 격리된 Docker 컨테이너를 하나씩 띄우고, 그 안에서 Claude Code를 실행한다 — 결정적 이름·세션 카운팅 자동 정리·크레덴셜 격리·컨테이너별 MD 컨텍스트까지 끝단간 동작."**

---

## 1. 범위 (확정)

### 1.1 포함 (이번 마일스톤)

- Dockerfile — 에이전트 컨테이너 이미지 (ubuntu:24.04 + Node + git + agent 사용자 + entrypoint)
- Python CLI 런처 (`agentpod`): `run` / `shell` / `status` / `stop` / `rm` / `context` / `build`
- 결정적 컨테이너 이름 (경로 해시) — §4.3
- 세션 락파일 + 레퍼런스 카운팅 + 크래시 복구 + 시그널 정리 — §4.3
- 크레덴셜 격리 (기본 = 호스트 AI Agent 계정 `~/.agent/claude` 바인드 마운트) — §4.4
- 인증 **두 방식 모두**: API 키(`.env` → `--env-file`) + 대화형 로그인(바인드 마운트 영속)
- 컨테이너별 MD 컨텍스트 마운트 + 자동 주입 — §4.11
- 최소 멀티툴 registry (claude 항목 하나) — §4.10
- pytest 유닛 테스트 (순수 함수: 이름 해시, 세션 카운팅, registry)

### 1.2 제외 (Phase 2/3로 연기 — YAGNI)

| 항목 | 연기 이유 |
|------|-----------|
| Chromium(headless) + 폰트 | MCP 미동작 대비책일 뿐. MCP가 Phase 2 → 지금 불필요. 이미지 슬림·빌드 빠름 |
| 프로파일(다중 신원) | 경로/이름 규칙은 미리 설계해 두되 구현은 Phase 2 |
| `.mcp.json` / skills 설치 | Phase 2 (§4.8) |
| 봇 git 신원 (토큰/deploy key) | Phase 2 (§4.5). 이번엔 `safe.directory` 설정만 |
| mise 통합 + 볼륨 캐시 | Phase 2 (§4.9) |
| worktree + 헤드리스/병렬 실행 (모델 A) | Phase 3 (§5.5) |
| 리소스 제한 (memory/cpu/pids) | Phase 2/3 (§4.12). 이번엔 미적용 |
| 고아 GC, 복원력 사다리 | Phase 3 |

> **연기 원칙**: 제외 항목이라도 경로 레이아웃·이름 규칙·registry 스키마는 확장 가능하게 설계해 나중에 코드 수정 없이/최소로 끼워지도록 한다.

---

## 2. 기술 결정

| 영역 | 결정 | 근거 |
|------|------|------|
| 오케스트레이터 언어 | Python 3.12+ | BUILD-GUIDE §3.3 |
| CLI 프레임워크 | **Typer** | 타입힌트 기반, 서브커맨드 깔끔, 스펙 허용안 |
| Docker 제어 | **`subprocess` + `docker` CLI** | 투명, SDK 의존성 없음, 스펙 권장 |
| 패키지 구조 | `src/` 레이아웃 | 표준, import 오염 방지 |
| 테스트 | pytest | 스펙 §7 Phase 4 |
| 호스트 타깃 | WSL2/Linux + Docker | 스펙 §1 "Linux 고정" |

---

## 3. 호스트 디렉토리 레이아웃 (`~/.agent`)

```
~/.agent/
├── claude/                     # 디폴트 AI Agent 계정 크레덴셜 → 컨테이너 /home/agent/.claude
├── claude.json                 # onboarding 상태 → 컨테이너 /home/agent/.claude.json
├── contexts/
│   └── <projectId>/            # 이 컨테이너만 보는 MD (§4.11). 사용자가 직접 채움
│       ├── CLAUDE.md           # (선택) 에이전트 지침 → 자동 주입
│       └── *.md                # (선택) 참고 문서
└── locks/
    └── <projectId>--<sessionId>.lock   # 내용 = PID
```

- `~/.agent`가 없으면 CLI가 최초 실행 시 생성한다 (paths.py).
- 프로파일 경로(`~/.agent/profiles/<name>/`)는 이번엔 만들지 않지만 naming/credentials가 접미사를 인식하도록 설계.

---

## 4. 컨테이너 레이아웃

```
컨테이너 agent-<projectId>
├── /project/<projectId>            # 프로젝트 경로 bind mount (rw), 작업 디렉토리(-w)
├── /home/agent/.claude             # ~/.agent/claude bind mount (rw) — 로그인 영속
├── /home/agent/.claude.json        # ~/.agent/claude.json bind mount (rw) — onboarding
├── /home/agent/context             # ~/.agent/contexts/<projectId> bind mount (ro) — MD
└── (docker.sock 없음 · 호스트 gitconfig/ssh 없음 · Chromium 없음)
```

환경변수: `.env`가 프로젝트 루트에 있으면 `--env-file`로 주입.

---

## 5. 구성 요소별 스펙

### 5.1 naming.py — 결정적 이름 (§4.3)

```
projectId  = <basename(절대경로) 소문자·[a-z0-9-]로 정규화>-<sha256(절대경로)[:12]>
containerName = "agent-" + projectId
lockPrefix = projectId            # (프로파일 도입 시: projectId + "--p--" + profile)
```

- 경로는 `os.path.realpath`로 정규화 후 해시(심볼릭 링크 흔들림 방지).
- basename에서 영숫자·하이픈 외 문자는 `-`로 치환, 연속 `-` 축약, 소문자화.
- **순수 함수** → 유닛 테스트 대상.

### 5.2 paths.py — 앱 데이터 레이아웃

- `agent_root()` = `$AGENT_HOME` 또는 `~/.agent`.
- `ensure_layout()` = `claude/`, `contexts/`, `locks/` 디렉토리 생성 (idempotent).
- `context_dir(projectId)`, `locks_dir()`, `claude_creds_dir()`, `claude_json_path()` 헬퍼.

### 5.3 docker_ctl.py — subprocess 래퍼

각 함수는 `docker` CLI를 `subprocess`로 호출하고 반환코드/출력을 다룬다.

- `image_exists(tag) -> bool` — `docker image inspect`
- `build_image(dockerfile, context, tag)` — `docker build`
- `container_state(name) -> "running"|"exited"|None` — `docker inspect -f {{.State.Status}}`
- `run_detached(name, mounts, env_file, workdir, image)` — `docker run -d`로 컨테이너 생성(장기 실행: `sleep infinity` 또는 `tail -f /dev/null`을 PID1로)
- `exec_interactive(name, cmd)` — `docker exec -it`로 도구 실행 (TTY 상속)
- `stop(name)` / `rm(name)` — `docker stop`/`docker rm`
- `list_agents() -> [dict]` — `docker ps -a --filter name=agent- --format`

> **컨테이너 모델**: 컨테이너는 PID1로 대기 프로세스(`sleep infinity`)를 돌려 살아있게 하고, 실제 도구(claude)는 `docker exec`로 붙인다. 이래야 한 컨테이너에 여러 세션(향후 모델 A)이 붙고 세션 카운팅으로 stop을 제어할 수 있다. entrypoint는 컨테이너 시작 시 1회 초기화 후 `exec "$@"`(=대기 프로세스).

### 5.4 session.py — 세션 수명주기 (§4.3)

- `create_lock(prefix) -> Path` : `locks/<prefix>--<sessionId>.lock` 생성, 내용 = 현재 PID. `sessionId`는 `uuid4` 또는 `pid+monotonic` 기반 유니크 값.
- `active_sessions(prefix) -> [Path]` : 같은 prefix 락 열거 후 **살아있는 PID만** 반환.
  - PID 생존: `os.kill(pid, 0)` → `ProcessLookupError`=죽음, `PermissionError`=살아있음, 성공=살아있음.
  - 죽은 PID 락은 즉시 삭제 (stale 청소, 크래시 복구).
- `release_lock(prefix, lock, container)` : 내 락 삭제 → 다른 활성 세션 없으면 `docker stop`.
- `install_signal_handlers(cleanup)` : `SIGINT`/`SIGTERM`/`SIGHUP` + `atexit.register`. `_cleaned` 플래그로 중복 정리 방지.
- **순수 로직(active_sessions의 PID 필터, 이름 파싱)** → 유닛 테스트. `os.kill`은 monkeypatch.

### 5.5 registry.py — 최소 멀티툴 registry (§4.10)

```python
@dataclass(frozen=True)
class ToolDefinition:
    name: str                      # "claude"
    binary: str                    # "claude"
    default_flags: list[str]       # ["--dangerously-skip-permissions"]
    install_command: list[str]     # 런타임 설치 (Phase 1은 이미지/entrypoint에서 처리 가능)
    update_command: list[str]
    credential_mounts: list[tuple[str, str]]  # (호스트경로, 컨테이너경로)

REGISTRY = {"claude": ToolDefinition(...)}
DEFAULT_TOOL = "claude"
```

- 새 도구 추가 = dict에 객체 하나. 실행/마운트 로직은 registry를 읽을 뿐 도구 종류를 분기하지 않음.
- 이번 마일스톤은 `claude`만 채운다. gemini/codex는 Phase 후속.

### 5.6 context.py — MD 컨텍스트 (§4.11)

- `resolve_mount(projectId) -> tuple[str,str] | None` : `contexts/<projectId>`가 존재하면 `(호스트경로, "/home/agent/context")` ro 마운트, 없으면 `None`(마운트 생략, 폴백 없음).
- 자동 주입은 **entrypoint**가 담당 (5.8).

### 5.7 cli.py — Typer 앱 (`agentpod`)

| 커맨드 | 동작 |
|--------|------|
| `agentpod build [--force]` | 이미지 `agentpod:latest` 빌드. 존재하면 skip(--force로 강제) |
| `agentpod run [--tool claude] [-- <extra args>]` | (cwd 기준) 이미지 없으면 안내→빌드, 컨테이너 스폰/재사용, 세션 락 생성, `docker exec -it`로 `claude <default_flags> <extra>` 실행. 종료 시 세션 릴리스 |
| `agentpod shell` | 같은 컨테이너에 `bash` 대화형 접속 (디버깅). 세션 락 동일 적용 |
| `agentpod status` | 모든 `agent-*` 컨테이너 목록·상태 + 활성 세션 수 |
| `agentpod stop <projectId\|.>` | 컨테이너 stop (수동) |
| `agentpod rm <projectId\|.>` | 컨테이너 stop+rm |
| `agentpod context [<projectId\|.>]` | 해당 컨테이너의 컨텍스트 폴더 경로 출력(없으면 생성 안내) |

- `run`/`shell`은 cwd를 프로젝트 경로로 간주 → naming으로 컨테이너 이름 계산.
- `stop`/`rm`/`context`에 `.` = cwd 기준.
- 인증: 프로젝트 루트에 `.env` 있으면 `--env-file`. `~/.agent/claude`는 항상 마운트(로그인 영속).

### 5.8 Dockerfile + entrypoint

**Dockerfile (레이어 순서, §4.1 축약판):**
```dockerfile
FROM ubuntu:24.04
# LAYER 1 (거의 안 바뀜): apt — curl git ca-certificates unzip locales tzdata
# LAYER 2 (가끔): Node.js (apt 또는 nodesource) — claude CLI 구동용
# LAYER 3 (가끔): agent 사용자(uid 1000) + 홈 + .claude 디렉토리
# LAYER 4 (자주): entrypoint COPY, claude CLI 설치(npm i -g @anthropic-ai/claude-code)
ENTRYPOINT ["/usr/local/bin/agent-entrypoint.sh"]
CMD ["sleep", "infinity"]
```

> 이번 마일스톤은 claude CLI를 **이미지에 설치**(npm 전역)해 단순화한다. 런타임 바이너리+볼륨 캐시(자동 업데이트 영속)는 Phase 2에서 도입.
> Chromium/mise/프록시/Docker CLI는 포함하지 않는다.

**entrypoint (`agent-entrypoint.sh`):**
```bash
#!/bin/bash
set -euo pipefail
# 1. git: git config --global --add safe.directory '*'  (봇 신원은 Phase 2)
# 2. MD 컨텍스트 자동 주입:
#    /home/agent/context/CLAUDE.md 있으면
#    → ~/.claude/CLAUDE.md 에 "@/home/agent/context/CLAUDE.md" import 한 줄 보장(중복 방지)
# 3. exec "$@"   # = sleep infinity (대기 프로세스). 도구는 docker exec로 붙음
```

- MD 주입은 **사용자 저장소를 건드리지 않는다** (유저 메모리 파일에만 import 추가).
- import 줄이 이미 있으면 다시 추가하지 않음(idempotent).

---

## 6. 데이터 흐름 (run)

```
사용자: (프로젝트 디렉토리에서) agentpod run
  │
  ├─ naming.projectId(cwd) → containerName
  ├─ 이미지 없으면 build_image()
  ├─ container_state != running 이면 run_detached(
  │     mounts = [ cwd→/project/<id>(rw),
  │               ~/.agent/claude→/home/agent/.claude(rw),
  │               ~/.agent/claude.json→/home/agent/.claude.json(rw),
  │               contexts/<id>→/home/agent/context(ro, 있으면) ],
  │     env_file = cwd/.env (있으면),
  │     workdir = /project/<id> )
  │       → entrypoint 초기화(safe.dir, MD import) → sleep infinity
  ├─ session.create_lock(projectId)
  ├─ install_signal_handlers(release)
  ├─ exec_interactive(containerName,
  │     ["claude", "--dangerously-skip-permissions", *extra])   # TTY 상속
  │
  └─ (사용자 종료) → session.release_lock → 다른 세션 없으면 docker stop
```

---

## 7. 오류 처리

- Docker 미설치/데몬 미기동 → 명확한 에러 메시지 + 종료코드 !=0.
- 이미지 없음 → `run`에서 자동 빌드 시도(또는 안내).
- 크래시로 남은 stale 락 → `active_sessions`가 자동 청소.
- 컨테이너가 이미 `exited` 상태 → `run` 시 `docker start` 또는 재생성.
- `.env` 없음 → 경고만(에러 아님). API 키 없고 로그인도 없으면 컨테이너 안 claude가 로그인을 요구 → 사용자가 대화형으로 로그인(둘 다 지원 정책).

---

## 8. 테스트 전략 (pytest)

| 대상 | 유형 | 방식 |
|------|------|------|
| `naming.projectId` | 유닛 | 경로→이름 결정성·정규화·해시 길이 |
| `session.active_sessions` | 유닛 | `os.kill` monkeypatch로 살아있음/죽음/권한 케이스, stale 청소 |
| `session` 이름 파싱 | 유닛 | 락파일명 prefix/sessionId 파싱 |
| `registry` | 유닛 | claude 정의 존재·기본 도구·확장 형태 |
| `context.resolve_mount` | 유닛 | 폴더 유무에 따른 마운트/None |
| 컨테이너 수명주기 | 통합(선택, `@pytest.mark.integration`) | 실제 docker 필요 — CI 기본 skip |

---

## 9. 완료 기준 (Definition of Done)

1. `agentpod build` 로 이미지 빌드 성공.
2. 임의 프로젝트 디렉토리에서 `agentpod run` → 격리 컨테이너 안에서 Claude Code 대화형 세션 진입.
3. API 키(.env) 또는 대화형 로그인 중 하나로 Claude 인증 동작.
4. `~/.agent/contexts/<projectId>/CLAUDE.md`를 넣으면 그 지침이 세션에 자동 반영.
5. 세션 종료 시 컨테이너 자동 stop(마지막 세션일 때), 재진입 시 세션 이어짐.
6. `agentpod status/stop/rm/context` 동작.
7. pytest 유닛 테스트 통과.
