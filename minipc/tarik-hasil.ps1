# Tarik video yang sudah jadi dari mini PC ke laptop: output\<nama mini PC>\<folder video>.
# Hanya folder yang sudah rampung (ada deskripsi.txt, ditulis paling akhir) dan belum ada di laptop.
# Daftar mini PC di data\pekerja.json (tidak ikut Git): [{"nama": "minipc-A", "host": "user@192.168.x.x"}, ...]
$ErrorActionPreference = 'Stop'
$akar = Split-Path $PSScriptRoot -Parent
$kunci = Join-Path $HOME '.ssh\minipc_ed25519'
$pekerja = Get-Content (Join-Path $akar 'data\pekerja.json') -Raw | ConvertFrom-Json
foreach ($p in $pekerja) {
    $tujuan = Join-Path $akar "output\$($p.nama)"
    New-Item -ItemType Directory -Force $tujuan | Out-Null
    try {
        # Tanpa tanda kutip & kurung kurawal: PowerShell 5.1 mengacaknya saat meneruskan argumen ke ssh.exe
        # ("${d%/}" pernah sampai sebagai "$d%/" sehingga nama folder berakhiran "/%/").
        # baris: "<folder> <waktu deskripsi.txt>"; video yang dibuat ulang punya waktu baru dan diunduh lagi
        $siap = ssh -i $kunci -o BatchMode=yes -o ConnectTimeout=8 $p.host `
            'cd ~/video-konspirasi/output 2>/dev/null && for d in */; do test -f $d/deskripsi.txt && echo $(basename $d) $(stat -c %Y $d/deskripsi.txt); done'
    } catch {
        Write-Host "$($p.nama) ($($p.host)) tidak terjangkau: $_" -ForegroundColor Yellow
        continue
    }
    $baru = 0
    foreach ($baris in $siap) {
        if (-not $baris) { continue }
        $f, $versi = $baris -split ' ', 2
        $lokal = Join-Path $tujuan $f
        $tanda = Join-Path $lokal '.versi'
        if ((Test-Path $tanda) -and ((Get-Content $tanda -Raw).Trim() -eq $versi)) { continue }
        Write-Host "Mengunduh $($p.nama)\$f ..."
        if (Test-Path $lokal) { Remove-Item -Recurse -Force $lokal }
        scp -q -r -i $kunci -o BatchMode=yes "$($p.host):video-konspirasi/output/$f" $tujuan
        Set-Content -Path $tanda -Value $versi -Encoding ascii
        $baru++
    }
    Write-Host "$($p.nama): $baru video baru/diperbarui, total $(@($siap).Count) di mini PC -> $tujuan" -ForegroundColor Green
}
