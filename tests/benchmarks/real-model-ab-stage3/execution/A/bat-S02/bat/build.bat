@echo off
chcp 936 >nul
cd /d "H:\temp\user\wsw-v110-stage3\20261115-001546\execution\A\bat-S02\bat\工作\发布" || exit /b 1
build.exe
exit /b %ERRORLEVEL%
