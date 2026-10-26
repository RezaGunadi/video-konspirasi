"""Menyusun video akhir dengan ffmpeg: shot per shot → sambung → narasi + musik + subtitle."""
import random
import re
from pathlib import Path

from .alat import CACHE, FFMPEG, FFPROBE, MUSIK, ffmpeg, jalankan

FPS = 30
GESER_KATA = 0.1  # detik, lihat tulis_subtitle
UKURAN = {"9:16": (1080, 1920), "16:9": (1920, 1080)}
_encoder = None


def encoder():
    """h264_nvenc (GPU) kalau ada, kalau tidak libx264."""
    global _encoder
    if _encoder is None:
        try:
            jalankan([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
                      "-c:v", "h264_nvenc", "-f", "null", "-"], timeout=30)
            _encoder = "h264_nvenc"
        except RuntimeError:
            _encoder = "libx264"
    return _encoder


def _arg_encode(kualitas_tinggi=True):
    """kualitas_tinggi = file antara (shot). Shot dibuat TANPA B-frame: dengan B-frame, tiap file mulai dengan
    DTS negatif dan penyambungan kehilangan ±1 frame per sambungan, sehingga gambar makin lama makin maju
    dari narasi/subtitle (dan terasa "melompat" di tiap pergantian shot)."""
    tanpa_b = ["-bf", "0"] if kualitas_tinggi else []
    if encoder() == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19" if kualitas_tinggi else "22",
                "-b:v", "0", "-profile:v", "high", "-pix_fmt", "yuv420p", *tanpa_b]
    return ["-c:v", "libx264", "-preset", "veryfast" if kualitas_tinggi else "medium",
            "-crf", "18" if kualitas_tinggi else "20", "-pix_fmt", "yuv420p", *tanpa_b]


def _grade(gaya):
    """Gaya misterius: gelap & dingin (sorotan diredam lewat curves, bayangan kebiruan), saturasi rendah,
    vignette tegas, grain film, dan kedip cahaya halus seperti proyektor tua. Gaya cerah (video sains/fakta):
    sedikit lebih kontras, berwarna, dan tajam seperti dokumenter alam."""
    if gaya == "cerah":
        return ",eq=contrast=1.05:saturation=1.12,unsharp=5:5:0.35"
    if gaya != "misterius":
        return ""
    return (",eq=contrast=1.2:saturation=0.55:brightness='-0.04+0.012*sin(t*7.3)+0.008*sin(t*12.9)':eval=frame,"
            "curves=all='0/0 0.25/0.17 0.5/0.38 0.75/0.6 1/0.8',"
            "colorbalance=rs=-0.08:bs=0.12:rm=-0.05:bm=0.08:rh=-0.06:bh=0.08,"
            "vignette=PI/3.4,noise=alls=10:allf=t+u")


def kabut(format_video):
    """Tekstur kabut putih transparan (dibuat sekali, ukuran 1,5x layar) untuk ditumpuk dan digeser pelan."""
    W, H = UKURAN[format_video]
    w2, h2 = W * 3 // 2, H * 3 // 2
    tujuan = CACHE / f"kabut-{w2}x{h2}.png"
    if tujuan.exists():
        return tujuan
    abu = CACHE / f"kabut-abu-{w2}x{h2}.png"
    ffmpeg(["-f", "lavfi", "-i", f"nullsrc=s={w2 // 2}x{h2 // 2},geq=lum='random(1)*255':cb=128:cr=128",
            "-frames:v", "1", "-vf", f"gblur=sigma=40,eq=contrast=4:brightness=-0.15,gblur=sigma=12,"
            f"scale={w2}:{h2},format=gray", str(abu)], timeout=120)
    ffmpeg(["-f", "lavfi", "-i", f"color=white:s={w2}x{h2}", "-i", str(abu), "-filter_complex",
            "[0:v]format=rgba[w];[1:v]format=gray,lutyuv=y='val*0.35'[a];[w][a]alphamerge",
            "-frames:v", "1", str(tujuan)], timeout=120)
    abu.unlink(missing_ok=True)
    return tujuan


# Transisi di shot pertama tiap adegan (dipilih efek.rencana sesuai isi adegan; "zoom" dikerjakan di zoompan).
_TRANSISI = {
    "glitch": (",rgbashift=rh=-16:bh=16:rv=4:bv=-4:enable='lt(t,0.2)',noise=alls=50:allf=t:enable='lt(t,0.16)',"
               "eq=brightness=0.18:enable='lt(t,0.05)'"),
    "kilat": ",eq=brightness=0.55:saturation=0.3:enable='lt(t,0.05)',eq=brightness=0.22:enable='between(t,0.05,0.12)'",
    "terbakar": (",colorbalance=rs=0.55:gs=0.15:bs=-0.45:rm=0.3:enable='lt(t,0.25)',"
                 "eq=brightness=0.28:contrast=1.3:enable='lt(t,0.12)'"),
    "whip": ",gblur=sigma=45:sigmaV=0.5:enable='lt(t,0.08)',gblur=sigma=16:sigmaV=0.5:enable='between(t,0.08,0.16)'",
    "gelap": ",fade=in:st=0:d=0.35",
    "zoom": ",eq=brightness=0.12:enable='lt(t,0.06)'",
}

# Gerak kamera (Ken Burns) di kanvas 2x: dulu hanya 4 macam dan bergiliran. "hentak" = zoom cepat di awal (adegan
# penting), "goyang" = sedikit bergetar seperti kamera tangan (adegan menegangkan).
_GERAK = {
    "masuk": ("1+0.15*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "kanan": ("1.12", "(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"),
    "keluar": ("1.15-0.15*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "turun": ("1.12", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*on/{n}"),
    "diagonal": ("1.05+0.12*on/{n}", "(iw-iw/zoom)*(0.2+0.6*on/{n})", "(ih-ih/zoom)*(0.7-0.4*on/{n})"),
    "kiri": ("1.12", "(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"),
    "naik": ("1.12", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{n})"),
    "hentak": ("1+0.2*(1-exp(-on/6))+0.04*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "goyang": ("1.1+0.04*on/{n}", "iw/2-(iw/zoom/2)+9*sin(on*0.31)+5*sin(on*0.73)",
               "ih/2-(ih/zoom/2)+7*cos(on*0.27)"),
}
_GILIRAN_GERAK = ("masuk", "kanan", "keluar", "turun", "diagonal", "kiri", "naik")


def _efek_misterius(gaya, format_video, nomor, transisi, masuk):
    """Kabut yang bergerak pelan + glitch singkat di awal adegan (gaya misterius). Mengembalikan
    (input tambahan, filter yang dipasang setelah [g] → [o] tanpa tpad). Gaya cerah: tanpa kabut, transisinya yang
    halus saja (glitch & terbakar diganti whip)."""
    if gaya == "cerah":
        transisi = "whip" if transisi is True else {"glitch": "whip", "terbakar": "whip"}.get(transisi, transisi)
        return masuk, ";[g]null" + _TRANSISI.get(transisi, "")
    if gaya != "misterius":
        return masuk, ";[g]null"
    W, H = UKURAN[format_video]
    s1, s2 = (nomor * 1.7) % 6.28, (nomor * 2.9) % 6.28  # tiap shot kabutnya bergerak beda arah
    idx = masuk.count("-i")  # nomor input kabut = setelah semua input gambar
    masuk = [*masuk, "-loop", "1", "-framerate", str(FPS), "-i", str(kabut(format_video))]
    f = (f";[{idx}:v]crop={W}:{H}:x='(iw-{W})*(0.5+0.45*sin(t*0.13+{s1:.2f}))':"
         f"y='(ih-{H})*(0.5+0.45*cos(t*0.09+{s2:.2f}))'[f];[g][f]overlay=0:0")
    if transisi is True:
        transisi = "glitch"
    f += _TRANSISI.get(transisi, "")
    return masuk, f


def _terangkan(bahan):
    """Foto yang memang gelap (foto Apollo AS11-39-5839: rata-rata 28 dari 255) jadi hitam pekat setelah grade
    "misterius" yang menggelapkan. Sumber dengan kecerahan rata-rata di bawah 70 dinaikkan dulu dengan gamma."""
    terang = kecerahan(bahan["file"], (bahan.get("mulai") or 0) + (0.5 if bahan["jenis"] == "video" else 0))
    if not terang or terang >= 70:
        return ""
    gamma = min(2.2, (95 / max(terang, 10)) ** 0.55)
    return f"eq=gamma={gamma:.2f}:contrast=1.05,"


# Skala stiker per frame saat muncul (±0,27 detik): membesar melewati ukuran akhir lalu memantul balik ("meletup").
_POP_STIKER = (0.5, 0.78, 1.0, 1.1, 1.12, 1.07, 1.02, 1.0)
_SUDUT_STIKER = (-4.0, 3.0, -2.5, 4.5, -3.5, 2.0)
_FONT_LABEL = r"C:\Windows\Fonts\impact.ttf"


def buat_stiker(sumber, label, format_video, nomor, folder):
    """Foto jadi stiker seperti di video berita/konspirasi YouTube: bingkai putih bersudut bulat, bayangan, sedikit
    miring, label kuning di pojok bawah. Disimpan sebagai urutan PNG transparan berisi animasi muncul.
    Mengembalikan (pola_png, x, y): posisi kiri-atas kanvas stiker di layar."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
    W, H = UKURAN[format_video]
    tegak = format_video == "9:16"
    # Shorts: di tengah atas (subtitle ada di ±70% tinggi layar); YouTube: di samping, kiri/kanan bergantian.
    maks_w, maks_h = (int(W * 0.72), int(H * 0.32)) if tegak else (int(W * 0.40), int(H * 0.50))
    foto = ImageOps.exif_transpose(Image.open(sumber)).convert("RGB")
    s = min(maks_w / foto.width, maks_h / foto.height)
    foto = foto.resize((max(1, round(foto.width * s)), max(1, round(foto.height * s))), Image.LANCZOS)
    tepi = max(10, round(min(W, H) * 0.014))
    kartu = Image.new("RGBA", (foto.width + 2 * tepi, foto.height + 2 * tepi), (255, 255, 255, 255))
    kartu.paste(foto, (tepi, tepi))
    bulat = Image.new("L", kartu.size, 0)
    ImageDraw.Draw(bulat).rounded_rectangle((0, 0, kartu.width - 1, kartu.height - 1), radius=tepi, fill=255)
    kartu.putalpha(bulat)
    label = " ".join((label or "").split()).upper()
    if label:
        ukuran = round(W * (0.045 if tegak else 0.024))
        lebar_maks = kartu.width - 3 * tepi
        while True:  # kecilkan huruf sampai label muat di lebar foto
            font = ImageFont.truetype(_FONT_LABEL, ukuran)
            lebar_teks = ImageDraw.Draw(kartu).textlength(label, font=font)
            if lebar_teks + ukuran <= lebar_maks or ukuran <= 22:
                break
            ukuran -= 2
        kotak = font.getbbox(label)
        pad = round(ukuran * 0.35)
        tag = Image.new("RGBA", (int(lebar_teks) + 2 * pad, kotak[3] - kotak[1] + 2 * pad), (245, 197, 24, 255))
        ImageDraw.Draw(tag).text((pad - kotak[0], pad - kotak[1]), label, font=font, fill=(10, 10, 10, 255))
        gabung = Image.new("RGBA", (kartu.width, kartu.height + tag.height // 2), (0, 0, 0, 0))
        gabung.alpha_composite(kartu, (0, 0))
        gabung.alpha_composite(tag, (2 * tepi, kartu.height - tag.height // 2))
        kartu = gabung
    kartu = kartu.rotate(_SUDUT_STIKER[nomor % len(_SUDUT_STIKER)], resample=Image.BICUBIC, expand=True)
    geser = (round(W * 0.008), round(W * 0.012))
    ruang = round(W * 0.03)
    penuh = Image.new("RGBA", (kartu.width + 2 * ruang + geser[0], kartu.height + 2 * ruang + geser[1]), (0, 0, 0, 0))
    bayang = Image.new("RGBA", kartu.size, (0, 0, 0, 255))
    bayang.putalpha(kartu.getchannel("A").point(lambda a: int(a * 0.55)))
    penuh.alpha_composite(bayang, (ruang + geser[0], ruang + geser[1]))
    penuh = penuh.filter(ImageFilter.GaussianBlur(round(W * 0.012)))
    penuh.alpha_composite(kartu, (ruang, ruang))

    besar = max(_POP_STIKER)
    cw, ch = int(penuh.width * besar) + 2, int(penuh.height * besar) + 2
    folder = Path(folder)
    for i, skala in enumerate(_POP_STIKER):
        bingkai = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        kecil = penuh.resize((max(1, round(penuh.width * skala)), max(1, round(penuh.height * skala))), Image.LANCZOS)
        if skala < 0.9:  # dua frame pertama sedikit transparan supaya munculnya tidak kasar
            kecil.putalpha(kecil.getchannel("A").point(lambda a, f=0.55 + 0.45 * skala: int(a * f)))
        bingkai.alpha_composite(kecil, ((cw - kecil.width) // 2, (ch - kecil.height) // 2))
        bingkai.save(folder / f"stiker-{nomor:04d}-{i:02d}.png")
    if tegak:
        cx, cy = W / 2, H * 0.37
    else:
        cx, cy = (W * 0.70 if nomor % 2 == 0 else W * 0.30), H * 0.44
    x = int(min(max(0, cx - cw / 2), max(0, W - cw)))
    y = int(min(max(H * 0.05, cy - ch / 2), max(0, H * (0.74 if tegak else 0.86) - ch)))
    return str(folder / f"stiker-{nomor:04d}-%02d.png"), x, y


_POP_MASKOT = (0.35, 0.7, 1.0, 1.12, 1.06, 0.98, 1.0)


def urutan_maskot(png, format_video, folder):
    """Maskot (PNG sudah bergaris tepi putih) sebagai urutan PNG animasi muncul "memantul", di pojok kiri bawah:
    Shorts di atas area judul/caption aplikasi, YouTube di bawah stiker kiri. Mengembalikan
    (pola_png, jumlah_frame, x, y). Di-cache per pose & format."""
    from PIL import Image
    W, H = UKURAN[format_video]
    tegak = format_video == "9:16"
    tinggi = int(H * (0.17 if tegak else 0.27))
    asli = Image.open(png).convert("RGBA")
    asli = asli.resize((max(1, round(asli.width * tinggi / asli.height)), tinggi), Image.LANCZOS)
    besar = max(_POP_MASKOT)
    cw, ch = int(asli.width * besar) + 2, int(asli.height * besar) + 2
    awalan = f"maskot-{Path(png).stem}-{format_video.replace(':', 'x')}"
    folder = Path(folder)
    if not (folder / f"{awalan}-{len(_POP_MASKOT) - 1:02d}.png").exists():
        for i, skala in enumerate(_POP_MASKOT):
            bingkai = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            kecil = asli.resize((max(1, round(asli.width * skala)), max(1, round(asli.height * skala))), Image.LANCZOS)
            # memantul dari bawah: titik tumpu di tengah bawah
            bingkai.alpha_composite(kecil, ((cw - kecil.width) // 2, ch - kecil.height))
            bingkai.save(folder / f"{awalan}-{i:02d}.png")
    x = int(W * (0.03 if tegak else 0.015))
    y = int(H * (0.87 if tegak else 0.975)) - ch
    return str(folder / f"{awalan}-%02d.png"), len(_POP_MASKOT), x, y


def buat_shot(bahan, frames, format_video, gaya, isi_layar, nomor, tujuan, batal=None, transisi=False, gerak=None,
              stiker=None, maskot=None):
    """Satu shot berdurasi tepat `frames` frame, tanpa audio. transisi=True: shot pertama sebuah adegan.
    stiker = {"file", "label", "tunda"}: foto yang ditempel di atas footage (tata visual "video + stiker"), muncul
    setelah `tunda` detik lalu mengambang pelan. maskot = {"file", "tunda", "durasi"}: maskot channel muncul di pojok
    kiri bawah, bergoyang, lalu memudar."""
    W, H = UKURAN[format_video]
    # tpad menggandakan frame terakhir sebagai cadangan; -frames:v lalu memotong TEPAT `frames` frame.
    # Tanpa ini zoompan+fps kadang kurang 1 frame per shot, dan gambar makin maju dari narasi.
    akhir = f",fps={FPS},setsar=1,format=yuv420p" + _grade(gaya) + "[g]"
    sw, sh = bahan.get("lebar") or W, bahan.get("tinggi") or H
    if bahan.get("tutup_bawah"):
        sh = int(sh * 0.78)
    beda_rasio = max(sw / sh, (W / H)) / min(sw / sh, (W / H))
    blur = isi_layar == "blur" and beda_rasio > 1.25

    if bahan["jenis"] == "video":
        masuk = ["-ss", f"{bahan.get('mulai', 0):.2f}", "-stream_loop", "-1", "-i", bahan["file"]]
        if blur:
            vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:2[bg];"
                  f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
        else:
            # Tanpa zoom tambahan: zoom per frame dibulatkan ke kelipatan 2 piksel dan membuat gambar bergetar.
            vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    else:
        # Ken Burns: gambar diperbesar 2x lalu zoompan, efek bergantian per shot.
        masuk = ["-i", bahan["file"]]
        W2, H2 = W * 2, H * 2
        z, x, y = (e.format(n=frames) for e in _GERAK.get(gerak) or _GERAK[_GILIRAN_GERAK[nomor % len(_GILIRAN_GERAK)]])
        if transisi == "zoom":  # zoom tembus: mulai 40% lebih dekat lalu cepat mundur ke gerak biasa
            z = f"({z})*(1+0.4*max(0,1-on/9))"
        if blur:
            dasar = (f"split[a][b];[a]scale={W2}:{H2}:force_original_aspect_ratio=increase,crop={W2}:{H2},boxblur=40:2[bg];"
                     f"[b]scale={W2}:{H2}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,")
        else:
            dasar = f"scale={W2}:{H2}:force_original_aspect_ratio=increase,crop={W2}:{H2},"
        vf = (f"{dasar}zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS}")
    masuk, efek_akhir = _efek_misterius(gaya, format_video, nomor, transisi, masuk)
    if stiker:
        # Ditempel SETELAH grade & kabut: stikernya tetap tajam dan berwarna seperti tempelan editor.
        pola, sx, sy = buat_stiker(stiker["file"], stiker.get("label", ""), format_video, nomor, Path(tujuan).parent)
        idx = masuk.count("-i")
        masuk = [*masuk, "-framerate", str(FPS), "-start_number", "0", "-i", pola]
        efek_akhir += (f"[e];[{idx}:v]format=rgba,setpts=PTS+{stiker.get('tunda', 0.12):.3f}/TB[s];"
                       f"[e][s]overlay=x={sx}:y='{sy}+{round(H * 0.004)}*sin(t*2.3)':eof_action=repeat")
    if maskot:
        pola, n, mx, my = urutan_maskot(maskot["file"], format_video, Path(tujuan).parent)
        idx = masuk.count("-i")
        masuk = [*masuk, "-framerate", str(FPS), "-start_number", "0", "-i", pola]
        t0, t1 = maskot["tunda"], maskot["tunda"] + maskot["durasi"]
        # frame terakhir diulang sebagai frame sungguhan (loop) supaya fade keluar bisa bekerja
        efek_akhir += (f"[e2];[{idx}:v]format=rgba,loop=loop=-1:size=1:start={n - 1},"
                       f"setpts=N/{FPS}/TB+{t0:.3f}/TB,fade=t=out:st={t1 - 0.25:.3f}:d=0.25:alpha=1[m];"
                       f"[e2][m]overlay=x={mx}:y='{my}+{round(H * 0.003)}*sin(t*3.1)':"
                       f"enable='between(t,{t0:.3f},{t1:.3f})'")
    # Subtitle/teks tertanam di bagian bawah video sumber: 22% bawah dibuang (sedikit zoom). Dulu dipakai delogo,
    # hasilnya coretan garis vertikal yang jelek.
    tutup = "crop=iw:trunc(ih*0.78/2)*2:0:0," if bahan.get("tutup_bawah") else ""
    fc = f"[0:v]{tutup}{_terangkan(bahan)}{vf}{akhir}{efek_akhir},tpad=stop_mode=clone:stop=15[o]"
    ffmpeg([*masuk, "-filter_complex", fc, "-map", "[o]", "-frames:v", str(frames), "-r", str(FPS),
            *_arg_encode(), "-an", str(tujuan)], batal=batal, timeout=900)
    return tujuan


def buat_shot_banding(kiri, kanan, label_kiri, label_kanan, frames, format_video, gaya, nomor, tujuan, batal=None,
                      transisi=False, sama=False):
    """Perbandingan 🆚: dua foto berdampingan (Shorts: atas-bawah, YouTube: kiri-kanan), masing-masing zoom pelan,
    garis pemisah kuning, label di tiap foto, dan tulisan "MIRIP?" di tengah."""
    W, H = UKURAN[format_video]
    tegak = format_video == "9:16"
    pw, ph = (W, H // 2) if tegak else (W // 2, H)
    tujuan = Path(tujuan)
    folder = tujuan.parent
    for nama, teks in (("kiri", label_kiri), ("kanan", label_kanan), ("tengah", "MIRIP?")):
        (folder / f"{tujuan.stem}.{nama}.txt").write_text(teks or " ", encoding="utf-8")
    font = "C\\:/Windows/Fonts/impact.ttf"

    def panel(i, z0, z1):
        return (f"[{i}:v]scale={pw * 2}:{ph * 2}:force_original_aspect_ratio=increase,crop={pw * 2}:{ph * 2},"
                f"zoompan=z='{z0}+({z1}-{z0})*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={frames}:s={pw}x{ph}:fps={FPS},setsar=1[p{i}];")

    garis = (f"drawbox=x=0:y={ph - 5}:w={W}:h=10:color=0xF5C518@0.95:t=fill" if tegak else
             f"drawbox=x={pw - 5}:y=0:w=10:h={H}:color=0xF5C518@0.95:t=fill")
    ukuran = 62 if tegak else 54
    xk, yk = (40, ph + 75) if tegak else (pw + 40, 40)  # di bawah tulisan "MIRIP?" yang ada di tengah
    label = (f"drawtext=fontfile='{font}':textfile='{tujuan.stem}.kiri.txt':fontsize={ukuran}:fontcolor=white:"
             f"box=1:boxcolor=black@0.65:boxborderw=14:x=40:y=40,"
             f"drawtext=fontfile='{font}':textfile='{tujuan.stem}.kanan.txt':fontsize={ukuran}:fontcolor=white:"
             f"box=1:boxcolor=black@0.65:boxborderw=14:x={xk}:y={yk},"
             f"drawtext=fontfile='{font}':textfile='{tujuan.stem}.tengah.txt':fontsize={int(ukuran * 1.6)}:"
             f"fontcolor=0xF5C518:borderw=8:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:enable='gte(t,0.5)'")
    tumpuk = "vstack" if tegak else "hstack"
    masuk = ["-i", str(Path(kiri["file"]).resolve()), "-i", str(Path(kanan["file"]).resolve())]
    masuk, efek_akhir = _efek_misterius(gaya, format_video, nomor, transisi, masuk)
    # sama=True ("satu foto, dua dunia"): zoom kedua panel identik supaya daratannya sejajar, dan tanpa grade gelap
    # supaya beda warna Bulan (abu-abu) vs Bumi (berwarna) tetap terasa
    zoom = ((1.0, 1.06), (1.0, 1.06)) if sama else ((1.0, 1.08), (1.08, 1.0))
    fc = (panel(0, *zoom[0]) + panel(1, *zoom[1]) +
          f"[p0][p1]{tumpuk}=inputs=2,fps={FPS},format=yuv420p" + ("" if sama else _grade(gaya)) + f",{garis},{label}[g]" +
          efek_akhir + ",tpad=stop_mode=clone:stop=15[o]")
    ffmpeg([*masuk, "-filter_complex", fc, "-map", "[o]", "-frames:v", str(frames), "-r", str(FPS),
            *_arg_encode(), "-an", tujuan.name], batal=batal, timeout=900, cwd=str(folder))
    return tujuan


def shot_kosong(frames, format_video, tujuan, batal=None, gaya="misterius"):
    """Cadangan kalau footage gagal / kartu disclaimer: latar gelap berkabut."""
    W, H = UKURAN[format_video]
    masuk, efek_akhir = _efek_misterius(gaya, format_video, 7, False,
                                        ["-f", "lavfi", "-i", f"color=c=0x0b0b10:s={W}x{H}:r={FPS}"])
    fc = f"[0:v]noise=alls=18:allf=t+u,vignette=PI/3,format=yuv420p[g]{efek_akhir},format=yuv420p[o]"
    ffmpeg([*masuk, "-filter_complex", fc, "-map", "[o]", "-frames:v", str(frames), *_arg_encode(),
            str(tujuan)], batal=batal, timeout=300)
    return tujuan


# ---------------------------------------------------------------- subtitle

def _ass_waktu(t):
    t = max(0.0, t)
    j = int(t // 3600)
    m = int(t % 3600 // 60)
    d = t % 60
    return f"{j}:{m:02d}:{d:05.2f}"


def _teks_ass(t):
    return re.sub(r"[{}\\]", "", t or "").replace("\n", " ").strip()


def tulis_subtitle(path, adegan, format_video, disclaimer=None, geser_kata=GESER_KATA, hook="", gaya_visual="misterius",
                   layar=()):
    """Subtitle .ass: beberapa kata per tampilan, kata yang sedang diucapkan berwarna kuning.

    disclaimer: {"awal": teks | "", "akhir": (mulai, durasi, teks) | None} — teks di awal tampil di bagian atas
    dalam kotak gelap; kartu akhir tampil di tengah layar selama narator membacakannya.
    layar: [{"teks", "t0", "t1", "atas"}] — angka/istilah kunci yang tampil BESAR (gaya video sains: "30 JUTA
    TAHUN"), di tengah layar, atau di atas kalau shot itu sedang menampilkan stiker.
    """
    W, H = UKURAN[format_video]
    pendek = format_video == "9:16"
    maks_kata, maks_huruf = (3, 18) if pendek else (7, 40)
    cerah = gaya_visual == "cerah"
    gaya = [
        f"Style: Default,Arial Black,{78 if pendek else 62},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,"
        f"0,0,0,0,100,100,0,0,1,{6 if pendek else 4},2,2,60,60,{560 if pendek else 70},1",
        # BorderStyle 3 = kotak; warna kotak dari OutlineColour (libass) — keduanya diisi hitam transparan.
        f"Style: Disclaimer,Arial,{34 if pendek else 30},&H00FFFFFF,&H00FFFFFF,&H70000000,&H70000000,"
        f"-1,0,0,0,100,100,0,0,3,14,0,8,{90 if pendek else 360},{90 if pendek else 360},{170 if pendek else 50},1",
        f"Style: Kartu,Arial,{54 if pendek else 50},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,3,0,5,{100 if pendek else 260},{100 if pendek else 260},0,1",
        # Judul hook di detik-detik pertama: besar, garis tepi tebal; misterius = putih dengan bayangan merah gelap,
        # cerah = kuning dengan bayangan hitam (seperti channel sains).
        f"Style: Hook,Impact,{118 if pendek else 104},{'&H0018C5F5' if cerah else '&H00FFFFFF'},&H00FFFFFF,&H00000000,"
        f"{'&H64000000' if cerah else '&H00101060'},0,0,0,0,100,100,2,0,1,8,6,8,70,70,{int(H * 0.2)},1",
        # Angka/istilah kunci yang tampil besar (gaya cerah).
        f"Style: Layar,Impact,{116 if pendek else 104},&H0018C5F5,&H00FFFFFF,&H00000000,&H78000000,"
        f"0,0,0,0,100,100,1,0,1,8,6,5,60,60,0,1",
    ]
    baris = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
             "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
             "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
             "MarginL, MarginR, MarginV, Encoding", *gaya, "", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    disclaimer = disclaimer or {}
    for i, l in enumerate(layar):  # muncul "meletup", sedikit miring bergantian, lalu memudar
        y = int(H * (0.14 if l.get("atas") else 0.42))
        baris.append(f"Dialogue: 3,{_ass_waktu(l['t0'])},{_ass_waktu(l['t1'])},Layar,,0,0,0,,"
                     f"{{\\an5\\pos({W // 2},{y})\\frz{-3 if i % 2 else 3}\\fad(90,250)\\fscx135\\fscy135"
                     f"\\t(0,220,\\fscx100\\fscy100)}}{_teks_ass(l['teks']).upper()}")
    if hook:  # muncul membesar lalu mengecil ke ukuran normal, lalu memudar
        baris.append(f"Dialogue: 2,{_ass_waktu(0.0)},{_ass_waktu(2.9)},Hook,,0,0,0,,"
                     "{\\fad(120,450)\\fscx135\\fscy135\\t(0,260,\\fscx100\\fscy100)}"
                     f"{_teks_ass(hook).upper()}")
    if disclaimer.get("awal"):
        mulai_d = 3.0 if hook else 0.3  # jangan bertumpuk dengan judul hook
        baris.append(f"Dialogue: 1,{_ass_waktu(mulai_d)},{_ass_waktu(mulai_d + 5)},Disclaimer,,0,0,0,,"
                     f"{{\\fad(300,500)}}⚠ {_teks_ass(disclaimer['awal'])}")
    if disclaimer.get("akhir"):
        mulai, durasi, teks = disclaimer["akhir"]
        baris.append(f"Dialogue: 1,{_ass_waktu(mulai + 0.1)},{_ass_waktu(mulai + durasi)},Kartu,,0,0,0,,"
                     f"{{\\fad(400,400)}}{{\\c&H0000E5FF&\\fs{80 if pendek else 70}}}DISCLAIMER{{\\r}}\\N\\N"
                     f"{_teks_ass(teks)}")
    for a in adegan:
        # Edge TTS menandai awal kata ±0,12 detik sebelum suaranya terdengar (diukur dengan silencedetect);
        # akhir katanya sudah pas. Geser awal kata supaya highlight tidak mendahului suara.
        kata = [{**k, "t0": min(k["t0"] + geser_kata, k["t1"] - 0.03) + a["mulai"], "t1": k["t1"] + a["mulai"],
                 "teks": re.sub(r"[{}\\]", "", k["teks"]).strip()} for k in a["kata"]]
        kata = [k for k in kata if k["teks"]]
        grup, sekarang = [], []
        for i, k in enumerate(kata):
            jeda = sekarang and k["t0"] - sekarang[-1]["t1"] > 0.3
            panjang = len(" ".join(x["teks"] for x in sekarang + [k]))
            if sekarang and (len(sekarang) >= maks_kata or panjang > maks_huruf or jeda):
                grup.append(sekarang)
                sekarang = []
            sekarang.append(k)
        if sekarang:
            grup.append(sekarang)
        batas_adegan = a["mulai"] + a["durasi"]
        for gi, g in enumerate(grup):
            # Tahan teks sampai kelompok berikutnya muncul (jeda pendek tidak bikin subtitle berkedip).
            berikut = grup[gi + 1][0]["t0"] if gi + 1 < len(grup) else batas_adegan
            selesai_grup = berikut if berikut - g[-1]["t1"] <= 0.6 else g[-1]["t1"] + 0.3
            for wi, k in enumerate(g):
                mulai = k["t0"]
                selesai = g[wi + 1]["t0"] if wi + 1 < len(g) else selesai_grup
                if selesai - mulai < 0.04:
                    continue
                isi = []
                for wj, x in enumerate(g):
                    t = x["teks"].upper() if pendek else x["teks"]
                    # kata yang sedang diucapkan: kuning dan "meletup" sesaat
                    isi.append("{\\c&H0000E5FF&\\fscx118\\fscy118\\t(0,90,\\fscx100\\fscy100)}" + t +
                               "{\\c&H00FFFFFF&\\fscx100\\fscy100}" if wj == wi else t)
                baris.append(f"Dialogue: 0,{_ass_waktu(mulai)},{_ass_waktu(selesai)},Default,,0,0,0,,{' '.join(isi)}")
    Path(path).write_text("\n".join(baris) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- gabung akhir

def pilih_musik():
    daftar = [p for p in MUSIK.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg", ".flac")]
    return random.choice(daftar) if daftar else None


def dengung_misterius():
    """Musik latar cadangan buatan sendiri (bebas hak cipta): dengung rendah + desis, untuk saat folder musik kosong."""
    tujuan = CACHE / "dengung-misterius.m4a"
    if tujuan.exists():
        return tujuan
    d = 180
    ffmpeg(["-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude=0.5:d={d}",
            "-f", "lavfi", "-i", f"sine=f=55:d={d}", "-f", "lavfi", "-i", f"sine=f=82.41:d={d}",
            "-f", "lavfi", "-i", f"sine=f=110.3:d={d}",
            "-filter_complex",
            "[0]lowpass=f=280,volume=0.6[n];[1]volume=0.5,tremolo=f=0.1:d=0.6[a];"
            "[2]volume=0.35,tremolo=f=0.13:d=0.7[b];[3]volume=0.15,tremolo=f=0.17:d=0.8[c];"
            "[n][a][b][c]amix=inputs=4:normalize=0,aecho=0.8:0.7:600|1100:0.35|0.25,lowpass=f=1200,"
            f"afade=t=in:d=2,afade=t=out:st={d - 2}:d=2,loudnorm=I=-20,aformat=channel_layouts=stereo",
            "-c:a", "aac", "-b:a", "128k", str(tujuan)], timeout=300)
    return tujuan


def gabung(kerja, shots, adegan, total, format_video, subtitle, musik, volume_musik, tujuan, batal=None,
           disclaimer=None, suara=None, geser_kata=GESER_KATA, hook="", sfx=None, gaya_visual="misterius", layar=(),
           logo=None):
    """kerja: folder proyek (cwd ffmpeg supaya path subtitle tidak perlu di-escape).
    adegan = data subtitle per adegan; suara = potongan audio [{mp3, durasi}] (bawaan: mp3 per adegan).
    layar = tulisan besar per adegan (lihat tulis_subtitle); logo = PNG logo channel di pojok kanan atas."""
    kerja = Path(kerja)
    # Daftar shot langsung jadi input encode akhir (didekode, bukan disalin) supaya tidak ada frame yang hilang.
    daftar = kerja / "shots.txt"
    daftar.write_text("".join(f"file '{Path(s).as_posix()}'\n" for s in shots), encoding="utf-8")
    (kerja / "gambar.mp4").unlink(missing_ok=True)  # sisa versi lama

    # Narasi: tiap adegan dipad tepat sepanjang durasinya (wav terpisah), lalu disambung lewat daftar.
    # Satu perintah dengan ratusan input bisa melewati batas panjang command line Windows (video 20 menit).
    folder_suara = kerja / "suara"
    folder_suara.mkdir(exist_ok=True)
    potongan = []
    for i, a in enumerate(suara or adegan):
        wav = folder_suara / f"{i:04d}.wav"
        ffmpeg(["-i", a["mp3"], "-af", f"apad=whole_dur={a['durasi']:.3f},atrim=0:{a['durasi']:.3f}",
                "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], batal=batal, timeout=120)
        potongan.append(wav)
    (kerja / "suara.txt").write_text("".join(f"file '{w.as_posix()}'\n" for w in potongan), encoding="utf-8")
    ffmpeg(["-f", "concat", "-safe", "0", "-i", str(kerja / "suara.txt"), "-c", "copy", str(kerja / "narasi.wav")],
           batal=batal, timeout=600)

    # 1) Audio dicampur TERPISAH ke satu file. Kalau gambar (gabungan shot) dan pencampuran beberapa sumber
    #    audio diproses dalam SATU perintah ffmpeg, ada potongan audio ±3 detik yang terbuang (terbukti di video
    #    bulan: "NASA memang sering melakukan simulasi…" tidak terdengar) — penonton mendengar narasi melompat.
    args = ["-i", "narasi.wav"]
    lapisan = []  # jalur audio tambahan yang dicampur dengan narasi
    if musik:
        args += ["-stream_loop", "-1", "-i", str(musik)]
        af = (f"[0:a]aformat=channel_layouts=stereo,asplit=2[nar][sc];"
              f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={volume_musik / 100:.2f},"
              f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(0, total - 2.5):.2f}:d=2.5[m];"
              f"[m][sc]sidechaincompress=threshold=0.03:ratio=5:attack=30:release=500[md];")
        lapisan.append("[md]")
    else:
        af = "[0:a]aformat=channel_layouts=stereo[nar];"
    if sfx:  # whoosh/dentuman: tidak ikut diredam supaya tetap terasa di pergantian adegan
        idx = 1 + (1 if musik else 0)
        args += ["-i", str(sfx)]
        af += f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.8[fx];"
        lapisan.append("[fx]")
    af += (f"[nar]{''.join(lapisan)}amix=inputs={1 + len(lapisan)}:duration=first:normalize=0,"
           "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    ffmpeg([*args, "-filter_complex", af, "-map", "[a]", "-t", f"{total:.3f}", "-c:a", "pcm_s16le",
            "campuran.wav"], batal=batal, timeout=1800, cwd=str(kerja))

    # 2) Gambar + subtitle, lalu audio yang sudah jadi disalin apa adanya (encode AAC saja).
    pakai_ass = subtitle or bool(hook) or bool(layar) or \
        bool(disclaimer and (disclaimer.get("awal") or disclaimer.get("akhir")))
    pudar = f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, total - 0.7):.2f}:d=0.7"
    if pakai_ass:
        tulis_subtitle(kerja / "subtitle.ass", adegan if subtitle else [], format_video, disclaimer, geser_kata,
                       hook, gaya_visual, layar)
    masuk = ["-f", "concat", "-safe", "0", "-i", "shots.txt", "-i", "campuran.wav"]
    if logo:
        # logo channel kecil di pojok kanan atas (Shorts: sedikit turun, di bawah ikon cari/kamera aplikasi)
        W, H = UKURAN[format_video]
        tegak = format_video == "9:16"
        lebar, tepi = int(W * (0.13 if tegak else 0.07)), int(W * (0.035 if tegak else 0.02))
        masuk += ["-loop", "1", "-i", str(logo)]
        peta = ["-filter_complex",
                f"[0:v]{'ass=subtitle.ass,' if pakai_ass else ''}null[a];[2:v]scale={lebar}:-1,format=rgba,"
                f"colorchannelmixer=aa=0.92[l];[a][l]overlay=W-w-{tepi}:{int(H * 0.065) if tegak else tepi}:"
                f"shortest=1,{pudar}[v]", "-map", "[v]", "-map", "1:a"]
    else:
        peta = ["-map", "0:v", "-map", "1:a", "-vf", ("ass=subtitle.ass," if pakai_ass else "") + pudar]
    ffmpeg([*masuk, *peta, "-t", f"{total:.3f}", *_arg_encode(kualitas_tinggi=False), "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
            str(Path(tujuan).resolve())], batal=batal, timeout=3600, cwd=str(kerja))
    return tujuan


def audio_utuh(path):
    """True kalau stream audio video tidak punya paket "melar" (loncatan waktu = bagian audio terlewat)."""
    try:
        out = jalankan([FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=duration_time",
                        "-of", "csv=p=0", str(path)], timeout=120)
    except RuntimeError:
        return True
    durasi = [float(x.strip(", ")) for x in out.split() if x.strip(", ")]
    return not any(d > 0.05 for d in durasi)


def durasi_video(path):
    """Durasi stream gambar saja (bukan audio) untuk cek sinkron."""
    try:
        out = jalankan([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                        "-of", "default=nw=1:nk=1", str(path)], timeout=60)
        return float(out.strip() or 0)
    except (RuntimeError, ValueError):
        return 0.0


def kecerahan(path, detik=0.0):
    """Rata-rata kecerahan 0-255 satu frame (untuk menghindari thumbnail yang hampir hitam)."""
    try:
        # "-ss 0" sebelum -i membuat gambar diam tidak menghasilkan frame sama sekali (kecerahan terbaca 0)
        lompat = ["-ss", f"{detik:.2f}"] if detik > 0 else []
        out = jalankan([FFMPEG, "-hide_banner", *lompat, "-i", str(path), "-frames:v", "1", "-vf",
                        "scale=160:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"],
                       timeout=60)
        nilai = re.findall(r"YAVG=([\d.]+)", out)
        return float(nilai[0]) if nilai else 0.0
    except RuntimeError:
        return 0.0


def thumbnail(kerja, gambar, teks, format_video, tujuan):
    """Thumbnail dari satu frame/gambar + teks besar (untuk YouTube)."""
    W, H = UKURAN[format_video]
    kerja = Path(kerja)
    (kerja / "teks_thumb.txt").write_text(teks or "", encoding="utf-8")
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},eq=contrast=1.15:saturation=0.85:"
          f"brightness=-0.06,vignette=PI/4")
    if teks:
        # Shorts: teks di sepertiga atas (bagian bawah tertutup tombol aplikasi).
        ukuran, y = (150, f"h-text_h-{int(H * 0.08)}") if format_video == "16:9" else (120, str(int(H * 0.2)))
        vf += (f",drawtext=fontfile='C\\:/Windows/Fonts/impact.ttf':textfile=teks_thumb.txt:fontsize={ukuran}:"
               f"fontcolor=yellow:borderw=10:bordercolor=black:x=(w-text_w)/2:y={y}")
    ffmpeg(["-i", str(gambar), "-frames:v", "1", "-vf", vf, "-q:v", "2", str(Path(tujuan).resolve())],
           timeout=120, cwd=str(kerja))
    return tujuan
