# AgentPod

Docker로 격리된 자율 AI 코딩 에이전트 컨테이너. 프로젝트마다 격리된 컨테이너를
하나씩 띄우고 그 안에서 Claude Code를 실행합니다.

> 설계 근거: [BUILD-GUIDE](docs/dev/BUILD-GUIDE.md) · Phase 1 스펙:
> [design](docs/superpowers/specs/2026-07-03-agentpod-phase1-design.md)

## 요구사항

- WSL2/Linux/Raspberry Pi OS(64bit) + Docker
- Python 3.10+

## 설치 (한 번에)

리눅스/WSL2/라즈베리파이에서 저장소 루트에서:

```bash
./install.sh
```

시스템 패키지(python3/venv/pip/pipx) 설치 → `agentpod` 명령을 PATH에 등록 →
에이전트 이미지 빌드까지 자동으로 합니다. 이미지 빌드를 건너뛰려면 `./install.sh --no-build`.

> 설치 후 현재 셸에서 `agentpod`가 안 잡히면 새 터미널을 열거나 `source ~/.bashrc`.
> 남은 수동 단계는 **Claude 인증 1회**뿐입니다(아래 인증 참고).

<details><summary>수동 설치 (스크립트를 쓰지 않을 때)</summary>

```bash
python3 -m venv ~/.venvs/agentpod && source ~/.venvs/agentpod/bin/activate
pip install -e .
```
</details>

## 사용

```bash
agentpod build                 # 에이전트 이미지 빌드 (최초 1회)
cd /path/to/your/project
agentpod run                   # 컨테이너 스폰/재사용 → Claude Code 대화형 실행
agentpod shell                 # 같은 컨테이너에 bash로 접속
agentpod status                # 모든 agent-* 컨테이너 + 활성 세션 수
agentpod stop                  # 이 프로젝트의 컨테이너 stop
agentpod rm                    # stop + remove
agentpod context               # 이 컨테이너의 MD 컨텍스트 폴더 경로
```

## 인증 (둘 다 지원)

- **API 키**: 프로젝트 루트 `.env`에 `ANTHROPIC_API_KEY=...` → 자동 주입.
- **대화형 로그인**: `agentpod shell` 후 `claude login`. `~/.agent/claude` 바인드
  마운트로 영속되어 컨테이너가 죽어도 로그인 유지.

## 봇 git 신원 (한 번 등록 → 모든 컨테이너 공유)

자율 에이전트가 사람 계정이 아닌 **전용 봇 신원**으로 커밋·푸시하게 합니다. 한 번 등록하면
`~/.agent/`에 저장되어 **모든 컨테이너가 자동으로 공유**합니다(로그인과 동일 원리).

```bash
agentpod git-setup --name "agent-bot" \
  --email "agent-bot@users.noreply.github.com" \
  --token <PAT>        # push/pull 토큰 (생략 시 커밋 신원만 설정)
```

- 저장 위치: `~/.agent/gitconfig`(신원) · `~/.agent/git-credentials`(토큰, chmod 600) — 저장소엔 안 들어감
- 프로젝트별로 다르게 쓰려면 `.env`의 `GIT_BOT_NAME/GIT_BOT_EMAIL/GITHUB_TOKEN`로 오버라이드
- 봇 계정 권한은 최소로, 토큰은 주기적으로 회전하세요.

## 컨테이너별 MD 컨텍스트

`agentpod context`가 출력하는 폴더(`~/.agent/contexts/<projectId>/`)에 `CLAUDE.md`와
참고 `.md`를 넣으면, 그 컨테이너의 Claude 세션에 자동으로 반영됩니다. 코드 수정 불필요.

## 개발

```bash
pip install -e ".[dev]"
pytest -m "not integration"
```
