@echo off
REM run.cmd -- launcher that works under ANY PowerShell execution policy.
REM
REM A downloaded (unzipped) repo is unsigned, and Windows may refuse to run
REM .ps1 files directly ("...is not digitally signed. You cannot run this
REM script on the current system."). This wrapper invokes scripts\run.ps1 with
REM the policy bypassed for this one invocation only -- it does NOT change
REM any system/user setting.
REM
REM If the launcher stops before the server starts, the window pauses so you
REM can read the error instead of disappearing.
REM
REM Use it like the .ps1:   run.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" %*
if errorlevel 1 pause
