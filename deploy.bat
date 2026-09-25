@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo =======================================================
echo   CYBERBAND S3 - AUTO DEPLOY DASHBOARD TO GITHUB PAGES
echo =======================================================

:: Tim git executable
set GIT_CMD=git
where git >nul 2>nul
if %errorlevel% neq 0 (
    if exist "%~dp0.git_bin\cmd\git.exe" (
        set "GIT_CMD=%~dp0.git_bin\cmd\git.exe"
    ) else (
        echo [!] Khong tim thay Git tren may! Vui long cai dat Git hoac doi MinGit tai ve.
        pause
        exit /b 1
    )
)

cd /d "%~dp0"

:: Kiem tra git repository da khoi tao chua
if not exist ".git" (
    echo [+] Khoi tao Git repository lan dau...
    "%GIT_CMD%" init
    "%GIT_CMD%" branch -M main
)

:: Kiem tra remote
"%GIT_CMD%" remote get-url origin >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] Chua cau hinh link GitHub Remote!
    echo Vui long nhap URL GitHub Repository cua ban (Vi du: https://github.com/username/cyberband.git):
    set /p REPO_URL=Link Repository: 
    if not "!REPO_URL!"=="" (
        "%GIT_CMD%" remote add origin !REPO_URL!
        echo [+] Da them remote origin: !REPO_URL!
    ) else (
        echo [-] Ban chua nhap link repository. Huy deploy.
        pause
        exit /b 1
    )
)

echo.
echo [+] Dang chuan bi deploy file index.html len GitHub...
"%GIT_CMD%" add index.html
"%GIT_CMD%" commit -m "Auto deploy update: %date% %time%" 2>nul

echo [+] Dang day (push) du lieu len branch main...
"%GIT_CMD%" push origin main

if %errorlevel% equ 0 (
    echo.
    echo =======================================================
    echo   [V] DEPLOY THANH CONG!
    echo   GitHub Pages se tu dong cap nhat web sau 15-30 giay!
    echo =======================================================
) else (
    echo.
    echo [-] Push that bai! Vui long kiem tra lai quyen truy cap GitHub hoac mang internet.
)

echo.
pause
