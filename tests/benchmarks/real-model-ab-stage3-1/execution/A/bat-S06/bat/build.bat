@echo off
chcp 936 >nul
cd /d "H:\temp\user\wsw-v110-stage3-1\20261115-010429\execution\A\bat-S06\bat\工作\发布" || exit /b 1
build.exe
exit /b %errorlevel%
