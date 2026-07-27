<#
AgentPod folder-picker menu (Windows). Double-click agentpod-menu.bat, or run:
    powershell -File agentpod-menu.ps1

Lists sub-folders under .\agents (each folder = one agent/project), lets you
pick one by number, then runs `agentpod run` / `agentpod shell` /
`agentpod export` there -- no need to type paths or cd by hand.
#>

$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AgentsDir = Join-Path $RepoDir "agents"

function Get-AgentFolders {
    if (-not (Test-Path $AgentsDir)) { return @() }
    Get-ChildItem -Path $AgentsDir -Directory | Sort-Object Name
}

function Show-ActionMenu($target) {
    while ($true) {
        Write-Host ""
        Write-Host "  선택: $target" -ForegroundColor DarkGray
        Write-Host "  R) 실행 (agentpod run)"
        Write-Host "  S) 셸 접속 (agentpod shell)"
        Write-Host "  E) 공유용으로 내보내기 (agentpod export)"
        Write-Host "  B) 뒤로"
        $action = Read-Host "동작 선택"

        Push-Location $target
        try {
            switch -Regex ($action) {
                '^[Rr]$' { agentpod run; return }
                '^[Ss]$' { agentpod shell; return }
                '^[Ee]$' { agentpod export; Read-Host "계속하려면 Enter"; continue }
                '^[Bb]$' { return }
                default  { Write-Host "잘못된 선택입니다." -ForegroundColor Red }
            }
        } finally {
            Pop-Location
        }
    }
}

while ($true) {
    Clear-Host
    Write-Host "=== AgentPod ===" -ForegroundColor Cyan
    Write-Host ""
    $folders = Get-AgentFolders
    if ($folders.Count -eq 0) {
        Write-Host "agents\ 아래에 폴더가 없습니다." -ForegroundColor Yellow
    } else {
        for ($i = 0; $i -lt $folders.Count; $i++) {
            Write-Host ("  {0}) {1}" -f ($i + 1), $folders[$i].Name)
        }
    }
    Write-Host ""
    Write-Host "  P) 다른 경로 직접 입력"
    Write-Host "  Q) 종료"
    Write-Host ""
    $choice = Read-Host "실행할 에이전트 번호"

    if ($choice -match '^[Qq]$') { break }

    $target = $null
    if ($choice -match '^[Pp]$') {
        $target = Read-Host "프로젝트 경로 입력"
    } elseif ($choice -match '^\d+$' -and [int]$choice -ge 1 -and [int]$choice -le $folders.Count) {
        $target = $folders[[int]$choice - 1].FullName
    } else {
        Write-Host "잘못된 선택입니다." -ForegroundColor Red
        Start-Sleep -Seconds 1
        continue
    }

    if (-not (Test-Path $target)) {
        Write-Host "경로가 없습니다: $target" -ForegroundColor Red
        Start-Sleep -Seconds 2
        continue
    }

    Show-ActionMenu $target
}
