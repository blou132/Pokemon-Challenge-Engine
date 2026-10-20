Option Explicit
Dim shell, files, folder, executable, shortcutPath, shortcut
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
executable = files.BuildPath(folder, "Pokemon-Challenge-Engine.exe")
If Not files.FileExists(executable) Then
  MsgBox "Pokemon-Challenge-Engine.exe est introuvable dans ce dossier.", 16, "PCE"
  WScript.Quit 1
End If
shortcutPath = files.BuildPath(shell.SpecialFolders("Desktop"), "Pokemon Challenge Engine.lnk")
If files.FileExists(shortcutPath) Then
  MsgBox "Un raccourci portant ce nom existe deja. Il a ete conserve.", 64, "PCE"
  WScript.Quit 0
End If
Set shortcut = shell.CreateShortcut(shortcutPath)
shortcut.TargetPath = executable
shortcut.WorkingDirectory = folder
shortcut.IconLocation = executable & ",0"
shortcut.Save
MsgBox "Le raccourci a ete cree sur le bureau.", 64, "PCE"
