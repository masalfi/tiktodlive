# TikTok Live Controller

Penonton TikTok LIVE mengontrol HP Android host lewat gift dan komentar.
Contoh: gift **Rose** → layar HP di-tap, komentar `!home` → tombol Home ditekan,
gift besar → HP reboot (dengan konfirmasi).

Berjalan di **macOS** dan **Windows**. Python + PySide6 + ADB.

---

## Cara Kerja

```
TikTok LIVE  ──►  Rule Engine  ──►  Antrian Aksi  ──►  ADB / PC / Overlay
 (gift,           (kondisi +         (serial +          (HP Android,
  komentar)        cooldown)          kill switch)       SFX, OBS)
```

Koneksi TikTok memakai [TikTokLive](https://pypi.org/project/TikTokLive/) —
port Python dari protokol yang sama dengan `tiktok-live-connector` (Node.js).

---

## Setup

### 1. Prasyarat

**Python 3.10 atau lebih baru** (`python --version`).

**ADB** — **tidak perlu diinstall terpisah.** scrcpy membawa adb-nya sendiri,
jadi begitu kamu klik **Unduh scrcpy** di tab scrcpy, adb ikut tersedia.

Urutan pencarian adb:

1. `adb.path` di `config/settings.yaml` (kalau diisi manual)
2. **adb bawaan scrcpy** di `vendor/` ← dipakai secara default
3. `adb` di PATH sistem
4. Lokasi Android SDK umum

Bawaan scrcpy didahulukan supaya versinya selalu cocok dengan scrcpy yang
dipakai — ini juga yang membuat aplikasi langsung jalan di Windows tanpa
memasang Android platform-tools.

**scrcpy** — **tidak perlu diinstall manual.** Buka tab **scrcpy** di
aplikasi, klik **Unduh scrcpy** sekali, dan binary resmi untuk OS-mu
(macOS/Windows/Linux, otomatis terdeteksi) diunduh ke folder `vendor/`
beserta verifikasi SHA256. Kalau kamu sudah punya scrcpy di sistem, itu
yang dipakai.

### 2. Jalankan

```bash
python run.py
```

Itu saja. Saat pertama dijalankan, `run.py` otomatis membuat lingkungan
virtual (`.venv`) dan memasang semua paket yang dibutuhkan, lalu membuka
aplikasi. Tidak perlu mengetik perintah lain atau mengaktifkan venv.

> Di Windows pakai `python run.py`; di macOS/Linux bisa `python3 run.py`.

### 3. Siapkan HP Android

1. Aktifkan **Opsi Pengembang**: Settings → About phone → ketuk *Build number* 7x.
2. Nyalakan **USB debugging**.
3. Colok USB, lalu **Allow** saat muncul dialog di HP.
4. Cek terbaca: `adb devices` → harus muncul serial dengan status `device`.

Mau tanpa kabel? `adb tcpip 5555` lalu `adb connect <IP-HP>:5555`.

---

## Pemakaian

### Tab Mulai

Tab pertama yang kamu lihat: daftar langkah persiapan dengan status
masing-masing, dan tombol **Buka** yang langsung melompat ke tab terkait.

| | Langkah |
|---|---|
| 1 | Sambungkan HP Android |
| 2 | Siapkan scrcpy (opsional) |
| 3 | Isi akun TikTok |
| 4 | Buat aturan gift |
| 5 | Pasang overlay di OBS (opsional) |
| 6 | Kalibrasi tombol game (opsional) |

Di atasnya ada ringkasan: **Siap dipakai** kalau semua langkah wajib
beres, atau daftar apa yang masih kurang.

### Tab Koneksi
Isi nama akun TikTok → **Connect**. Kamu boleh menempel link profilnya langsung (`https://tiktok.com/@nama/live`) — aplikasi merapikannya sendiri. Status berubah **LIVE** kalau
akun sedang siaran. Akun harus benar-benar sedang live.

*Sign API key* opsional — hanya untuk menaikkan rate limit server signature
(EulerStream) kalau sering kena limit.

### Tab Rules
Satu rule = **event + kondisi → rangkaian aksi**.

| Event | Kondisi yang tersedia |
|---|---|
| Gift | nama gift (persis/mengandung), gift ID, min/maks total koin, min jumlah kirim |
| Komentar | mengandung, sama persis, diawali, regex, peka huruf besar/kecil |
| Like | minimal jumlah like |
| Follow / Share / Join | — (selalu cocok) |

Semua event juga bisa dibatasi **hanya dari user tertentu**.

**Test Run** menjalankan rule memakai event contoh — bisa dites tanpa menunggu
gift asli.

### Nama gift — otomatis, tidak perlu diketik manual

Daftar gift diambil **langsung dari API TikTok** (±680 gift), jadi tidak perlu
menghafal atau mengetik namanya:

- Di **editor rule**, kolom *Nama gift* adalah dropdown yang bisa dicari.
  Tiap entri menampilkan harga koin dan tanda *(streak)*, mis.
  `Rose - 1 koin (streak)`. Yang disimpan hanya nama gift-nya.
- Tab **Gift** menampilkan seluruh katalog dengan **ikon asli** tiap gift,
  harga koin, status streak, dan ID-nya. Ada kotak cari di atasnya.
- Tombol **Segarkan** mengambil daftar terbaru dari TikTok.

Daftar disimpan ke `config/gifts.json`, jadi tetap tersedia walau sedang
offline, dan disegarkan otomatis kalau umurnya sudah lewat 7 hari.

Saat kamu **terhubung ke sebuah live**, gift khusus room itu (mis. gift
musiman atau eksklusif) otomatis ditambahkan ke katalog.

Gift yang belum ada di daftar tetap bisa diketik manual di dropdown yang sama.

> Beberapa gift punya nama sama dengan ID berbeda. Karena rule mencocokkan
> berdasarkan nama, katalog menyimpan satu entri per nama — yang termurah,
> karena itu yang paling sering dikirim penonton.

### Placeholder
Dipakai di parameter teks (mis. judul overlay):

`{user}` `{username}` `{gift}` `{count}` `{coins}` `{comment}` `{likes}`

### Tab Devices
Daftar device ADB + panel tes aksi manual. Pilih baris untuk mengganti device
target.

### Tab scrcpy
Kontrol penuh scrcpy tanpa terminal. Semua pengaturan langsung terlihat
sebagai perintah di bagian bawah, jadi kamu tahu persis apa yang dijalankan.

| Sub-tab | Isi |
|---|---|
| **Tampilan** | Resolusi maks, FPS, bitrate, codec, rotasi, crop |
| **Jendela** | Judul, selalu di atas, layar penuh, tanpa bingkai, ukuran & posisi |
| **Device** | Matikan layar HP, cegah tidur, tampilkan sentuhan, rekam ke file |
| **Wireless** | Sambungkan HP lewat WiFi tanpa kabel — cukup satu tombol |

**Cara pakai wireless:** colok HP dengan USB sekali, pastikan HP dan komputer
satu jaringan WiFi, klik **Aktifkan Wireless**. Setelah tersambung, kabel USB
boleh dicabut.

Rule juga bisa menjalankan scrcpy lewat aksi **Jalankan scrcpy** / **Hentikan
scrcpy**, memakai pengaturan yang sama dengan tab ini.

### Kalau HP reboot

scrcpy hanya untuk **melihat layar** (mirroring). Semua aksi — tap, swipe,
tombol, reboot — tetap lewat **adb**, tidak lewat scrcpy.

Karena itu, saat sebuah rule me-reboot HP, aplikasi menangani sendiri:

| Tahap | Yang terjadi |
|---|---|
| HP mulai reboot | Device hilang dari adb; status bar jadi **Device offline** |
| Selama offline | Aksi ADB **dijeda** dan antrian dikosongkan, supaya log tidak penuh error. Aksi host (overlay, suara) tetap jalan |
| HP selesai boot | Device terdeteksi lagi; aksi ADB lanjut otomatis |
| Setelah itu | Kalau scrcpy tadi sedang berjalan, **dijalankan ulang otomatis** dengan pengaturan yang sama |

Untuk device **wireless**, reboot juga memutus adb-over-TCP. Aplikasi mencoba
`adb connect` berkala sampai HP kembali (maksimal 4 menit). Kalau setelah itu
belum kembali, muncul pesan untuk mencolok kabel USB sebentar — sebagian HP
memang mematikan adb-wifi setiap kali boot.

Kalau kamu menghentikan scrcpy **sendiri** lewat tombol Hentikan, aplikasi
tidak akan menjalankannya lagi otomatis.

### Tab Game — kontrol Mobile Legends & game lain

Aksi game menekan tombol di dalam game (ultimate, recall, skill, joystick)
berdasarkan posisi yang **kamu kalibrasi sendiri**.

> **Kenapa tidak pakai koordinat dari internet?** Mobile Legends mengizinkan
> pemain memindahkan tombol lewat pengaturan HUD, dan posisinya juga berubah
> mengikuti resolusi layar. Koordinat yang benar di satu HP bisa meleset jauh
> di HP lain. Karena itu posisi disimpan sebagai **persentase layar** dan
> dikalibrasi langsung dari screenshot HP-mu.

#### Cara kalibrasi (sekali saja)

1. Buka game di HP sampai masuk pertandingan
2. Tab **Game** → **Ambil Screenshot**
3. Pilih tombol di daftar kiri (mis. `ultimate`)
4. Klik posisi tombol itu di gambar
5. Klik **Tes tekan** untuk memastikan benar — lihat HP-nya
6. Ulangi untuk tombol lain, lalu **Simpan**

Tips: nyalakan **Tampilkan sentuhan** di tab scrcpy supaya kamu bisa melihat
persis di mana tap mendarat.

> **Orientasi harus sama.** Profil yang dikalibrasi saat layar mendatar hanya
> berlaku saat layar mendatar. Tab Game menampilkan orientasi HP saat ini dan
> memberi peringatan kalau tidak cocok — kalau diabaikan, semua tap akan
> mendarat di tempat yang salah.
>
> Ini penting karena `adb shell wm size` **selalu** melaporkan ukuran fisik
> (mis. 1080x2280) walau HP sedang mendatar. Aplikasi membaca rotasi
> sebenarnya lewat `dumpsys`, bukan dari `wm size`.

#### Aksi game

| Aksi | Fungsi |
|---|---|
| **Tekan tombol game** | Tap tombol; bisa diulang (mis. spam serang 5x) |
| **Tekan & tahan** | Untuk recall atau skill yang perlu di-charge |
| **Skill terarah** | Tekan tombol lalu geser untuk membidik (skillshot) |
| **Gerakkan hero** | Geser joystick ke satu arah selama N detik |
| **Combo** | Beberapa tombol berurutan, mis. `skill1,skill2,ultimate` |

Tombol bawaan profil Mobile Legends: `attack`, `skill1`, `skill2`, `skill3`,
`ultimate`, `spell`, `recall`, `heal`, `joystick`, `shop`, `minimap`,
`upgrade1..3`. Kamu bisa menambah tombol baru langsung di
`config/game_profiles.yaml`.

Contoh rule sudah disiapkan (semua **nonaktif** sampai kamu kalibrasi):
Gift Lion → ultimate, `!recall` → pulang ke base, gift ≥1000 koin → combo
skill 1-2-ulti, `!maju` → jalan ke kanan, Gift Rose → spam serang 5x.

#### Yang perlu kamu tahu

- **Ketentuan layanan game.** Sebagian game melarang otomatisasi input dan
  bisa menindak akun. Ini HP dan akunmu sendiri — pertimbangkan risikonya,
  terutama di mode ranked.
- **Sebagian game memblokir input adb.** Kalau tap tidak bereaksi padahal
  posisinya benar, game itu menolak event yang disuntikkan. Tidak ada
  jalan keluar dari sisi aplikasi ini.
- Kalibrasi ulang kalau kamu mengubah HUD layout atau resolusi layar.

### Tab Gift
Katalog lengkap gift TikTok beserta ikonnya — cari nama gift, lihat harga koin
dan apakah gift itu bisa di-streak. Ikon diunduh sekali lalu disimpan lokal.

### Tab Log
Kolom kiri = event masuk dari TikTok. Kolom kanan = aksi yang dijalankan
beserta hasilnya.

---

## Daftar Aksi

### Di HP (ADB)
| Aksi | Keterangan |
|---|---|
| Tap layar | koordinat X, Y |
| Swipe | dari (x1,y1) ke (x2,y2) + durasi |
| Ketik teks | spasi otomatis di-escape |
| Tombol (keyevent) | Home, Back, Power, Volume, dll |
| Buka / tutup aplikasi | lewat nama package |
| Buka URL | membuka link di browser HP |
| Screenshot | disimpan ke folder `screenshots/` |
| **Reboot device** | ⚠ dibatasi maks 2×/jam |
| **WiFi / mode pesawat** | ⚠ bisa memutus adb wireless |
| Brightness | 0–255 |
| Rotasi layar | auto-rotate dimatikan otomatis |
| Volume | naik/turun, beberapa step |
| **Custom shell** | ⚠ perintah `adb shell` bebas |

### Di PC Host
| Aksi | Keterangan |
|---|---|
| Tampilkan overlay | alert di OBS |
| Mainkan suara | file dari `assets/sfx/` |
| **Jalankan script** | ⚠ program/script apa saja |
| Tekan tombol di PC | butuh izin Accessibility di macOS |
| **Suara di overlay** | efek suara lewat OBS Browser Source (bisa pilih channel) |
| **Musik latar overlay** | musik loop dengan fade in/out |
| **Efek visual overlay** | confetti, getar, kilat, teks, hujan emoji |
| Jalankan scrcpy | memakai pengaturan dari tab scrcpy |
| Hentikan scrcpy | menutup jendela scrcpy |
| Tunggu | jeda di tengah rangkaian aksi |

⚠ = aksi berbahaya. Centang **"Minta konfirmasi"** di rule agar muncul dialog
konfirmasi (auto-batal setelah 10 detik).

---

## Beberapa overlay sekaligus (channel)

Satu server melayani **banyak Browser Source**. Tiap overlay punya *channel*
sendiri, jadi gift berbeda bisa tampil di posisi dan ukuran berbeda di OBS.

| URL Browser Source | Channel |
|---|---|
| `http://127.0.0.1:8777/overlay` | `main` (utama) |
| `http://127.0.0.1:8777/overlay?ch=alert` | `alert` |
| `http://127.0.0.1:8777/overlay?ch=efek` | `efek` |
| `http://127.0.0.1:8777/overlay?ch=musik` | `musik` |

Nama channel bebas — huruf kecil, angka, `-` dan `_`. Penulisan otomatis
diseragamkan, jadi `Alert`, `ALERT`, dan `alert` menunjuk overlay yang sama.

### Contoh susunan di OBS

| Browser Source | Channel | Ukuran & posisi | Isi |
|---|---|---|---|
| Alert Gift | `alert` | 600x400, pojok kiri atas | Notifikasi nama pengirim |
| Efek Layar | `efek` | 1920x1080, penuh | Confetti, hujan emoji, getar |
| Musik | `musik` | 100x100, disembunyikan | Hanya pemutar audio |

Memisahkan musik ke channel sendiri berguna: kalau kamu menyembunyikan
overlay efek, musiknya tetap jalan.

### Cara memakai

Di tiap aksi overlay ada kolom **Channel**. Kosongkan untuk overlay utama,
atau isi nama channel-nya.

Di tab Overlay, **Channel** berupa dropdown yang otomatis berisi:

- `main` (overlay utama)
- semua channel yang dipakai rule-mu
- channel yang sedang terhubung, lengkap dengan jumlahnya — mis. `alert (2 terbuka)`

Channel baru tetap bisa diketik langsung. Memilih channel langsung
memperbarui URL yang bisa kamu **Salin URL** ke OBS, dan tombol **Uji** akan
mengirim ke channel itu. Di bawah URL ada indikator apakah Browser Source
untuk channel tersebut sudah terbuka.

> Kalau aksi melapor *"belum ada overlay yang membukanya"*, berarti Browser
> Source untuk channel itu belum ditambahkan di OBS, atau URL-nya salah ketik.

## Tab Overlay

Atur audio dan efek visual, lalu coba langsung dengan tombol **Uji** tanpa
menunggu gift asli.

### Audio — diputar DI DALAM overlay

Ini bedanya dengan "Mainkan suara di PC": audio overlay diputar oleh halaman
overlay itu sendiri, jadi **OBS menangkapnya otomatis** sebagai bagian dari
Browser Source. Tidak perlu menyetel Desktop Audio, dan suaranya tidak
bocor ke aplikasi lain.

| Aksi | Fungsi |
|---|---|
| **Suara di overlay** | Efek suara sekali jalan saat gift masuk |
| **Musik latar overlay** | Musik yang diulang terus; `play` / `stop` / `volume`, semuanya dengan fade halus |
| Mainkan suara di PC | Yang lama — hanya keluar di speaker PC |

File bisa diambil dari **mana saja di komputer** (mp3, wav, ogg, m4a, flac,
opus). Aplikasi menyajikannya lewat server lokal.

### Efek visual

| Efek | Tampilan |
|---|---|
| **Confetti** | Kertas warna berjatuhan (jumlah bisa diatur, maks 400) |
| **Layar bergetar** | Overlay berguncang sesaat |
| **Kilat warna** | Layar berkedip dengan warna pilihan |
| **Teks melayang** | Teks besar naik lalu memudar — bisa pakai `{user}`, `{gift}` |
| **Hujan emoji** | Emoji berjatuhan dari atas layar |

Semua efek bisa digabung dalam satu rule. Contoh di `config/rules.yaml`:
gift ≥500 koin → hujan mawar + layar bergetar + teks nama pengirim.

## Overlay di OBS

1. Pastikan aplikasi berjalan (overlay otomatis aktif).
2. Di OBS: **+ → Browser Source**.
3. URL: `http://127.0.0.1:8777/overlay`
4. Ukuran: **1920 × 1080**.
5. Centang *Shutdown source when not visible* supaya hemat resource.

Latar belakang halaman sudah transparan. Halaman menyambung ulang sendiri
kalau aplikasi di-restart.

Ganti port lewat `overlay.port` di `config/settings.yaml`.

---

## Pengaman

Aksi tidak langsung dijalankan begitu saja — ada beberapa lapis pengaman:

- **Antrian serial** — aksi dijalankan satu per satu, tidak tumpang tindih
  walau gift datang bertubi-tubi.
- **Cooldown per rule** — jeda minimum antar pemicu.
- **Maks per jam** — batas jumlah pemicu per rule.
- **Batas antrian** (default 50) — event baru di-drop kalau antrian menumpuk.
- **Konfirmasi** — dialog untuk aksi berbahaya, auto-batal kalau didiamkan.
- **Hard cap reboot** — maks 2×/jam, **tidak bisa dilewati setting rule**.
- **Tombol PANIC** — selalu terlihat di status bar. Sekali klik: semua aksi
  berhenti dan antrian dikosongkan. Klik lagi untuk melanjutkan.

### Catatan gift streak
Gift yang bisa di-*streak* (Rose, dll) mengirim event berkali-kali selama
streak berlangsung. Aplikasi ini **hanya menghitung sekali di akhir streak**,
jadi satu streak 20 Rose tidak memicu aksi 20 kali.

---

## Konfigurasi

`config/settings.yaml` — pengaturan aplikasi (dibuat otomatis saat pertama jalan).
`config/rules.yaml` — daftar rule (ditimpa tiap kali menyimpan dari GUI).
`config/gifts.json` — cache katalog gift TikTok (dibuat otomatis).
`config/game_profiles.yaml` — posisi tombol game hasil kalibrasi.
`config/gift_icons/` — cache gambar ikon gift (dibuat otomatis, ±5 MB).
`vendor/` — binary scrcpy hasil unduhan (dibuat otomatis, ±12 MB).
`config/rules.yaml.bak` — cadangan rule otomatis sebelum setiap penyimpanan.

Isi `config/rules.yaml` bawaan sudah berisi 5 contoh rule siap pakai.

---

## Masalah Umum

| Gejala | Penyebab / solusi |
|---|---|
| `adb tidak ditemukan` | Buka tab scrcpy → **Unduh scrcpy** (adb ikut di dalamnya), atau isi `adb.path` di settings.yaml |
| Device `unauthorized` | Buka HP, tekan **Allow** pada dialog USB debugging |
| `@user sedang tidak live` | Akun harus benar-benar sedang siaran |
| **WebSocket ditolak (HTTP 400/401/403)** | Isi Sign API key → aplikasi otomatis pakai backend EulerStream. Lihat bagian di bawah |
| Batas koneksi EulerStream (4429) | Tutup koneksi lain ke akun yang sama, tunggu ~1 menit |
| Gift muncul sebagai "Gift #12345" | Gift belum ada di katalog — klik **Segarkan** di tab Gift |
| Error sign server / rate limit | Klik **Cek kuota** di tab Koneksi; kalau habis, tunggu reset |
| Aksi sistem gagal di HP fisik | Sebagian butuh izin khusus; hasil per aksi terlihat di tab Log |
| Overlay kosong di OBS | Cek aplikasi jalan, dan URL/port cocok dengan settings |
| Tombol PC tidak jalan (macOS) | System Settings → Privacy → Accessibility → izinkan Terminal/Python |
| Unduhan scrcpy gagal | Cek internet; atau install manual lalu isi `scrcpy.path` di settings.yaml |
| Wireless gagal tersambung | HP harus terhubung USB dulu, dan satu jaringan WiFi dengan PC |
| Aksi bilang "belum ada overlay yang membukanya" | Browser Source untuk channel itu belum dibuka di OBS, atau URL-nya salah |
| Audio overlay tidak bunyi | Cek overlay terbuka di OBS (tab Overlay menampilkan jumlahnya). Di browser biasa, klik halaman sekali untuk membuka blokir autoplay |
| File audio ditolak | Format harus mp3/wav/ogg/m4a/flac/opus, maks 64 MB |
| Tap game meleset | Cek indikator orientasi di tab Game — HP harus dalam posisi yang sama seperti saat kalibrasi |
| Tes tekan tidak terasa | Layar HP mungkin terkunci; buka kuncinya dulu |
| Tap game tidak bereaksi sama sekali | Game itu memblokir input adb — tidak bisa diatasi dari aplikasi |
| Dropdown gift kosong | Klik **Segarkan** di tab Gift; butuh internet. Nama gift tetap bisa diketik manual |

---

## Dua backend koneksi

Aplikasi punya dua cara menyambung ke TikTok LIVE. Pilih di tab **Koneksi → Backend**.

| Backend | Butuh API key | Kapan dipakai |
|---|---|---|
| **EulerStream** | Ya | WebSocket terkelola. **Paling andal** — dipakai otomatis kalau API key terisi |
| **TikTokLive** | Tidak | Koneksi langsung ke TikTok. Gratis, tapi sering ditolak HTTP 400 (lihat bawah) |
| **Otomatis** (bawaan) | — | Pakai EulerStream kalau ada API key, kalau tidak TikTokLive |

Ambil API key gratis di [eulerstream.com](https://www.eulerstream.com/pricing),
lalu isi di tab **Koneksi → Sign API key**.

### Batas koneksi EulerStream

Paket punya batas **koneksi serentak**, bukan hanya jumlah request. Kalau muncul
pesan batas koneksi (kode 4429), pastikan tidak ada aplikasi atau tab lain yang
masih tersambung ke akun yang sama, lalu tunggu sekitar satu menit — aplikasi
menyambung ulang sendiri dengan jeda panjang.

Klik **Cek kuota** untuk melihat sisa kuota harian/jam/menit.

## Kalau koneksi ditolak HTTP 400

Ini penyebab kegagalan koneksi yang paling sering, dan **bukan bug aplikasi**.

**Apa yang terjadi.** TikTok tidak mengizinkan koneksi langsung ke layanan
webcast-nya tanpa tanda tangan (signature). TikTokLive memakai layanan pihak
ketiga **EulerStream** untuk itu. Kalau EulerStream sedang tidak bisa memberi
URL WebSocket TikTok yang asli, ia mengembalikan **proxy fallback** miliknya
(`wss://ws-fallback.eulerstream.com`) — dan proxy itu menolak koneksi tanpa
API key berbayar. Hasilnya: HTTP 400.

**Cara memastikan ini yang terjadi:**
1. Tab Koneksi → klik **Cek kuota**.
2. Kalau kuota masih penuh (mis. `hari: 100/100`) tapi koneksi tetap ditolak,
   berarti memang sedang jatuh ke fallback proxy — bukan soal kuota.

**Solusinya:** isi **Sign API key** di tab Koneksi. Aplikasi akan otomatis
beralih ke backend **EulerStream** yang memakai jalur berbeda dan tidak
terpengaruh masalah ini.

> Catatan: API key saja **tidak** memperbaiki backend TikTokLive — sign server
> tetap mengembalikan fallback proxy. Yang menyelesaikan masalah adalah
> berpindah backend, dan itu terjadi otomatis saat key terisi.

Aplikasi **berhenti mencoba ulang** saat kena 400/401/403, karena retry tidak
akan menolong dan hanya menghabiskan kuota sign server.

Semua fitur lain (rule, aksi ADB, overlay, katalog gift) tetap berfungsi penuh
tanpa koneksi live — pakai **Test Run** di tab Rules untuk mengujinya.

## Test

```bash
.venv/bin/python -m pytest tests/ -q      # macOS/Linux
.venv\Scripts\python -m pytest tests/ -q   # Windows
```

Menguji rule matching, kondisi, cooldown, rate limit, antrian, kill switch,
dan substitusi placeholder — semuanya tanpa perlu device atau koneksi live.
