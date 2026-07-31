' Launch a .bat with no console window and wait for exit code.
' Prevents Interactive Task Scheduler jobs from dying when the console is closed
' (STATUS_CONTROL_C_EXIT / -1073741510).
'
' Always passes --hidden so the bat does not re-launch itself.
Option Explicit
If WScript.Arguments.Count < 1 Then
  WScript.Quit 1
End If

Dim bat, sh, code, cmd
bat = WScript.Arguments(0)
Set sh = CreateObject("Wscript.Shell")
' 0 = hidden, True = wait
cmd = "cmd /c call """ & bat & """ --hidden"
code = sh.Run(cmd, 0, True)
WScript.Quit code
