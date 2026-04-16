@echo off
setlocal

cd /d "%~dp0"

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "TMP=%CD%\.tmp"
set "TEMP=%CD%\.tmp"

if not exist "%TMP%" mkdir "%TMP%"

if not exist "%VENV_PYTHON%" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :fail
)

echo Ensuring local environment is ready...
"%VENV_PYTHON%" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo Repairing pip inside the virtual environment...
    "%VENV_PYTHON%" -m ensurepip --upgrade
    if errorlevel 1 goto :fail
    "%VENV_PYTHON%" -m pip install --upgrade pip setuptools wheel
    if errorlevel 1 goto :fail
)

set "PYTHONPATH=%CD%\src"
"%VENV_PYTHON%" -c "import traffic_quantum" >nul 2>nul
if errorlevel 1 (
    echo Installing project package...
    "%VENV_PYTHON%" -m pip install -e .
    if errorlevel 1 goto :fail
)

if "%~1"=="" goto :benchmark
if /I "%~1"=="smoke" goto :smoke
if /I "%~1"=="benchmark" goto :benchmark
if /I "%~1"=="train" goto :train
if /I "%~1"=="assets" goto :assets
if /I "%~1"=="test" goto :test
if /I "%~1"=="sumo" goto :sumo

echo Unknown mode: %~1
echo Usage: run_project.bat [smoke^|benchmark^|train^|assets^|test^|sumo]
exit /b 1

:smoke
echo Running hybrid smoke test...
"%VENV_PYTHON%" -m traffic_quantum.cli smoke-test --controller hybrid
if errorlevel 1 goto :fail
goto :success

:benchmark
echo Running benchmark and writing reports...
if not exist reports mkdir reports
"%VENV_PYTHON%" -m traffic_quantum.cli benchmark --config configs/mock_city.toml --replications 2 --output reports
if errorlevel 1 goto :fail
echo.
echo Reports saved to:
echo   %CD%\reports\benchmark_runs.csv
echo   %CD%\reports\benchmark_summary.csv
goto :success

:train
echo Training hybrid policy...
"%VENV_PYTHON%" -m traffic_quantum.cli train-policy --config configs/mock_city.toml --episodes 5
if errorlevel 1 goto :fail
goto :success

:assets
echo Generating SUMO assets...
"%VENV_PYTHON%" -m traffic_quantum.cli generate-sumo-assets --config configs/sumo_city.toml --output generated_sumo
if errorlevel 1 goto :fail
echo.
echo SUMO source files saved to:
echo   %CD%\generated_sumo
goto :success

:test
echo Running automated tests...
"%VENV_PYTHON%" -m pytest -q tests -p no:cacheprovider
if errorlevel 1 goto :fail
goto :success

:sumo
if exist "C:\Program Files\Eclipse\Sumo\bin\sumo-gui.exe" set "SUMO_BINARY=C:\Program Files\Eclipse\Sumo\bin\sumo-gui.exe"
if exist "C:\Program Files\Eclipse\Sumo\bin\netconvert.exe" set "NETCONVERT_BINARY=C:\Program Files\Eclipse\Sumo\bin\netconvert.exe"
if exist "C:\Program Files (x86)\Eclipse\Sumo\bin\sumo-gui.exe" if not defined SUMO_BINARY set "SUMO_BINARY=C:\Program Files (x86)\Eclipse\Sumo\bin\sumo-gui.exe"
if exist "C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe" if not defined NETCONVERT_BINARY set "NETCONVERT_BINARY=C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe"

if not defined SUMO_BINARY (
    echo SUMO is not installed in the standard Windows paths.
    echo Install SUMO, or edit run_sumo_gui.bat / configs\sumo_city.toml with your local paths.
    exit /b 1
)

if not defined NETCONVERT_BINARY (
    echo netconvert.exe was not found next to SUMO.
    exit /b 1
)

echo Generating SUMO assets...
"%VENV_PYTHON%" -m traffic_quantum.cli generate-sumo-assets --config configs/sumo_city.toml --output generated_sumo
if errorlevel 1 goto :fail

echo Building SUMO network...
"%NETCONVERT_BINARY%" --node-files generated_sumo\grid.nod.xml --edge-files generated_sumo\grid.edg.xml --output-file generated_sumo\grid.net.xml
if errorlevel 1 goto :fail

set "SUMO_HOME="
for %%I in ("%SUMO_BINARY%") do set "SUMO_HOME=%%~dpI.."

echo Running SUMO GUI smoke test...
set "SUMO_BINARY=%SUMO_BINARY%"
"%VENV_PYTHON%" -m traffic_quantum.cli smoke-test --backend sumo --controller hybrid --config configs/sumo_city.toml
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
