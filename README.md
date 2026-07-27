# AgentPod

Docker로 격리된 자율 AI 코딩 에이전트 컨테이너. 프로젝트마다 격리된 컨테이너를
하나씩 띄우고 그 안에서 Claude Code를 실행합니다.

> 설계 근거: [BUILD-GUIDE](docs/dev/BUILD-GUIDE.md) · Phase 1 스펙:
> [design](docs/superpowers/specs/2026-07-03-agentpod-phase1-design.md)

## 요구사항

- Windows 10/11 + Docker Desktop
- Python 3.10+

## 설치 (한 번에)

저장소 루트에서 `install_windows.bat`을 더블클릭하거나 터미널에서:

```
install_windows.bat
```

Docker Desktop·Python 3.10+ 확인 → 전용 venv에 `agentpod` 명령 설치(PATH 등록) →
에이전트 이미지 빌드까지 자동으로 합니다. 이미지 빌드를 건너뛰려면 `install_windows.bat --no-build`.
자세한 단계·문제 해결은 [설치 가이드](docs/windows/install-guide.html) 참고.

> 설치 후 현재 창에서 바로 `agentpod`가 잡힙니다. 새 터미널 창도 자동으로 PATH가 적용됩니다.
> 남은 수동 단계는 **Claude 인증 1회**뿐입니다(아래 인증 참고).

<details><summary>수동 설치 (스크립트를 쓰지 않을 때)</summary>

```powershell
python -m venv $env:USERPROFILE\.venvs\agentpod
& $env:USERPROFILE\.venvs\agentpod\Scripts\pip.exe install -e .
```
</details>

## 실행 — 폴더 선택 메뉴로 (가장 쉬움)

저장소 루트에서 `agentpod`라고만 치면 `agents\` 아래 폴더들이 번호로 뜨고, 골라서
바로 실행(`run`)·셸 접속(`shell`)·공유(`export`)까지 할 수 있습니다. 타이핑도
경로도 몰라도 됩니다. 자세한 사용법은 [메뉴 가이드](docs/windows/menu-guide.html) 참고.

## 사용 — 커맨드로 직접

```bash
agentpod build                 # 에이전트 이미지 빌드 (최초 1회)
cd /path/to/your/project
agentpod run                   # 컨테이너 스폰/재사용 → Claude Code 대화형 실행
agentpod shell                 # 같은 컨테이너에 bash로 접속
agentpod status                # 모든 agent-* 컨테이너 + 활성 세션 수
agentpod stop                  # 이 프로젝트의 컨테이너 stop
agentpod rm                    # stop + remove
agentpod context               # 이 컨테이너의 MD 컨텍스트 폴더 경로
agentpod export                # 설치된 플러그인/스킬 + MCP 서버를 agent.toml/.mcp.json에 기록 (아래 공유하기)
```

## 인증 (둘 다 지원)

- **API 키**: 프로젝트 루트 `.env`에 `ANTHROPIC_API_KEY=...` → 자동 주입.
- **대화형 로그인**: `agentpod shell` 후 `claude login`. 바인드 마운트로 영속되어 컨테이너가
  죽어도, 심지어 다른 프로젝트로 옮겨도 로그인이 유지됩니다 — 로그인은 프로젝트별로 분리되지
  않고 항상 공유됩니다(아래 프로파일 참고).

## 리소스 제한 (폭주 방지)

자율 실행 컨테이너가 호스트를 마비시키지 않도록 메모리·CPU·PID에 상한을 겁니다.
기본값은 memory 4g · cpus 2 · pids 512.

```bash
# 실행마다 지정
agentpod run --memory 8g --cpus 4 --pids 1024

# 호스트 기본값을 환경변수로 (빈 값 = 해당 제한 해제)
export AGENT_MEMORY=8g AGENT_CPUS=4 AGENT_PIDS_LIMIT=1024
```

> 제한은 컨테이너 **생성 시점**에 적용됩니다(이미 떠 있는 컨테이너엔 미적용 — 필요 시 `agentpod rm` 후 재실행).

## 멀티툴 (claude / codex / opencode)

`--tool`로 실행할 AI 코딩 CLI를 선택합니다. 도구별 자율 플래그·크레덴셜은 registry가 흡수.

```bash
agentpod run --tool claude     # 기본
agentpod run --tool codex
agentpod run --tool opencode
```
크레덴셜은 도구별로 분리 저장·영속: claude→`~/.agent/claude`, codex→`~/.agent/codex`, opencode→`~/.agent/opencode`.

## 프로파일 (기본은 프로젝트별 자동 분리)

`--profile`을 **안 쓰면**, 플러그인/스킬 설치 상태가 프로젝트 폴더마다 자동으로 격리됩니다.
한 프로젝트 컨테이너에서 설치한 플러그인이 다른 프로젝트로 새지 않습니다. 단, **로그인은
프로파일과 무관하게 항상 공유**됩니다.

```bash
agentpod run                          # 기본: 이 프로젝트만의 플러그인 상태
agentpod run --profile bot            # 명시: "bot"이라는 이름으로 여러 프로젝트가 상태 공유
```

지정 시 컨테이너명 `agent-<id>--p--<profile>`, 크레덴셜 경로 `~/.agent/profiles/<name>/<tool>`.
같은 `--profile` 이름을 여러 프로젝트에 쓰면 그 프로젝트들끼리 플러그인 상태를 의도적으로
공유/복사하는 효과가 있습니다. `run/shell/stop/rm/export` 전부에 적용됩니다.

## mise (툴체인 버전)

이미지에 **mise + python 3.12 + node**가 내장됩니다. 프로젝트 루트에 `mise.toml`을 두면
부팅 시 선언한 버전을 추가 설치합니다.

```toml
[tools]
python = "3.12"
node = "22"
```

## 봇 git 신원 (한 번 등록 → 모든 컨테이너 공유)

자율 에이전트가 사람 계정이 아닌 **전용 봇 신원**으로 커밋·푸시하게 합니다. 한 번 등록하면
`~/.agent/`에 저장되어 **모든 컨테이너가 자동으로 공유**합니다(로그인과 동일 원리).

```bash
# HTTPS 토큰 방식 (GitHub 등)
agentpod git-setup --name "agent-bot" \
  --email "agent-bot@users.noreply.github.com" \
  --token <PAT>        # push/pull 토큰 (생략 시 커밋 신원만 설정)

# SSH 방식 (Bitbucket 등) — 키 생성 + known_hosts + 공개키 출력까지 한 번에
agentpod git-setup --ssh --ssh-host bitbucket.org \
  --name "agent-bot" --email "봇 Bitbucket 이메일"
```

- 저장 위치: `~/.agent/gitconfig`(신원) · `~/.agent/git-credentials`(토큰, chmod 600) — 저장소엔 안 들어감
- 프로젝트별로 다르게 쓰려면 `.env`의 `GIT_BOT_NAME/GIT_BOT_EMAIL/GITHUB_TOKEN`로 오버라이드
- 봇 계정 권한은 최소로, 토큰은 주기적으로 회전하세요.
- 자세한 방법(PAT 발급·docker run 방식·확인): [git-identity-guide](docs/git-identity-guide.html)

## 스킬(플러그인) 자동 설치 — skills.toml / agent.toml

프로젝트 루트에 매니페스트를 두면 컨테이너 부팅 시 선언한 스킬을 자동 설치합니다(멱등·best-effort).

```toml
# skills.toml (스킬만)  또는  agent.toml (전체 설정 중 [[skills]] 섹션)
[[skills]]
name = "superpowers"            # 유명 스킬은 이름만 (내장 카탈로그가 출처 해석)

[[skills]]
name = "my-skill"
source = "github:org/repo"      # 커스텀은 마켓플레이스 저장소 지정
# marketplace_name = "..."      # (선택) install 시 @이름; add 출력에서 자동 감지 시도
enabled = true                  # (선택, 기본 true)
```

- **위치**: 프로젝트 루트(= 컨테이너 작업 디렉토리). `agent.toml`·`skills.toml` 둘 다 읽어 병합.
- 내부적으로 `claude plugin marketplace add` + `claude plugin install`로 번역됩니다.
- 자세한 추가 방법(커스텀 스킬·문제 해결): [skills-guide](docs/skills-guide.html)

## 팀원과 공유하기 — `agentpod export`

세션 중에 설치한 플러그인/스킬, 붙인 MCP 서버는 기본적으로 프로젝트별 격리 상태(위 프로파일)에만
남아 `git clone`해도 자동으로 안 따라옵니다. `agentpod export`가 지금 상태를 프로젝트 파일로
스냅샷합니다:

```bash
agentpod export
# → agent.toml에 [[skills]] 추가
# → .mcp.json에 mcpServers 추가
# → 시크릿(MCP env/헤더 값)은 .mcp.json에 안 박히고 .env(gitignore)로 분리
```

`git diff agent.toml .mcp.json`으로 확인 후 커밋·푸시하면, 팀원은 `git clone` +
`agentpod run`만으로 같은 스킬이 자동 설치되고 MCP 서버가 자동 승인됩니다. `.mcp.json`의
`${VAR}`가 참조하는 실제 값은 각자 자기 `.env`에 채워야 합니다(값 자체는 시크릿이라 공유 대상이
아님). 자세한 내용: [export-guide](docs/export-guide.html)

## 컨테이너별 MD 컨텍스트

`agentpod context`가 출력하는 폴더(`~/.agent/contexts/<projectId>/`)에 `CLAUDE.md`와
참고 `.md`를 넣으면, 그 컨테이너의 Claude 세션에 자동으로 반영됩니다. 코드 수정 불필요.

## 개발

```bash
pip install -e ".[dev]"
pytest -m "not integration"
```
