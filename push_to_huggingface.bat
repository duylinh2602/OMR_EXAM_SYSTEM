@echo off
chcp 65001 >nul
echo ============================================================
echo   DANG DONG BO VA DAY CODE LEN HUGGING FACE SPACES...
echo ============================================================

& "C:\Users\DinhDuyLinh\AppData\Local\GitHubDesktop\app-3.6.10\resources\app\git\cmd\git.exe" checkout --orphan hf-deploy
& "C:\Users\DinhDuyLinh\AppData\Local\GitHubDesktop\app-3.6.10\resources\app\git\cmd\git.exe" rm --cached -r cloudflared.exe dist_installer output/graded_sheets output/web_uploads output/*.pdf "PHIEU TLTN 40 CAU CUC QLCL.pdf" samples/ 2>nul
& "C:\Users\DinhDuyLinh\AppData\Local\GitHubDesktop\app-3.6.10\resources\app\git\cmd\git.exe" commit -m "deploy: update app on Hugging Face Spaces"
& "C:\Users\DinhDuyLinh\AppData\Local\GitHubDesktop\app-3.6.10\resources\app\git\cmd\git.exe" push -f space hf-deploy:main
& "C:\Users\DinhDuyLinh\AppData\Local\GitHubDesktop\app-3.6.10\resources\app\git\cmd\git.exe" checkout -f main
& "C:\Users\DinhDuyLinh\AppData\Local\GitHubDesktop\app-3.6.10\resources\app\git\cmd\git.exe" branch -D hf-deploy

echo ============================================================
echo   DA CAP NHAT LEN HUGGING FACE SPACES HOAN TAT!
echo ============================================================
pause
