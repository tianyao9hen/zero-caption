; Zero Caption 的 Windows 单用户安装包定义。
;
; 安装包只负责把已经通过 PyInstaller 验证的便携目录复制到用户选择的目录，
; 不会在目标电脑下载 Python、FFmpeg、模型或其他运行组件。安装目录只允许
; 使用空目录或已属于 Zero Caption 的目录，因此卸载时可以安全清理其中的残留文件。

#define MyAppName "Zero Caption"
#define MyAppVersion "0.1.1"
#define MyAppPublisher "Zero Caption"
#define MyAppExeName "ZeroCaption.exe"
#define MyAppDataDirectoryName "ZeroCaption"
#define MyInstallMarkerName ".zero-caption-install-root"

; 完整发布目录超过数 GB。开发期可以传入 `/DInstallerSmokeTest=1`，只打包
; 安装目录标记来快速验证真实安装/卸载控制流；正式构建不会定义该开关。
#ifdef InstallerSmokeTest
  #define MyAppId "{{52DE2005-6574-4D05-80B8-60058136A16D}"
  #define MyPayloadSource "install-root.marker"
#else
  #define MyAppId "{{7E1E396A-6A63-45EE-B798-2C94890E41F2}"
  #define MyPayloadSource "..\dist\ZeroCaption\*"
#endif

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} 安装程序
DefaultDirName={localappdata}\Programs\ZeroCaption
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist\installer
OutputBaseFilename=ZeroCaption-{#MyAppVersion}-win64-setup
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
SetupIconFile=..\resources\icons\zero-caption.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "{#MyPayloadSource}"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "install-root.marker"; DestDir: "{app}"; DestName: "{#MyInstallMarkerName}"; Attribs: hidden; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 正常卸载会删除清单中的发布文件。下面再清理运行期可能写进安装目录的残留，
; 例如崩溃转储或旧版本文件；目录选择校验保证 `{app}` 不会是用户的共享文件夹。
Type: filesandordirs; Name: "{app}\*"
Type: dirifempty; Name: "{app}"

[Code]
var
  CleanUserHistory: Boolean;

function IsDirectoryEmpty(const Directory: String): Boolean;
var
  FindRec: TFindRec;
begin
  { 尚未创建的目录可以安全使用，安装器稍后会负责创建它。 }
  Result := True;
  if not DirExists(Directory) then
    Exit;

  { `FindFirst` 会枚举目录内容；跳过系统提供的当前目录和父目录占位项。 }
  if FindFirst(AddBackslash(Directory) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          Result := False;
          Exit;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function IsOwnedInstallDirectory(const Directory: String): Boolean;
var
  NormalizedDirectory: String;
begin
  NormalizedDirectory := AddBackslash(Directory);

  { 新版本使用隐藏标记确认目录所有权。两个旧版文件的组合用于兼容升级， }
  { 避免已经安装过的用户因为旧目录没有标记而无法覆盖安装。 }
  Result :=
    FileExists(NormalizedDirectory + '{#MyInstallMarkerName}') or
    (
      FileExists(NormalizedDirectory + '{#MyAppExeName}') and
      FileExists(NormalizedDirectory + 'unins000.exe')
    );
end;

function IsSafeInstallDirectory(const Directory: String): Boolean;
begin
  { 统一供交互向导和静默安装调用，避免命令行模式绕过目录所有权检查。 }
  Result := IsDirectoryEmpty(Directory) or IsOwnedInstallDirectory(Directory);
end;

function InstallDirectoryValidationMessage(): String;
begin
  Result :=
    '所选安装目录中已经存在其他文件。' + #13#10 + #13#10 +
    '为避免卸载时误删个人文件，请选择一个空目录，或新建一个专用于 Zero Caption 的目录。';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  InstallDirectory: String;
begin
  Result := True;
  { 静默模式也会经过页面事件，但不能在这里显示不可抑制的 `MsgBox`。 }
  { 让流程继续到 `ssInstall`，再由 `CurStepChanged` 使用 `Abort` 直接退出。 }
  if WizardSilent then
    Exit;

  if CurPageID <> wpSelectDir then
    Exit;

  { 卸载阶段需要清空整个安装目录，所以安装阶段不能接受混有个人文件的目录。 }
  InstallDirectory := RemoveBackslashUnlessRoot(WizardDirValue);
  if IsSafeInstallDirectory(InstallDirectory) then
    Exit;

  MsgBox(
    InstallDirectoryValidationMessage(),
    mbError,
    MB_OK
  );
  Result := False;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  InstallDirectory: String;
begin
  if CurStep <> ssInstall then
    Exit;

  { 静默安装不会点击“下一步”，所以在真正复制文件前再次执行同一检查。 }
  { `Abort` 从 `ssInstall` 事件调用时会立即结束安装，不会留下等待确认的隐藏窗口。 }
  InstallDirectory := RemoveBackslashUnlessRoot(WizardDirValue);
  if IsSafeInstallDirectory(InstallDirectory) then
    Exit;

  Log('已拒绝不安全的安装目录：' + InstallDirectory);
  Abort;
end;

function HasCleanHistoryParameter(): Boolean;
var
  ParameterIndex: Integer;
begin
  Result := False;
  for ParameterIndex := 1 to ParamCount do
  begin
    { 静默自动化不能弹窗，发布验收通过显式参数选择清理历史记录。 }
    if CompareText(ParamStr(ParameterIndex), '/CLEANHISTORY') = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  CleanUserHistory := HasCleanHistoryParameter();

  { 普通卸载必须由用户明确选择；默认按钮是“否”，避免误删项目和 API 配置。 }
  if not UninstallSilent then
  begin
    CleanUserHistory := MsgBox(
      '是否同时清理 Zero Caption 的历史记录？' + #13#10 + #13#10 +
      '选择“是”将永久删除项目记录、字幕、缓存、导出文件、日志和本机设置。' + #13#10 +
      '选择“否”只卸载软件，历史记录会保留，重新安装后仍可继续使用。',
      mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2
    ) = IDYES;
  end;
end;

function IsSafeTestHistoryDirectory(const Directory: String): Boolean;
var
  NormalizedDirectory: String;
  RequiredPrefix: String;
begin
  { 自动验收需要隔离真实用户数据。测试覆盖路径必须位于系统临时目录， }
  { 第一层目录还必须使用随机验收前缀，不能借这个入口删除任意路径。 }
  NormalizedDirectory := RemoveBackslashUnlessRoot(ExpandFileName(Directory));
  RequiredPrefix :=
    AddBackslash(RemoveBackslashUnlessRoot(ExpandFileName(GetEnv('TEMP')))) +
    'zero-caption-installer-';

  Result :=
    (Length(NormalizedDirectory) > Length(RequiredPrefix)) and
    (
      CompareText(
        Copy(NormalizedDirectory, 1, Length(RequiredPrefix)),
        RequiredPrefix
      ) = 0
    ) and
    (
      CompareText(
        ExtractFileName(NormalizedDirectory),
        '{#MyAppDataDirectoryName}'
      ) = 0
    );
end;

function ResolveUserDataDirectory(): String;
var
  TestHistoryDirectory: String;
begin
  TestHistoryDirectory := ExpandConstant('{param:TESTHISTORYROOT|}');
  if TestHistoryDirectory = '' then
  begin
    Result := ExpandConstant('{localappdata}\{#MyAppDataDirectoryName}');
    Exit;
  end;

  if IsSafeTestHistoryDirectory(TestHistoryDirectory) then
  begin
    Result := RemoveBackslashUnlessRoot(ExpandFileName(TestHistoryDirectory));
    Log('卸载验收使用隔离历史目录：' + Result);
  end
  else
  begin
    { 如果测试参数不安全就拒绝清理，绝不回退到真实用户目录。 }
    Result := '';
    Log('已拒绝不安全的卸载验收历史目录：' + TestHistoryDirectory);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataDirectory: String;
begin
  if (CurUninstallStep <> usPostUninstall) or not CleanUserHistory then
    Exit;

  { 用户历史统一位于 `%LOCALAPPDATA%\ZeroCaption`。只删除这个应用专属目录， }
  { 不处理用户主动导出到其他位置的文件，避免扩大卸载范围。 }
  UserDataDirectory := ResolveUserDataDirectory();
  if (UserDataDirectory = '') or not DirExists(UserDataDirectory) then
    Exit;

  if DelTree(UserDataDirectory, True, True, True) then
  begin
    Log('已清理 Zero Caption 用户历史目录：' + UserDataDirectory);
  end
  else
  begin
    Log('无法完整清理 Zero Caption 用户历史目录：' + UserDataDirectory);
    if not UninstallSilent then
    begin
      MsgBox(
        '部分历史记录正在被其他程序占用，未能全部删除：' + #13#10 +
        UserDataDirectory + #13#10 + #13#10 +
        '请关闭占用文件的程序后手动删除该目录。',
        mbError,
        MB_OK
      );
    end;
  end;
end;
