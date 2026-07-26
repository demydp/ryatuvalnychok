; Инсталлятор "Рятувальничок". Собирается через installer/build.ps1 (PyInstaller -> этот
; скрипт), не напрямую — build.ps1 передаёт /DMyAppVersion=X.Y.Z из app/version.py, чтобы
; версия установщика никогда не расходилась с версией, которую видит "Перевірити оновлення"
; внутри программы (см. app/version.py, app/update_checker.py).
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "Рятувальничок"
#define MyAppExeName "Ryatuvalnychok.exe"

[Setup]
; Сгенерирован один раз для этого продукта — НЕ менять между версиями, иначе Inno Setup
; будет считать каждый релиз новой отдельной программой вместо обновления существующей.
AppId={{09423062-62E4-4389-AF88-12A11C26AA1D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
; Мьютекс совпадает с APP_MUTEX_NAME в run.py — тихое обновление (/FORCECLOSEAPPLICATIONS,
; см. app/update_checker.py) находит и закрывает по нему уже запущенный процесс сам.
AppMutex=RyatuvalnychokSingleInstance
; Без прав администратора: ставим в профиль пользователя (как VS Code/Chrome), а не в Program
; Files — так первый запуск не пугает UAC-окном, что для не-технического покупателя продукта важно.
DefaultDirName={localappdata}\Programs\Ryatuvalnychok
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=RyatuvalnychokSetup
SetupIconFile=..\dashboard.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Данные пользователя (config.json, кэш, история, модель Whisper) живут в
; %LOCALAPPDATA%\Ryatuvalnychok (см. app/paths.py) — отдельно от {app} выше, поэтому
; переустановка/обновление поверх никогда их не трогает.

[Languages]
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[CustomMessages]
russian.LaunchAtStartup=Запускать при входе в Windows (в фоне, без окна браузера)
ukrainian.LaunchAtStartup=Запускати при вході в Windows (у фоні, без вікна браузера)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:LaunchAtStartup}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Ryatuvalnychok\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
