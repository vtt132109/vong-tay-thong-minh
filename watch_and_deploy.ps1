# ==============================================================================
# CYBERBAND S3 - REALTIME FILE WATCHER & AUTO-DEPLOY TO GITHUB PAGES
# ==============================================================================

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $projectRoot

# Tim Git executable (uu tien MinGit neu co)
$gitCmd = "git"
$mingitPath = Join-Path $projectRoot ".git_bin\cmd\git.exe"
if (Test-Path $mingitPath) {
    $gitCmd = $mingitPath
} elseif (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[-] Khong tim thay Git tren may! Vui long cai Git hoac kiem tra thu muc .git_bin." -ForegroundColor Red
    Exit 1
}

# Khoi tao Git repository neu chua co
if (-not (Test-Path (Join-Path $projectRoot ".git"))) {
    Write-Host "[+] Khoi tao Git repository lan dau..." -ForegroundColor Cyan
    & $gitCmd init | Out-Null
    & $gitCmd branch -M main | Out-Null
}

# Kiem tra remote origin
$originUrl = (& $gitCmd remote get-url origin 2>$null)
if (-not $originUrl) {
    Write-Host "==========================================================" -ForegroundColor Yellow
    Write-Host "  CAU HINH LIEN KET GITHUB LAN DAU" -ForegroundColor Yellow
    Write-Host "==========================================================" -ForegroundColor Yellow
    $repoUrl = Read-Host "Nhap link GitHub repo cua ban (Vi du: https://github.com/user/repo.git)"
    if ($repoUrl) {
        & $gitCmd remote add origin $repoUrl
        Write-Host "[+] Da lien ket toi: $repoUrl" -ForegroundColor Green
    } else {
        Write-Host "[-] Chua nhap link repo. Dung chuong trinh." -ForegroundColor Red
        Exit 1
    }
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  SMARTBAND S3: AUTO-DEPLOY WATCHER DANG CHAY..." -ForegroundColor Green
Write-Host "  Moi khi ban luu file index.html hoac admin.html (Ctrl + S)," -ForegroundColor White
Write-Host "  He thong se TU DONG day len GitHub Pages ngay lap tuc!" -ForegroundColor White
Write-Host "  (Nhan Ctrl + C de dung watcher bat cu luc nao)" -ForegroundColor DarkGray
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

$filesToWatch = @("index.html", "admin.html")
$lastWriteTimes = @{}

foreach ($f in $filesToWatch) {
    $fullPath = Join-Path $projectRoot $f
    if (Test-Path $fullPath) {
        $lastWriteTimes[$f] = (Get-Item $fullPath).LastWriteTime
    }
}

while ($true) {
    Start-Sleep -Milliseconds 800
    try {
        $triggeredFile = $null
        foreach ($f in $filesToWatch) {
            $fullPath = Join-Path $projectRoot $f
            if (Test-Path $fullPath) {
                $currentWriteTime = (Get-Item $fullPath).LastWriteTime
                if (-not $lastWriteTimes.ContainsKey($f) -or ($currentWriteTime -gt $lastWriteTimes[$f])) {
                    $lastWriteTimes[$f] = $currentWriteTime
                    $triggeredFile = $f
                    break
                }
            }
        }

        if ($triggeredFile) {
            # Debounce 2s de editor luu xong hoan toan
            Start-Sleep -Seconds 2

            # Cap nhat lai timestamp cua tat ca file de tranh duplicate trigger
            foreach ($f in $filesToWatch) {
                $fullPath = Join-Path $projectRoot $f
                if (Test-Path $fullPath) {
                    $lastWriteTimes[$f] = (Get-Item $fullPath).LastWriteTime
                }
            }

            $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "`n[$timestamp] Phat hien thay doi tai file: $triggeredFile" -ForegroundColor Yellow
            Write-Host ">> Dang tu dong add va commit index.html & admin.html..." -ForegroundColor Cyan

            & $gitCmd add index.html admin.html
            & $gitCmd commit -m "Auto deploy update ($triggeredFile): $timestamp" 2>$null | Out-Null

            Write-Host ">> Dang day len GitHub (git push origin main)..." -ForegroundColor Cyan
            $pushResult = & $gitCmd push origin main 2>&1

            if ($LASTEXITCODE -eq 0) {
                Write-Host "[V] DEPLOY THANH CONG LEN GITHUB PAGES!" -ForegroundColor Green
                Write-Host "    - Trang nguoi dung: https://vtt132109.github.io/vong-tay-thong-minh/" -ForegroundColor White
                Write-Host "    - Trang quan tri:  https://vtt132109.github.io/vong-tay-thong-minh/admin.html" -ForegroundColor White
            } else {
                Write-Host "[-] Push that bai: $pushResult" -ForegroundColor Red
            }
            Write-Host ">> Tiep tuc theo doi index.html & admin.html..." -ForegroundColor DarkGray
        }
    } catch {
        # Bo qua loi tam thoi khi file bi khoa luc dang luu
    }
}
