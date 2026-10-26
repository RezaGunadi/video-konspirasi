# Siapkan mini PC (Windows) untuk Video Konspirasi AI: akses SSH dari laptop (pakai kunci, tanpa password),
# firewall hanya untuk jaringan lokal, dan Ollama yang bisa dipakai laptop lewat LAN.
# Jalankan SEKALI: klik kanan siapkan-minipc.bat -> Run as administrator.
$ErrorActionPreference = 'Stop'
$kunci = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG/IlR6oiwlNiYkmuqGWR1IVMJ869ht+N/+GtufOKDpI video-konspirasi-laptop'

Write-Host '1/5 Memasang OpenSSH Server (bisa 1-3 menit)...'
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
if ($cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
Set-Service sshd -StartupType Automatic
Start-Service sshd

Write-Host '2/5 Memasang kunci akses laptop...'
# akun administrator membaca kunci dari file ini (bukan dari folder .ssh pengguna)
$authAdmin = 'C:\ProgramData\ssh\administrators_authorized_keys'
if (-not (Test-Path $authAdmin) -or -not (Select-String -Path $authAdmin -SimpleMatch $kunci -Quiet)) {
    Add-Content -Path $authAdmin -Value $kunci -Encoding ascii
}
icacls $authAdmin /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
$authUser = Join-Path $env:USERPROFILE '.ssh\authorized_keys'
New-Item -ItemType Directory -Force (Split-Path $authUser) | Out-Null
if (-not (Test-Path $authUser) -or -not (Select-String -Path $authUser -SimpleMatch $kunci -Quiet)) {
    Add-Content -Path $authUser -Value $kunci -Encoding ascii
}

Write-Host '3/5 Firewall: SSH dan Ollama hanya dari jaringan lokal...'
foreach ($r in @(@{N = 'Video AI - SSH'; P = 22 }, @{N = 'Video AI - Ollama'; P = 11434 })) {
    if (-not (Get-NetFirewallRule -DisplayName $r.N -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $r.N -Direction Inbound -Protocol TCP -LocalPort $r.P `
            -RemoteAddress LocalSubnet -Action Allow -Profile Any | Out-Null
    }
}

Write-Host '4/5 Ollama boleh diakses dari laptop (OLLAMA_HOST=0.0.0.0:11434)...'
[Environment]::SetEnvironmentVariable('OLLAMA_HOST', '0.0.0.0:11434', 'Machine')

Write-Host '5/5 Info mini PC (kirim baris di bawah ini ke Claude):'
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name.Trim()
$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }).IPAddress -join ', '
Write-Host ''
Write-Host "Nama: $env:COMPUTERNAME | User: $env:USERNAME | CPU: $cpu | RAM: $ram GB | IP: $ip" -ForegroundColor Green
