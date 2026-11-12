@echo off
rem Starts the Vite dev server. Vite needs Node 20+; the default Node on this PC is 16, so prefer nvm's Node 22 when present.
if exist C:\nvm\v22.22.2\node.exe set "PATH=C:\nvm\v22.22.2;%PATH%"
if "%PORT%"=="" set PORT=5173
cd /d "%~dp0"
node node_modules\vite\bin\vite.js --port %PORT% --strictPort
