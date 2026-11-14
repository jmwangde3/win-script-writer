@echo off
cd /d "H:\temp\user\wsw-v110-stage3-1\20261115-010429\execution\B\bat-S07\bat\工作\发布"
if errorlevel 1 exit /b 1
"%CD%\build.exe"
exit /b %ERRORLEVEL%
