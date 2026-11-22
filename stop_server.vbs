' Stop the background Xiangqi server started by start_server.vbs.
Option Explicit

Dim fso, shell, root, pythonw, script, command, code

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(root, "server\.venv\Scripts\pythonw.exe")
script = fso.BuildPath(root, "run_server.py")

If Not fso.FileExists(pythonw) Then
    MsgBox "server\.venv\Scripts\pythonw.exe not found.", _
           16, "Xiangqi Server"
    WScript.Quit 1
End If

command = """" & pythonw & """ """ & script & """ --stop"
code = shell.Run(command, 0, True)

If code <> 0 Then
    MsgBox "The background server is not running.", 64, "Xiangqi Server"
End If
