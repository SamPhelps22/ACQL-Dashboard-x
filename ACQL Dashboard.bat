@echo off
rem ---------------------------------------------------------------------
rem  ACQL Dashboard - double-click launcher.
rem
rem  Lives next to run.py, in the same folder as the acql folder. It finds
rem  Python, hands over to run.py, and stays open if anything goes wrong so
rem  the message can be read instead of flashing past.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0"
title ACQL Dashboard

if not exist "run.py" goto wrongfolder

rem The py launcher first: it is what a normal Windows install provides, and
rem it dodges the Microsoft Store stub that "python" sometimes points at.
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto haspython
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto haspython
goto nopython

:haspython

echo   Starting the ACQL Dashboard...
echo   The first run takes a minute while it sets itself up. Leave it be.
echo.
%PY% run.py %*
if errorlevel 1 goto failed
exit /b 0


:nopython
echo.
echo   ============================================================
echo     The dashboard needs Python, and this computer hasn't got it.
echo   ============================================================
echo.
echo     1. Press a key and the download page will open.
echo     2. Click the big yellow "Download Python" button.
echo     3. Run the file it downloads.
echo     4. On the FIRST screen of the installer, tick the box at the
echo        bottom that says "Add python.exe to PATH". This matters -
echo        without it the dashboard cannot find Python afterwards.
echo     5. Click Install Now and wait for it to finish.
echo     6. Come back here and double-click this file again.
echo.
echo     It is free, it takes about five minutes, and nothing else
echo     on the computer is affected.
echo.
pause
start "" "https://www.python.org/downloads/windows/"
exit /b 1


:wrongfolder
echo.
echo   This file has been separated from the rest of the dashboard.
echo.
echo   It needs to sit in the same folder as run.py and the "acql"
echo   folder. Move it back in beside them and try again.
echo.
pause
exit /b 1


:failed
echo.
echo   ------------------------------------------------------------
echo     The dashboard stopped. The message above says why.
echo   ------------------------------------------------------------
echo.
echo   If it mentions a missing file, the folder was probably copied
echo   while something was still downloading - copy it again.
echo.
echo   Anything else: send Sam a photo of this window. If he asks what
echo   the dashboard can see, he means this - run it and send the result:
echo.
echo       "%~nx0" --diagnose
echo.
pause
exit /b 1