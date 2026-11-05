@echo off
rem ============================================================================================
rem  Start HDL Studio (Design Manager) on Windows. Arguments are passed on, e.g.
rem      bin\hdlstudio.bat D:\path\project.hdp
rem  Uses the virtual environment .venv of the repository when there is one, else "python".
rem ============================================================================================
set "ROOT=%~dp0.."
if exist "%ROOT%\.venv\Scripts\pythonw.exe" (
    start "" "%ROOT%\.venv\Scripts\pythonw.exe" "%ROOT%\bin\hdlstudio.py" %*
) else (
    start "" pythonw "%ROOT%\bin\hdlstudio.py" %*
)
