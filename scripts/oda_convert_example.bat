@echo off
REM Example ODA File Converter usage
REM Update ODA_PATH before running

set ODA_PATH=C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe
set IN_DIR=%~1
set OUT_DIR=%~2
set FILE_NAME=%~3

if "%IN_DIR%"=="" (
  echo Usage: oda_convert_example.bat ^<input_dir^> ^<output_dir^> ^<file_name.dwg^>
  exit /b 1
)

if "%OUT_DIR%"=="" (
  echo Usage: oda_convert_example.bat ^<input_dir^> ^<output_dir^> ^<file_name.dwg^>
  exit /b 1
)

if "%FILE_NAME%"=="" (
  echo Usage: oda_convert_example.bat ^<input_dir^> ^<output_dir^> ^<file_name.dwg^>
  exit /b 1
)

"%ODA_PATH%" "%IN_DIR%" "%OUT_DIR%" ACAD2018 DXF 0 1 "%FILE_NAME%"
