; Instalador do Aimedget (Inno Setup).
;
; Compila a pasta gerada pelo PyInstaller (dist\Aimedget) num único Aimedget-Setup-<versão>.exe.
; Normalmente chamado por tools\build_release.ps1, que passa a versão lida de app\core\version.py:
;     ISCC.exe /DAppVersion=1.0.0 installer\Aimedget.iss
;
; Decisões:
; - Instalação POR USUÁRIO, sem pedir administrador (padrão de apps de bandeja, como Discord e Spotify):
;   vai para %LOCALAPPDATA%\Programs\Aimedget. O app já guarda tudo em %LOCALAPPDATA%\Aimedget.
; - AppId fixo: identifica o app para o Windows em TODAS as versões. Nunca mude, senão cada atualização
;   vira um "app novo" em Aplicativos instalados.
; - Atualização automática: o app roda este instalador com /SILENT /UPDATE (app\services\updater_service.py);
;   com /UPDATE o app é reaberto no fim.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Aimedget"
#define AppExe "Aimedget.exe"
#define AppPublisher "Aimedget"
#define AppUrl "https://github.com/allsz/aimedget"
; Mesmo ID de app que o Aimedget usa na barra de tarefas (app\main.py): o atalho e as janelas ficam no mesmo grupo
#define AppUserModelId "Aimedget.Hub"

[Setup]
AppId={{88436E81-8FDF-41FA-8814-3ECC71AE02E3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}

PrivilegesRequired=lowest
; Quem quiser instalar para todos os usuários (ex.: em C:\Program Files) escolhe isso numa caixa antes do assistente
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Sempre pergunta onde instalar (a pasta anterior vem preenchida numa reinstalação)
DisableDirPage=no
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

; Fecha o Aimedget se estiver aberto (instalar por cima de uma cópia em uso, ou a atualização automática)
CloseApplications=yes
RestartApplications=no

OutputDir=..\dist\release
OutputBaseFilename=Aimedget-Setup-{#AppVersion}
SetupIconFile=..\assets\aimedget_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; "dynamic": o assistente abre claro ou escuro conforme o tema de aplicativos do Windows do usuário
WizardStyle=modern dynamic
Compression=lzma2/ultra64
SolidCompression=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
brazilianportuguese.RemoveUserData=Remover também as suas configurações, temas e capas salvas do Aimedget?%n%nEscolha "Não" para mantê-los caso reinstale depois.
english.RemoveUserData=Also remove your Aimedget settings, themes and saved covers?%n%nChoose "No" to keep them in case you reinstall later.
brazilianportuguese.LaunchApp=Abrir o Aimedget
english.LaunchApp=Launch Aimedget

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Aimedget\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[InstallDelete]
; Uma versão nova pode ter removido arquivos: limpa a pasta de bibliotecas antes de copiar a nova
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelId}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelId}"; Tasks: desktopicon

[Run]
; Instalação normal: caixa "Abrir o Aimedget" no fim
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
; Atualização automática (silenciosa, com /UPDATE): reabre o app sozinho
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: IsAutoUpdate

[Code]
function IsAutoUpdate: Boolean;
begin
  Result := Pos('/UPDATE', UpperCase(GetCmdTail)) > 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    { "Iniciar com o Windows" grava este valor (app\core\config_manager.py). Sem remover, o Windows tentaria abrir
      um app que não existe mais a cada login. }
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Aimedget');
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\Aimedget');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox(CustomMessage('RemoveUserData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
