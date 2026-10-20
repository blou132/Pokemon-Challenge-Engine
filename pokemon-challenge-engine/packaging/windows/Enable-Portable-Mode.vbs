Option Explicit
Dim files, folder, marker, handle
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
marker = files.BuildPath(folder, "pce-portable.json")
If files.FileExists(marker) Then
  MsgBox "Le mode portable est deja active.", 64, "PCE"
  WScript.Quit 0
End If
If MsgBox("Fermez PCE avant de continuer. Les prochaines parties seront conservees dans user-data, pres de l'application. Les donnees existantes ne sont ni deplacees ni supprimees. Vous pourrez les importer depuis Parametres. Activer ce mode ?", 36, "PCE") <> 6 Then
  WScript.Quit 0
End If
Set handle = files.CreateTextFile(marker, False, False)
handle.WriteLine "{""schema_version"":1}"
handle.Close
MsgBox "Mode portable active. Conservez le dossier user-data lors des mises a jour.", 64, "PCE"
