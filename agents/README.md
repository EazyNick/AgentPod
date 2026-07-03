# agents/ — 할 일 기준 에이전트 컨텍스트

이 폴더는 AgentPod로 띄우는 **역할별 Claude 에이전트**의 컨텍스트를 할 일(task) 단위로 모아둡니다.
폴더 하나 = 에이전트 하나 = AgentPod 컨테이너 하나(`agent-<folder>-<hash>`)이며, 각 폴더의 `CLAUDE.md`가
그 컨테이너 안 Claude의 역할을 정의합니다. (Claude Code는 작업 디렉토리의 `CLAUDE.md`를 자동으로 읽습니다.)

## 대상: DUT(Device Under Test)

이 파이프라인의 대상은 네트워크 장비(DUT)입니다. UI를 바꾸고, 바뀐 UI가 DUT에서 실제로
정상 동작하는지(ping / SSID 연결 / DHCP 등) 검증합니다.

## 에이전트 (2단계)

| 폴더 | 역할 | 산출물 |
|------|------|--------|
| [`spec-inspect/`](spec-inspect/CLAUDE.md) | 사양 확인 + UI 검사 → **테스트 계획 수립** (기본: 모든 UI 테스트) | `ui-inventory.md`, `testplan.md` |
| [`apply-verify/`](apply-verify/CLAUDE.md) | UI 변경 + DUT 검증 **동시** 진행 | `report.html` (+ `run-log.md`) |

흐름: **spec-inspect** 로 무엇을·어떻게 테스트할지 확정 → **apply-verify** 로 변경하며 곧바로 DUT에서 검증하고 리포트 생성.

## 실행

```bash
# 1) 사양 확인 + 검사(테스트 계획)
cd agents/spec-inspect && agentpod run

# 2) UI 변경 + DUT 검증 동시 + HTML 리포트
cd agents/apply-verify && agentpod run
```

## 대상(UI/DUT) 연결

이 폴더들에는 **역할 지침과 사양·산출물 문서**만 둡니다. 실제 대상은 각 폴더의 아래 파일에 명시하세요.
- UI 소스/접속 방법: 각 `spec.md` 상단 또는 별도 지정
- DUT 접속 정보(IP·인터페이스·자격): [`apply-verify/dut.md`](apply-verify/dut.md)

> 네트워크 주의: DUT 테스트는 컨테이너가 DUT/LAN에 닿아야 합니다. ping/DHCP(관찰)/HTTP-API 는
> 아웃바운드로 대체로 가능하지만, 실제 무선(SSID) association 은 컨테이너가 호스트 WiFi에 직접
> 접근할 수 없으므로 **DUT의 관리 API 기반 확인**을 기본으로 합니다. (자세한 건 각 CLAUDE.md 참고)
