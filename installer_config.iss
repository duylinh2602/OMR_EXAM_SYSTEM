; installer_config.iss
[Setup]
AppId={{A3C98B20-1F2D-4D3E-9102-B7C8E2D99025}}
AppName=Hệ Thống Chấm Thi OMR 2026
AppVersion=2.0
AppPublisher=Trung Tâm GDNN-GDTX Lệ Thủy
DefaultDirName={autopf}\OMR_Exam_System
DefaultGroupName=OMR Exam System
OutputDir=dist_installer
OutputBaseFilename=Setup_OMR_System_2026
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
; 1. Sao chép toàn bộ cây thư mục build PyInstaller vào thư mục cài đặt
Source: "dist\OMR_Desktop_App\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 2. Giải nén trực tiếp tệp templates và tọa độ JSON vào đúng vị trí làm việc
Source: "templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "output\*.json"; DestDir: "{app}\output"; Flags: ignoreversion

[Icons]
Name: "{group}\Hệ Thống Chấm Thi OMR 2026"; Filename: "{app}\OMR_System.exe"
Name: "{autodesktop}\Hệ Thống Chấm Thi OMR 2026"; Filename: "{app}\OMR_System.exe"; Tasks: desktopicon

[Run]
Description: "{cm:LaunchProgram,Hệ Thống Chấm Thi OMR 2026}"; Filename: "{app}\OMR_System.exe"; Flags: nowait postinstall skipifsilent