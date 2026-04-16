@echo off
setlocal

cd /d "%~dp0"

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "CONFIG=configs\image_interchange.toml"
set "ASSET_DIR=generated_image_demo"
set "REPORT_DIR=reports\image_demo"

if not exist "%VENV_PYTHON%" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :fail
)

set "PYTHONPATH=%CD%\src"
"%VENV_PYTHON%" -c "import traffic_quantum" >nul 2>nul
if errorlevel 1 (
    echo Installing project package...
    "%VENV_PYTHON%" -m pip install -e .
    if errorlevel 1 goto :fail
)

if exist "C:\Program Files\Eclipse\Sumo\bin\sumo.exe" set "SUMO_BINARY=C:\Program Files\Eclipse\Sumo\bin\sumo.exe"
if exist "C:\Program Files\Eclipse\Sumo\bin\sumo-gui.exe" set "SUMO_GUI_BINARY=C:\Program Files\Eclipse\Sumo\bin\sumo-gui.exe"
if exist "C:\Program Files\Eclipse\Sumo\bin\netconvert.exe" set "NETCONVERT_BINARY=C:\Program Files\Eclipse\Sumo\bin\netconvert.exe"
if exist "C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe" if not defined SUMO_BINARY set "SUMO_BINARY=C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe"
if exist "C:\Program Files (x86)\Eclipse\Sumo\bin\sumo-gui.exe" if not defined SUMO_GUI_BINARY set "SUMO_GUI_BINARY=C:\Program Files (x86)\Eclipse\Sumo\bin\sumo-gui.exe"
if exist "C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe" if not defined NETCONVERT_BINARY set "NETCONVERT_BINARY=C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe"

if not defined SUMO_BINARY (
    echo SUMO was not found in the standard Windows installation paths.
    exit /b 1
)

if not defined NETCONVERT_BINARY (
    echo netconvert.exe was not found next to SUMO.
    exit /b 1
)

if "%~1"=="" goto :benchmark
if /I "%~1"=="assets" goto :assets
if /I "%~1"=="benchmark" goto :benchmark
if /I "%~1"=="smoke" goto :smoke
if /I "%~1"=="gui" goto :gui
if /I "%~1"=="test" goto :test

echo Unknown mode: %~1
echo Usage: run_image_demo.bat [assets^|benchmark^|smoke^|gui^|test]
exit /b 1

:assets
echo Generating image-inspired SUMO assets...
"%VENV_PYTHON%" -m traffic_quantum.cli generate-sumo-assets --config "%CONFIG%" --output "%ASSET_DIR%" --preset image-interchange --build-net --netconvert "%NETCONVERT_BINARY%"
if errorlevel 1 goto :fail
echo.
echo Image demo assets saved to:
echo   %CD%\%ASSET_DIR%
goto :success

:benchmark
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%"
call "%~f0" assets
if errorlevel 1 goto :fail
echo.
echo Running full controller benchmark on the image-inspired SUMO scenario...
"%VENV_PYTHON%" -m traffic_quantum.cli benchmark --config "%CONFIG%" --replications 2 --output "%REPORT_DIR%"
if errorlevel 1 goto :fail
echo.
echo Reports saved to:
echo   %CD%\%REPORT_DIR%\benchmark_runs.csv
echo   %CD%\%REPORT_DIR%\benchmark_summary.csv
goto :success

:smoke
call "%~f0" assets
if errorlevel 1 goto :fail
echo Running quick hybrid smoke test on the image-inspired SUMO scenario...
"%VENV_PYTHON%" -m traffic_quantum.cli smoke-test --config "%CONFIG%" --backend sumo --controller hybrid
if errorlevel 1 goto :fail
goto :success

:gui
if not defined SUMO_GUI_BINARY (
    echo SUMO GUI was not found in the standard Windows installation paths.
    exit /b 1
)
call "%~f0" assets
if errorlevel 1 goto :fail
echo Opening the image-inspired SUMO scenario in SUMO GUI...
set "SUMO_BINARY=%SUMO_GUI_BINARY%"
"%VENV_PYTHON%" -m traffic_quantum.cli smoke-test --config "%CONFIG%" --backend sumo --controller hybrid
if errorlevel 1 goto :fail
goto :success

:test
echo Running automated tests...
"%VENV_PYTHON%" -m pytest -q tests -p no:cacheprovider
if errorlevel 1 goto :fail
goto :success

:success
echo.
echo Completed successfully.
exit /b 0

:fail
echo.
echo Run failed.
exit /b 1
