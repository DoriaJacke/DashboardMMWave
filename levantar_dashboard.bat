@echo off
REM ============================================================
REM Levanta el dashboard MR60BHA1:
REM   1. Cierra cualquier servidor previo en el puerto 8000
REM   2. Compila el frontend (frontend/dist) con los cambios actuales
REM   3. Inicia el backend FastAPI (sirve API + interfaz)
REM   4. Abre el navegador en http://localhost:8000
REM Para detenerlo: cerrar esta ventana o Ctrl+C.
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/4] Cerrando servidor previo en el puerto 8000 (si existe)...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do taskkill /PID %%p /F >nul 2>&1

echo [2/4] Compilando frontend...
pushd frontend
if not exist node_modules (
    call npm install || goto :error
)
call npm run build || goto :error
popd

echo [3/4] Abriendo navegador...
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8000"

REM Placa CMAE: deshabilitada por defecto. Para encenderla, quitar el REM de la linea siguiente.
REM set MMWAVE_CMAE=1

echo [4/4] Iniciando backend en http://localhost:8000 ...
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
goto :eof

:error
echo.
echo *** Error al compilar el frontend. Revisa los mensajes de arriba. ***
popd
pause
exit /b 1
