# Lance l'interface sans console Python supplémentaire.
$projectPath = $PSScriptRoot
$localPython = Join-Path $projectPath '.venv\Scripts\pythonw.exe'
$workspacePython = Join-Path (Split-Path -Parent $projectPath) '.venv\Scripts\pythonw.exe'
if (Test-Path -LiteralPath $localPython -PathType Leaf) {
    $pythonPath = $localPython
} elseif (Test-Path -LiteralPath $workspacePython -PathType Leaf) {
    $pythonPath = $workspacePython
} else {
    throw 'Environnement Python introuvable. Suivez les commandes d’installation du README.'
}
Start-Process -FilePath $pythonPath -ArgumentList '-m', 'app.main' -WorkingDirectory $projectPath -WindowStyle Hidden
