@echo off
chcp 936 >nul
cd /d "H:\temp\user\wsw-v110-stage3-1\20261115-010429\execution\A\bat-S04\bat\工作\发布"
if errorlevel 1 exit /b %ERRORLEVEL%
"H:\temp\user\wsw-v110-stage3-1\20261115-010429\execution\A\bat-S04\bat\工作\发布\build.exe"
exit /b %ERRORLEVEL%
