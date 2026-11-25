; Compiled by build_installer.py. User data is deliberately never uninstalled.
#ifndef PackageDir
  #error PackageDir is required
#endif
[Setup]
AppId=ResearchInsight.Windows
AppName=Research Insight
AppVersion={#BuildVersion}
DefaultDirName={localappdata}\Programs\ResearchInsight
DefaultGroupName=Research Insight
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
DisableDirPage=no
OutputDir={#InstallerOutput}
OutputBaseFilename=ResearchInsight-Setup-{#BuildVersion}
Compression=lzma2
SolidCompression=yes
AppMutex=ResearchInsight-Running
UninstallDisplayIcon={app}\ResearchInsight.exe
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面启动快捷方式"; Flags: unchecked

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Excludes: "开始使用.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installed_usage.txt"; DestDir: "{app}"; DestName: "安装版使用说明.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\启动 Research Insight"; Filename: "{app}\ResearchInsightControl\ResearchInsightControl.exe"; Parameters: "--data-dir ""{code:DataDirectory}"""; WorkingDir: "{app}"
Name: "{group}\停止 Research Insight"; Filename: "{app}\ResearchInsight.exe"; Parameters: "--stop --data-dir ""{code:DataDirectory}"""; WorkingDir: "{app}"
Name: "{group}\卸载 Research Insight"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Research Insight"; Filename: "{app}\ResearchInsightControl\ResearchInsightControl.exe"; Parameters: "--data-dir ""{code:DataDirectory}"""; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
var
  DataPage: TInputDirWizardPage;

function DataDirectory(Param: String): String;
begin
  Result := DataPage.Values[0];
end;

function SupportedPath(Value: String): Boolean;
var I: Integer;
begin
  Result := False;
  for I := 1 to Length(Value) do
    if (Ord(Value[I]) < 33) or (Ord(Value[I]) > 126) then Exit;
  Result := True;
end;

procedure InitializeWizard;
begin
  DataPage := CreateInputDirPage(wpSelectDir, '选择用户数据目录',
    '账号、反馈、数据库和日志保存在这里',
    '卸载保留此目录。重装时选择同一目录。当前请选择纯英文、无空格的路径。', False, '');
  DataPage.Add('数据目录：');
  DataPage.Values[0] := GetPreviousData('DataDirectory', ExpandConstant('{localappdata}\ResearchInsightData'));
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'DataDirectory', DataPage.Values[0]);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var AppPath, DataPath: String;
begin
  Result := True;
  if (CurPageID = wpSelectDir) or (CurPageID = DataPage.ID) then begin
    if not SupportedPath(WizardDirValue) then begin
      MsgBox('当前程序路径只支持纯英文且无空格，请选择其他目录。', mbError, MB_OK);
      Result := False; Exit;
    end;
  end;
  if CurPageID = DataPage.ID then begin
    AppPath := Uppercase(AddBackslash(ExpandFileName(WizardDirValue)));
    DataPath := Uppercase(AddBackslash(ExpandFileName(DataPage.Values[0])));
    if not SupportedPath(DataPage.Values[0]) or
       (Length(DataPage.Values[0]) < 3) or
       (Copy(DataPage.Values[0], 2, 2) <> ':\') or
       (Copy(DataPath, 1, Length(AppPath)) = AppPath) or
       (Copy(AppPath, 1, Length(DataPath)) = DataPath) then begin
      MsgBox('请选择绝对数据路径，纯英文、无空格；程序与数据目录不能相同或互相包含。', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := MsgBox('卸载将删除程序和快捷方式，保留账号、反馈和数据库。请先在控制窗口选择“退出软件”，等窗口关闭。是否继续？', mbConfirmation, MB_YESNO) = IDYES;
end;
