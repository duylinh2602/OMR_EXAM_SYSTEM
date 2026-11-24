; installer_config.iss
[Setup]
AppId={{A3C98B20-1F2D-4D3E-9102-B7C8E2D99025}}
AppName=Hệ Thống Chấm Thi OMR 2026
AppVersion=2.0
AppPublisher=Trung Tâm GDNN-GDTX Lệ Thủy
DefaultDirName={autopf}\OMR_Exam_System
DefaultGroupName=Hệ Thống Chấm Thi OMR 2026
OutputDir=dist_installer
OutputBaseFilename=Setup_OMR_System_2026
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\app_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
Name: "{app}\output"; Permissions: users-full
Name: "{app}\output\graded_sheets"; Permissions: users-full
Name: "{app}\output\web_uploads"; Permissions: users-full
Name: "{app}\templates"; Permissions: users-full

[Files]
; 1. Biểu tượng ứng dụng
Source: "app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

; 2. Toàn bộ cây thư mục biên dịch PyInstaller
Source: "dist\OMR_Desktop_App\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 3. Giải nén trực tiếp tệp templates và các tệp cấu hình tọa độ vào thư mục ứng dụng
Source: "templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "output\header_coordinates.json"; DestDir: "{app}\output"; Flags: ignoreversion
Source: "output\part1_coordinates.json"; DestDir: "{app}\output"; Flags: ignoreversion
Source: "output\part2_coordinates.json"; DestDir: "{app}\output"; Flags: ignoreversion
Source: "output\part3_coordinates.json"; DestDir: "{app}\output"; Flags: ignoreversion
Source: "output\MAU_DAP_AN_TRAC_NGHIEM_2025.xlsx"; DestDir: "{app}\output"; Flags: ignoreversion
Source: "output\exams_db.json"; DestDir: "{app}\output"; Flags: onlyifdoesntexist
Source: "PHIEU TLTN 40 CAU CUC QLCL.pdf"; DestDir: "{app}\output"; Flags: ignoreversion

[Icons]
Name: "{group}\Hệ Thống Chấm Thi OMR 2026"; Filename: "{app}\OMR_System.exe"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\Gỡ cài đặt Hệ Thống Chấm Thi OMR 2026"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Hệ Thống Chấm Thi OMR 2026"; Filename: "{app}\OMR_System.exe"; Tasks: desktopicon; IconFilename: "{app}\app_icon.ico"

[Run]
Description: "{cm:LaunchProgram,Hệ Thống Chấm Thi OMR 2026}"; Filename: "{app}\OMR_System.exe"; Flags: nowait postinstall skipifsilent
