' pixal.vbs - the taskbar entry point: one click, whole studio.
'
' Verbs:
'   (none)    a person clicked: make sure the studio is up, then open the app
'             window once the sidecar answers. If it cannot come up, say so
'             and point at the log.
'   boot      unattended start (shell:startup, WMI): same boot path, but never
'             a window and never a dialog. Failures still land in the log.
'   restart   the sidecar is reloading its own code: wait for the OLD one to
'             let go of the port, then boot the new one (no window, no dialog).
'             Without the wait the status check below would see the outgoing
'             instance still answering and decline to spawn a replacement.
'   selftest  parse check for review tooling: prints ok, touches nothing.
'
' Boot discipline:
'   - The sidecar spawns hidden through cmd so stdout/stderr append to
'     logs\sidecar.log (rotated once at 5 MB). A sidecar that dies overnight
'     must leave a death note.
'   - The spawn lock (.pixal_spawn.lock) is touched every 500ms while the
'     spawning instance waits and deleted when it stops waiting. A fresh lock
'     (under 15s) means someone is genuinely mid-boot: do not spawn a rival
'     (the port-8188 bind fight of 2026-08-11), but keep waiting - a second
'     click during boot opens the window the moment the sidecar answers.
'   - The window always opens as chrome --app=, never chrome_proxy --app-id.
'     Chrome stamps a --app= window with AppUserModelID "Chrome.127.0.0.1_/"
'     (host + path, no port), and the Pixal shortcuts carry exactly that
'     System.AppUserModel.ID - so the window folds into the pinned taskbar
'     button instead of opening a second, Chrome-attributed one. A PWA window
'     (--app-id) would carry "Chrome._crx_<id>", match nothing the installer
'     wrote, and bring the second button back (2026-08-24, four rounds of
'     two-button days). No PWA, no discovery, no user step: the shortcut and
'     the window agree by construction.
Option Explicit

Const STATUS_TIMEOUT_MS = 900      ' the sidecar is local; slow means not up yet
Const WAIT_TICKS        = 60       ' 500ms each -> give python 30s to bind
Const LOCK_FRESH_S      = 15       ' owner touches every tick; older = dead owner
Const LOG_ROTATE_BYTES  = 5242880  ' 5 MB, rotated once to sidecar.log.1
Const HIDDEN            = 0
Const NORMAL            = 1

Dim shell, fso, root, base, mode
Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
base = "http://127.0.0.1:8190"

mode = ""
If WScript.Arguments.Count > 0 Then mode = LCase(WScript.Arguments(0))
If mode = "selftest" Then
    WScript.Echo "pixal.vbs parse ok"
    WScript.Quit 0
End If

Dim lock, up, iSpawned, ticks
lock = root & "\.pixal_spawn.lock"

If mode = "restart" Then
    ticks = 0
    Do While ticks < 40                       ' 20s for the old one to exit
        If Not Answering(base & "/api/status") Then Exit Do
        WScript.Sleep 500
        ticks = ticks + 1
    Loop
    ' The port closes BEFORE the process does. aiohttp still drains its open
    ' handlers, and the cmd wrapper that owns sidecar.log through >> lives until
    ' that finishes - so "status stopped answering" is NOT "the old one is gone".
    ' Spawning here put the new sidecar's redirect against a file the outgoing
    ' process still held, and it died on the redirect: "not answering after 30s"
    ' with nothing in the log to say why (2026-08-13, three times). The handle
    ' itself is the only honest signal.
    If Not WaitForLog(120) Then               ' up to 60s
        LogFallback "[pixal.vbs] sidecar.log still locked after 60s - " & _
                    "spawning anyway " & Now
    End If
End If

up = Answering(base & "/api/status")
iSpawned = False

If Not up Then
    If Not LockFresh() Then
        TouchLock
        RotateLog
        LogLine "[pixal.vbs] spawning sidecar (" & ModeName() & ") " & Now
        shell.Run SpawnCmd(), HIDDEN, False
        iSpawned = True
    End If
    ticks = 0
    Do While ticks < WAIT_TICKS
        WScript.Sleep 500
        If iSpawned Then TouchLock
        If Answering(base & "/api/status") Then
            up = True
            Exit Do
        End If
        ticks = ticks + 1
    Loop
    If iSpawned Then DropLock
End If

If up Then
    If mode <> "boot" And mode <> "restart" Then OpenApp
Else
    LogLine "[pixal.vbs] sidecar not answering after " & (WAIT_TICKS \ 2) & _
            "s (" & ModeName() & ") " & Now
    If mode <> "boot" And mode <> "restart" Then
        MsgBox "Pixal couldn't start." & vbCrLf & vbCrLf & _
               "The sidecar never answered on " & base & "." & vbCrLf & _
               "See logs\sidecar.log next to pixal.vbs for what happened.", _
               vbExclamation, "Pixal"
    End If
End If

' ---------------------------------------------------------------------------

Function ModeName()
    If mode = "" Then ModeName = "click" Else ModeName = mode
End Function

' True only when the sidecar answers its own status route. A bare TCP connect
' would go true the instant python binds, which is before the routes exist.
Function Answering(url)
    Dim http
    Answering = False
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    If Err.Number <> 0 Then Exit Function
    http.SetTimeouts STATUS_TIMEOUT_MS, STATUS_TIMEOUT_MS, _
                     STATUS_TIMEOUT_MS, STATUS_TIMEOUT_MS
    http.Open "GET", url, False
    http.Send
    If Err.Number = 0 Then Answering = (http.Status = 200)
    Err.Clear
    On Error GoTo 0
End Function

Function LockFresh()
    LockFresh = False
    On Error Resume Next
    If fso.FileExists(lock) Then
        LockFresh = _
            (DateDiff("s", fso.GetFile(lock).DateLastModified, Now) < LOCK_FRESH_S)
    End If
    On Error GoTo 0
End Function

Sub TouchLock()
    On Error Resume Next
    fso.CreateTextFile(lock, True).Close
    On Error GoTo 0
End Sub

Sub DropLock()
    On Error Resume Next
    fso.DeleteFile lock, True
    On Error GoTo 0
End Sub

Function LogPath()
    Dim dir
    dir = root & "\logs"
    On Error Resume Next
    If Not fso.FolderExists(dir) Then fso.CreateFolder dir
    On Error GoTo 0
    LogPath = dir & "\sidecar.log"
End Function

' One rotation, not a ring: sidecar.log -> sidecar.log.1 at 5 MB. If the move
' fails (an old sidecar still holds the file) just keep appending.
Sub RotateLog()
    On Error Resume Next
    If fso.FileExists(LogPath()) Then
        If fso.GetFile(LogPath()).Size > LOG_ROTATE_BYTES Then
            If fso.FileExists(LogPath() & ".1") Then
                fso.DeleteFile LogPath() & ".1", True
            End If
            fso.MoveFile LogPath(), LogPath() & ".1"
        End If
    End If
    On Error GoTo 0
End Sub

Sub LogLine(text)
    Dim f
    On Error Resume Next
    Set f = fso.OpenTextFile(LogPath(), 8, True)   ' 8 = ForAppending
    f.WriteLine text
    f.Close
    On Error GoTo 0
End Sub

' True once sidecar.log can be opened for append again - i.e. the outgoing
' "cmd /c ... >> sidecar.log" wrapper has actually exited. Nothing else tells
' us that: the process outlives both the port and the status route.
Function WaitForLog(maxTicks)
    Dim t, f
    WaitForLog = False
    For t = 1 To maxTicks
        On Error Resume Next
        Set f = fso.OpenTextFile(LogPath(), 8, True)
        If Err.Number = 0 Then
            f.Close
            Err.Clear
            On Error GoTo 0
            WaitForLog = True
            Exit Function
        End If
        Err.Clear
        On Error GoTo 0
        WScript.Sleep 500
    Next
End Function

' When sidecar.log is the thing that is broken, LogLine writes into the void -
' every "Pixal won't start" line this script has ever tried to leave about a
' locked log was swallowed by its own On Error Resume Next. This one lands
' somewhere else on purpose.
Sub LogFallback(text)
    Dim f
    On Error Resume Next
    Set f = fso.OpenTextFile(root & "\logs\sidecar.vbs.log", 8, True)
    If Err.Number = 0 Then
        f.WriteLine text
        f.Close
    End If
    Err.Clear
    On Error GoTo 0
End Sub

' The sidecar's stdout/stderr must land somewhere a human can find the morning
' after: run.bat runs hidden inside a cmd whose output appends to the log.
' "< NUL" is load-bearing, not tidiness. On Ctrl+C this cmd asks "Terminate
' batch job (Y/N)?"; with no stdin it waits FOREVER, still holding sidecar.log
' open through its >> redirect - which silently blocks the next spawn's own
' redirect, so the vbs waits its 30s and gives up with nothing in the log
' (2026-08-13, chasing "Pixal won't start"). EOF on stdin answers the prompt.
Function SpawnCmd()
    SpawnCmd = "cmd /c """"" & root & "\run.bat"" < NUL >> """ & _
               LogPath() & """ 2>&1"""
End Function

Function FindChrome(exeName)
    Dim dirs, d, p
    FindChrome = ""
    dirs = Array("%ProgramFiles%", "%ProgramFiles(x86)%", "%LocalAppData%")
    For Each d In dirs
        p = shell.ExpandEnvironmentStrings(d) & _
            "\Google\Chrome\Application\" & exeName
        If fso.FileExists(p) Then
            FindChrome = p
            Exit Function
        End If
    Next
End Function

' chrome --app= needs no installed PWA and no discovered id, and it is what
' keeps the window on the AppUserModelID the shortcuts carry. Without Chrome
' at all, the default browser.
Sub OpenApp()
    Dim exe
    exe = FindChrome("chrome.exe")
    If exe <> "" Then
        shell.Run """" & exe & """ --app=" & base, NORMAL, False
    Else
        shell.Run base, NORMAL, False
    End If
End Sub
