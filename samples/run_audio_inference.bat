@echo off
REM ---------------------------------------------------------------------
REM Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
REM SPDX-License-Identifier: BSD-3-Clause
REM ---------------------------------------------------------------------
REM
REM run_audio_inference.bat
REM   Fully-automatic runner for every model under samples\audio\.
REM   It drives run_inference.py --model <name> for each audio model in
REM   turn, with no interactive prompts, and prints a PASS/FAIL summary.
REM
REM   A model only counts as PASS when it actually runs inference to
REM   completion. The model scripts call exit() (exit code 0) even when
REM   model download fails, so the exit code alone cannot be trusted.
REM   Each run's output is therefore also scanned for failure markers:
REM       "Failed to download"        (model / asset download failed)
REM       "Please prepare the model"  (model binary missing)
REM       "is not ready"              (partial / incomplete file)
REM       "Traceback (most recent"    (unhandled Python exception)
REM   If the exit code is non-zero OR any marker is present -> FAIL.
REM
REM Usage (from the samples\ directory):
REM     run_audio_inference.bat                 REM run all audio models
REM     run_audio_inference.bat --list          REM list audio models and exit
REM     run_audio_inference.bat --model yamnet  REM run a single audio model
REM
REM Notes:
REM   * Requires the qai_appbuilder wheel to be installed and models
REM     downloaded (each script auto-downloads on first run).
REM   * Extra args after --model <name> are forwarded to the model script.
REM   * Per-run logs are written to logs\<model>.log next to this script.
REM ---------------------------------------------------------------------

setlocal enabledelayedexpansion

REM Always operate from the directory this script lives in (samples\).
pushd "%~dp0"

REM Pick a Python interpreter (allow override via the PYTHON env var).
if "%PYTHON%"=="" set "PYTHON=python"

set "LAUNCHER=run_inference.py"
if not exist "%LAUNCHER%" (
    echo [ERROR] Cannot find %LAUNCHER% next to this script.
    set "RC=1"
    goto :done
)

set "LOG_DIR=logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM -- List of audio models (must match names in run_inference.py) ----------
set "AUDIO_MODELS=pipertts_en whisper_base_en whisper_tiny_en yamnet"

REM -- --list : just show the audio models and exit -------------------------
if /I "%~1"=="--list" (
    echo.
    echo Available audio models:
    for %%M in (%AUDIO_MODELS%) do echo    - %%M
    echo.
    set "RC=0"
    goto :done
)

REM -- --model NAME [extra args] : run one model directly -------------------
if /I "%~1"=="--model" goto :single

REM -- Default: run every audio model in sequence --------------------------
echo ============================================================
echo   QAI AppBuilder - Audio Model Batch Runner
echo ============================================================
echo   Interpreter : %PYTHON%
echo   Launcher    : %LAUNCHER%
echo   Models      : %AUDIO_MODELS%
echo   Logs        : %LOG_DIR%\
echo ============================================================

set /a TOTAL=0
set /a PASSED=0
set /a FAILED=0
set "FAILED_LIST="

for %%M in (%AUDIO_MODELS%) do (
    set /a TOTAL+=1
    echo.
    echo ------------------------------------------------------------
    echo   [!TOTAL!] Running audio model: %%M
    echo ------------------------------------------------------------
    call :run_one %%M
    if !RUN_OK! EQU 1 (
        echo   [PASS] %%M  ^(inference completed^)
        set /a PASSED+=1
    ) else (
        echo   [FAIL] %%M  ^(!RUN_REASON!^)
        set /a FAILED+=1
        set "FAILED_LIST=!FAILED_LIST! %%M"
    )
)

echo.
echo ============================================================
echo   Audio batch summary
echo ------------------------------------------------------------
echo   Total : !TOTAL!
echo   Passed: !PASSED!
echo   Failed: !FAILED!
if not "!FAILED_LIST!"=="" echo   Failed models:!FAILED_LIST!
echo ============================================================

set "RC=0"
if !FAILED! GTR 0 set "RC=1"
goto :done

REM -- Single-model handler ------------------------------------------------
:single
if "%~2"=="" (
    echo [ERROR] --model requires a model name.
    set "RC=1"
    goto :done
)
set "ONE_MODEL=%~2"
shift
shift
set "EXTRA_ARGS="
:collect_args
if not "%~1"=="" (
    set "EXTRA_ARGS=!EXTRA_ARGS! %1"
    shift
    goto :collect_args
)
call :run_one "!ONE_MODEL!" "!EXTRA_ARGS!"
echo.
if !RUN_OK! EQU 1 (
    echo [PASS] !ONE_MODEL!  ^(inference completed^)
    set "RC=0"
) else (
    echo [FAIL] !ONE_MODEL!  ^(!RUN_REASON!^)
    set "RC=1"
)
goto :done

REM ========================================================================
REM :run_one <model_name> [extra_args]
REM   Runs one model through the launcher, streams output to the console
REM   AND a per-model log, then decides PASS/FAIL from the exit code plus
REM   failure markers in the captured output.
REM   Returns: RUN_OK (1=pass, 0=fail) and RUN_REASON (failure description).
REM ========================================================================
:run_one
setlocal enabledelayedexpansion
set "MODEL=%~1"
set "XARGS=%~2"
set "LOG=%LOG_DIR%\%MODEL%.log"

if "!XARGS!"=="" (
    "%PYTHON%" "%LAUNCHER%" --model "!MODEL!" > "!LOG!" 2>&1
) else (
    "%PYTHON%" "%LAUNCHER%" --model "!MODEL!" --args "!XARGS!" > "!LOG!" 2>&1
)
set "EXITCODE=!ERRORLEVEL!"

REM Echo the captured output back to the console so the run is still visible.
type "!LOG!"

set "OK=1"
set "REASON=inference completed"

if not "!EXITCODE!"=="0" (
    set "OK=0"
    set "REASON=launcher exit code !EXITCODE!"
    goto :run_one_end
)

REM Scan the log for failure markers (case-insensitive literal search).
findstr /I /C:"Failed to download" "!LOG!" >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    set "OK=0"
    set "REASON=model/asset download failed"
    goto :run_one_end
)
findstr /I /C:"Please prepare the model" "!LOG!" >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    set "OK=0"
    set "REASON=model binary missing"
    goto :run_one_end
)
findstr /I /C:"is not ready" "!LOG!" >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    set "OK=0"
    set "REASON=incomplete/partial file"
    goto :run_one_end
)
findstr /I /C:"Traceback (most recent call last)" "!LOG!" >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    set "OK=0"
    set "REASON=python exception"
    goto :run_one_end
)

:run_one_end
endlocal & set "RUN_OK=%OK%" & set "RUN_REASON=%REASON%"
goto :eof

REM -- Common exit ---------------------------------------------------------
:done
popd
endlocal & exit /b %RC%
