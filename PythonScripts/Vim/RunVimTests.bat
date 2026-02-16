@echo off
setlocal

set "REPO_DIR=%~dp0"
set "DEST_PY=%APPDATA%\10x\PythonScripts"
set "TENX_EXE=C:\Program Files\PureDevSoftware\10x\10x.exe"
set "RESULTS_FILE=%REPO_DIR%vim-test-results.txt"

echo [1/4] Preparing destination PythonScripts folder...
if not exist "%DEST_PY%" (
    mkdir "%DEST_PY%" || goto :copy_fail
)

echo [2/4] Copying Vim scripts and tests into 10x PythonScripts...
copy /Y "%REPO_DIR%VimAI.py" "%DEST_PY%\Vim.py" >nul || goto :copy_fail
copy /Y "%REPO_DIR%VimUser.py" "%DEST_PY%\VimUser.py" >nul || goto :copy_fail
copy /Y "%REPO_DIR%CppParserTestUtils.py" "%DEST_PY%\CppParserTestUtils.py" >nul || goto :copy_fail
copy /Y "%REPO_DIR%VimTests.py" "%DEST_PY%\VimTests.py" >nul || goto :copy_fail

if exist "%RESULTS_FILE%" del /Q "%RESULTS_FILE%"
if exist "%RESULTS_FILE%.json" del /Q "%RESULTS_FILE%.json"

set "VIM_TEST_RESULTS_PATH=%RESULTS_FILE%"
set "VIM_TEST_AUTO_EXIT=1"

echo [3/4] Launching 10x and executing RunTests()...
"%TENX_EXE%" -NewInstance "RunTests()"

echo [4/4] Inspecting result file...
if not exist "%RESULTS_FILE%" (
    echo ERROR: Result file was not created: "%RESULTS_FILE%"
    exit /b 1
)

findstr /R /C:"Failed: [1-9]" "%RESULTS_FILE%" >nul
if %ERRORLEVEL% EQU 0 (
    echo Vim tests FAILED. See:
    echo   %RESULTS_FILE%
    exit /b 1
)

echo Vim tests PASSED. Results:
echo   %RESULTS_FILE%
exit /b 0

:copy_fail
echo ERROR: Failed to copy files into "%DEST_PY%".
exit /b 1
