; Pixal Setup - Inno Setup script
;
; Built by install\build_installer.py, which stages the tree, generates
; components.iss from catalog.json and passes the version in. Do not run ISCC
; on this directly.
;
; Everything happens on the wizard's own pages. The setup engine still does the
; work - same plan, same downloads, same resume - but it runs with --headless
; and reports through a file, so there is no local web server, no browser tab
; and nothing left open when the wizard closes.
;
; Per-user by design: {localappdata}\Programs\Pixal, PrivilegesRequired=lowest
; and NO install-mode dialog. "Never asks for admin" means never asking.

#ifndef MyVersion
  #define MyVersion "1.4.1b"
#endif
#ifndef MyStage
  #define MyStage "_build\stage"
#endif

#define MyName    "Pixal"
#define MyExeName "Pixal.exe"

[Setup]
AppId={{8F3A6C21-4B7E-4E2A-9C5D-1A7B2E9F4D63}
AppName={#MyName}
AppVersion={#MyVersion}
AppVerName={#MyName} {#MyVersion}
AppPublisher=Pixal
VersionInfoVersion=1.0.0
VersionInfoDescription=Pixal Setup
DefaultDirName={localappdata}\Programs\Pixal
DefaultGroupName={#MyName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
AllowNoIcons=yes
PrivilegesRequired=lowest
OutputDir=..\
OutputBaseFilename=Pixal-Setup-{#MyVersion}-win-x64
SetupIconFile=..\web\icons\pixal-block.ico
UninstallDisplayIcon={app}\web\icons\pixal-block.ico
UninstallDisplayName={#MyName} {#MyVersion}
LicenseFile=..\LICENSE
WizardStyle=modern
WizardImageFile=wizard\wizard.bmp,wizard\wizard@125.bmp,wizard\wizard@150.bmp,wizard\wizard@175.bmp,wizard\wizard@200.bmp
WizardSmallImageFile=wizard\wizard-small.bmp,wizard\wizard-small@125.bmp,wizard\wizard-small@150.bmp,wizard\wizard-small@175.bmp,wizard\wizard-small@200.bmp
WizardImageStretch=yes
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no
DirExistsWarning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

; Lanes are generated from install\catalog.json at build time so this file and
; the catalog can never drift apart.
#include "_build\components.iss"

[Files]
Source: "{#MyStage}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; AppUserModelID is the taskbar fold: pixal.vbs opens the studio as
; `chrome --app=http://127.0.0.1:8190`, and Chrome stamps that window with
; AppUserModelID "Chrome.127.0.0.1_/" (host + path, no port). A pinned
; shortcut carrying the SAME id absorbs the window - one button, Pixal's
; icon, pinnable. Without it the window groups under Chrome and the user
; gets two buttons (2026-08-24). Never a Chrome._crx_ id here: that is what
; an installed PWA's window carries, and pointing the shortcut at it breaks
; the fold on every machine that has NOT installed the PWA - i.e. every
; fresh install.
Name: "{group}\{#MyName}";           Filename: "{app}\{#MyExeName}"; IconFilename: "{app}\web\icons\pixal-block.ico"; Comment: "Open Pixal"; AppUserModelID: "Chrome.127.0.0.1_/"
Name: "{group}\Pixal Setup";         Filename: "{app}\{#MyExeName}"; Parameters: "--setup"; IconFilename: "{app}\web\icons\pixal-block.ico"; Comment: "Add or repair ComfyUI and models"
Name: "{group}\Uninstall {#MyName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyName}";     Filename: "{app}\{#MyExeName}"; IconFilename: "{app}\web\icons\pixal-block.ico"; Tasks: desktopicon; AppUserModelID: "Chrome.127.0.0.1_/"

[Run]
Filename: "{app}\{#MyExeName}"; Description: "Open &Pixal now"; Flags: nowait postinstall skipifsilent; Check: EngineSucceeded

[UninstallDelete]
; Everything created AFTER install, which Inno's own file list cannot know
; about. Without these the folder survives an uninstall with a venv in it and
; "uninstalling is deleting a folder" stops being true.
Type: filesandordirs; Name: "{app}\install\_work"
Type: filesandordirs; Name: "{app}\install\runtime"
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\chats"
Type: files;          Name: "{app}\config.json"
Type: files;          Name: "{app}\.pixal_python"
Type: files;          Name: "{app}\history.jsonl"
Type: filesandordirs; Name: "{localappdata}\Pixal\_setup"
Type: dirifempty;     Name: "{localappdata}\Pixal"
Type: dirifempty;     Name: "{app}"

[Messages]
WelcomeLabel1=Welcome to Pixal
WelcomeLabel2=Pixal is a studio for making images and video on your own machine.%n%nThis installs Pixal itself, then downloads ComfyUI and the models you choose. Everything stays on this computer - nothing is uploaded.
FinishedHeadingLabel=Pixal is ready
ClickFinish=Click Finish to close Setup.

[Code]
var
  ComfyPage:  TInputDirWizardPage;
  WorkPage:   TOutputProgressWizardPage;
  FreshComfy: Boolean;
  RanEngine:  Boolean;
  EngineOK: Boolean;
  EngineProgFile: String;
  StopButton: TNewButton;
  DriverMajor: Integer;
  GpuName: String;

const
  DRIVER_MIN = 580;   { torch cu130, what the pinned ComfyUI portable ships }
  { A line whose first character is a hash is read by Inno's preprocessor
    even inside code, so a wrapped string can never start with one.
    Naming it once avoids the trap entirely. }
  NL2 = #13#10#13#10;

function ReadKey(const FileName, Key: String): String;
var
  Lines: TArrayOfString;
  i: Integer;
begin
  Result := '';
  if not FileExists(FileName) then Exit;
  if not LoadStringsFromFile(FileName, Lines) then Exit;
  for i := 0 to GetArrayLength(Lines) - 1 do
    if Pos(Key + '=', Lines[i]) = 1 then begin
      Result := Copy(Lines[i], Length(Key) + 2, MaxInt);
      Exit;
    end;
end;

function JsonPath(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
  StringChangeEx(Result, #13, '\r', True);
  StringChangeEx(Result, #10, '\n', True);
  StringChangeEx(Result, #9, '\t', True);
end;

function EngineSucceeded: Boolean;
begin
  Result := EngineOK;
end;

procedure StopEngine(Sender: TObject);
begin
  if SaveStringToFile(ChangeFileExt(EngineProgFile, '.cancel'), 'cancel', False) then begin
    StopButton.Enabled := False;
    StopButton.Caption := 'Stopping...';
  end else
    MsgBox('Could not request cancellation. Check folder permissions.', mbError, MB_OK);
end;

procedure EngineOutput(const S: String; const Error, FirstLine: Boolean);
begin
  WorkPage.SetProgress(StrToIntDef(ReadKey(EngineProgFile, 'pct'), 0), 100);
  WorkPage.SetText(ReadKey(EngineProgFile, 'step'), ReadKey(EngineProgFile, 'detail'));
end;

{ nvidia-smi through cmd so its output can be redirected to a file. Pascal has
  no pipe, and the two facts needed here - is there a driver, and how old is
  it - are one line of CSV. }
procedure DetectGpu;
var
  Tmp, S: String;
  Code, i: Integer;
  Lines: TArrayOfString;
begin
  DriverMajor := 0;
  Tmp := ExpandConstant('{tmp}\gpu.txt');
  Exec(ExpandConstant('{cmd}'),
       '/c nvidia-smi --query-gpu=name,driver_version --format=csv,noheader > "' +
       Tmp + '" 2>&1', '', SW_HIDE, ewWaitUntilTerminated, Code);
  if not FileExists(Tmp) then Exit;
  if not LoadStringsFromFile(Tmp, Lines) then Exit;
  if GetArrayLength(Lines) = 0 then Exit;
  S := Trim(Lines[0]);
  i := Pos(',', S);
  if i = 0 then Exit;
  GpuName := Trim(Copy(S, 1, i - 1));
  S := Trim(Copy(S, i + 1, MaxInt));
  i := Pos('.', S);
  if i > 0 then S := Copy(S, 1, i - 1);
  DriverMajor := StrToIntDef(Trim(S), 0);
end;

function LooksLikeComfy(const Dir: String): Boolean;
begin
  Result := FileExists(Dir + '\main.py') or DirExists(Dir + '\models');
end;

{ Shallow and cheap: the top level of every drive, plus the usual user folders.
  A deep walk is minutes of disk for a question the user can answer by typing,
  and this only has to fill in a default they can correct. }
function DetectComfy: String;
var
  Drives, Names: TArrayOfString;
  FR: TFindRec;
  d, n: Integer;
  Root, Cand: String;
begin
  Result := '';
  Drives := ['C:', 'D:', 'E:', 'F:', 'G:', 'X:', 'Y:', 'Z:'];
  Names  := [ExpandConstant('{userdocs}'), ExpandConstant('{userdesktop}'),
             ExpandConstant('{localappdata}\Programs')];
  for d := 0 to GetArrayLength(Drives) - 1 do begin
    Root := Drives[d] + '\';
    if not DirExists(Root) then Continue;
    if FindFirst(Root + '*Comfy*', FR) then try
      repeat
        if (FR.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then begin
          Cand := Root + FR.Name;
          if LooksLikeComfy(Cand) then begin Result := Cand; Exit; end;
          if LooksLikeComfy(Cand + '\ComfyUI') then begin Result := Cand; Exit; end;
        end;
      until not FindNext(FR);
    finally
      FindClose(FR);
    end;
  end;
  for n := 0 to GetArrayLength(Names) - 1 do begin
    Cand := Names[n] + '\ComfyUI';
    if LooksLikeComfy(Cand) then begin Result := Cand; Exit; end;
  end;
end;

procedure InitializeWizard;
begin
  ComfyPage := CreateInputDirPage(wpSelectComponents,
    'ComfyUI', 'Pixal renders through ComfyUI.',
    'If you already have ComfyUI, point Pixal at it - nothing inside it is ' +
    'changed except the node packs Pixal needs. If you do not have it, Pixal ' +
    'will install its own copy at this location.', False, '');
  ComfyPage.Add('');
  WorkPage := CreateOutputProgressPage('Setting up',
    'Downloading ComfyUI and the models you chose. This resumes if it is ' +
    'interrupted - you can close Setup and run it again without losing work.');
  StopButton := TNewButton.Create(WizardForm);
  StopButton.Parent := WorkPage.Surface;
  StopButton.Caption := 'Cancel setup';
  StopButton.SetBounds(0, WorkPage.ProgressBar.Top + WorkPage.ProgressBar.Height + ScaleY(24), ScaleX(120), ScaleY(25));
  StopButton.OnClick := @StopEngine;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Found: String;
begin
  Result := True;
  if CurPageID = wpWelcome then begin
    DetectGpu;
    if DriverMajor = 0 then begin
      MsgBox('No NVIDIA driver responded.' + NL2 +
             'Pixal renders on NVIDIA GPUs. If you have one, install its ' +
             'driver from nvidia.com and run Setup again.',
             mbCriticalError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
  if CurPageID = wpSelectComponents then begin
    WizardSelectComponents(ResolveLaneSelection(WizardSelectedComponents(False)));
    if ComfyPage.Values[0] = '' then begin
      Found := DetectComfy;
      FreshComfy := Found = '';
      if FreshComfy then
        ComfyPage.Values[0] := ExpandConstant('{sd}\ComfyUI')
      else
        ComfyPage.Values[0] := Found;
    end;
  end;
  if CurPageID = ComfyPage.ID then begin
    if Trim(ComfyPage.Values[0]) = '' then begin
      MsgBox('Choose where ComfyUI is, or where it should go.', mbError, MB_OK);
      Result := False;
    end else
      { Both shapes DetectComfy accepts, or a portable root (ComfyUI one
        level down) gets reclassified as a fresh target - which aimed a
        2.1 GB unpack at a real install on 2026-08-19. The engine guard
        would now refuse it, but the lane must read right here too. }
      FreshComfy := not (LooksLikeComfy(ComfyPage.Values[0])
        or LooksLikeComfy(ComfyPage.Values[0] + '\ComfyUI'));
    if FreshComfy and (DriverMajor < DRIVER_MIN) then begin
      MsgBox('The new ComfyUI portable needs NVIDIA driver ' + IntToStr(DRIVER_MIN) +
             ' or newer. Update your driver, or select an existing working ComfyUI.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function ChosenLanes: String;
var
  i: Integer;
  Ids: TArrayOfString;
begin
  Result := '';
  Ids := LaneIds;                       { generated into components.iss }
  for i := 0 to GetArrayLength(Ids) - 1 do
    if WizardIsComponentSelected(Ids[i]) then begin
      if Result <> '' then Result := Result + ',';
      Result := Result + '"' + Ids[i] + '"';
    end;
end;

{ Hands the engine exactly what the wizard already asked, then watches the
  progress file it writes. Same worker the browser flow drove - same plan,
  same downloads, same resume - reporting through a file instead of a socket,
  so nothing is left listening and no tab stays open. }
procedure RunEngine;
var
  ChoicesFile, ProgFile, Json, Phase, Err: String;
  Code: Integer;
begin
  RanEngine := True;
  EngineOK := False;
  ForceDirectories(ExpandConstant('{app}\install\_work'));
  ChoicesFile := ExpandConstant('{app}\install\_work\choices.json');
  ProgFile    := ExpandConstant('{app}\install\_work\progress.txt');
  EngineProgFile := ProgFile;
  DeleteFile(ProgFile);
  DeleteFile(ChangeFileExt(ProgFile, '.cancel'));

  Json := '{"lanes":[' + ChosenLanes + '],"comfy":{"mode":"';
  if FreshComfy then Json := Json + 'install' else Json := Json + 'use';
  Json := Json + '","path":"' + JsonPath(ComfyPage.Values[0]) +
          '"},"home":"' + JsonPath(ExpandConstant('{app}')) +
          '","tidy":true}';
  if not SaveStringToFile(ChoicesFile, Utf8Encode(Json), False) then
    RaiseException('Could not save setup choices. Check folder permissions.');

  WorkPage.SetProgress(0, 100);
  WorkPage.SetText('Starting', '');
  WorkPage.Show;
  try
    if not ExecAndLogOutput(ExpandConstant('{app}\install\runtime\python.exe'),
      '-X utf8 -u "' + ExpandConstant('{app}\install\pixal_install.py') + '" --headless "' +
      ChoicesFile + '" "' + ProgFile + '"', ExpandConstant('{app}'),
      SW_HIDE, ewWaitUntilTerminated, Code, @EngineOutput) then
      RaiseException('Could not start the setup engine: ' + SysErrorMessage(Code));
    Phase := ReadKey(ProgFile, 'phase');
    EngineOK := (Code = 0) and (Phase = 'done');
    Err := ReadKey(ProgFile, 'error');
    if not EngineOK then begin
      if Err = '' then Err := 'The setup engine stopped without confirming completion (exit ' + IntToStr(Code) + ').';
      MsgBox('Setup could not finish everything:' + NL2 + Err + NL2 +
             'Open Pixal Setup from the Start Menu to retry. Logs are in ' +
             ExpandConstant('{app}\install\_work') + '.', mbError, MB_OK);
    end;
  finally
    WorkPage.Hide;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and not EngineOK then begin
    WizardForm.FinishedHeadingLabel.Caption := 'Setup needs attention';
    WizardForm.FinishedLabel.Caption := 'Pixal setup did not complete. Open Pixal Setup from the Start Menu to retry; your existing files have been retained.';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not RanEngine) then RunEngine;
end;

function GetCustomSetupExitCode: Integer;
begin
  if EngineOK then Result := 0 else Result := 1;
end;
