@echo off
setlocal
set "SRC=%~dp0"
set "KRITA=%APPDATA%\krita"
set "DEST=%KRITA%\pykrita"
echo Installing Momo Color Picker ...
if not exist "%DEST%" mkdir "%DEST%"
xcopy /E /I /Y "%SRC%hsv_picker" "%DEST%\hsv_picker\" >nul
copy /Y "%SRC%hsv_picker.desktop" "%DEST%\hsv_picker.desktop" >nul
if not exist "%KRITA%\actions" mkdir "%KRITA%\actions"
copy /Y "%SRC%hsv_picker\actions\hsv_picker.action" "%KRITA%\actions\hsv_picker.action" >nul
echo Done. Restart Krita, then enable it in: Settings > Configure Krita > Python Plugin Manager.
echo Restart Krita once more to activate the plugin.
pause
