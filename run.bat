@echo off
setlocal

REM ============================================================================
REM  run.bat â€” Revox launcher
REM ============================================================================
REM
REM  Usage:
REM      run.bat "path\to\video.mkv"
REM
REM  If no argument is given, processes all video files in input\ folder.
REM
REM  This batch file is a thin wrapper around run.py (Python) which handles
REM  all filenames correctly, including those with special characters like &.
REM
REM  Prerequisites:
REM      1.  Python 3.10+ on PATH
REM      2.  ffmpeg on PATH  (winget install Gyan.FFmpeg)
REM      3.  pip install -r requirements.txt
REM
REM ============================================================================

REM --- Switch to the directory containing this batch file ---
cd /d "%~dp0"

REM --- Check Python ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH. Install Python 3.10+.
    goto :error
)

REM --- Check ffmpeg ---
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [ERROR] ffmpeg not found on PATH.
    echo         Install: winget install Gyan.FFmpeg
    echo         Then open a NEW terminal and re-run.
    goto :error
)

REM --- Determine TTS provider ---
set "PROVIDER=pyttsx3"
if not "%FISH_SPEECH_URL%"=="" set "PROVIDER=fish-speech"
if not "%ELEVENLABS_API_KEY%"=="" set "PROVIDER=elevenlabs"

REM --- Run the pipeline ---
if "%~1"=="" (
    echo.
    echo   No input file specified. Processing all videos in input\ folder...
    echo.
    python run_all.py --provider %PROVIDER%
) else (
    python run.py "%~1" --provider %PROVIDER%
)

if errorlevel 1 goto :error

echo.
echo ==============================================================================
echo   [SUCCESS] PIPELINE COMPLETE
echo   Check the output\ folder for results.
echo ==============================================================================
endlocal
exit /b 0

:error
echo.
echo ==============================================================================
echo   [FAILED] PIPELINE STOPPED DUE TO AN ERROR
echo ==============================================================================
endlocal
exit /b 1
