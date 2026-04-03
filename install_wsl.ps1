dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
Write-Host '---------------------------------------'
Write-Host 'Kurulum tamamlandi! Pencereyi kapatabilirsiniz.'
Start-Sleep -Seconds 10
