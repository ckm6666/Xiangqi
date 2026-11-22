' Start the Xiangqi server in the background without a console window.
Option Explicit

Dim fso, shell, root, pythonw, script, command, code

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(root, "server\.venv\Scripts\pythonw.exe")
script = fso.BuildPath(root, "run_server.py")

If Not fso.FileExists(pythonw) Then
    MsgBox "server\.venv\Scripts\pythonw.exe not found." & vbCrLf & _
           "Create the server venv and install requirements first.", _
           16, "Xiangqi Server"
    WScript.Quit 1
End If

command = """" & pythonw & """ """ & script & """ --background"
code = shell.Run(command, 0, True)

If code <> 0 Then
    MsgBox "Failed to start the server." & vbCrLf & _
           "See server\data\server-8765.err.log for details.", _
           16, "Xiangqi Server"
End If
