Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' This forces Windows to find the exact folder this VBS file is sitting in
ScriptDirectory = FSO.GetParentFolderName(WScript.ScriptFullName)

' Explicitly run the powershell script using the correct folder path
WshShell.Run "powershell.exe -windowstyle hidden -file """ & ScriptDirectory & "\start_sync.ps1""", 0, False