@echo off
rem AgentPod folder-picker menu. Double-click this file.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agentpod-menu.ps1"
