# Kosakata Video

Aplikasi pribadi untuk belajar kosakata dari video. Unggah video atau tempel link (Facebook, YouTube, TikTok, Instagram, X, dan lainnya). Setiap kosakata, idiom dan **slang** akan muncul di layar bersama artinya tepat saat diucapkan.

Alurnya mengikuti [innovationmech/video-translate](https://github.com/innovationmech/video-translate):

| Langkah | Alat |
|---|---|
| Ambil video dari link | `yt-dlp` |
| Transkripsi + waktu per kata | Whisper (`faster-whisper`, berjalan di komputer Anda) |
| Terjemahan kalimat, kosakata, slang & penjelasannya | Claude (`claude-opus-5-5`) |
| Kartu kata di atas video, CSV, SRT, unduh video bersubtitle | Browser |

## Pribadi

Aplikasi berjalan di komputer Anda sendiri pada `http://127.0.0.1:8000`, jadi hanya Anda yang bisa membukanya. Video dan hasilnya disimpan di folder `data/` di komputer Anda. Yang dikirim keluar hanya teks transkrip ke Claude untuk diterjemahkan.

## Cara menjalankan

1. Pasang **Python 3.10+** (centang *Add Python to PATH* di Windows).
2. Unduh repo ini (tombol **Code → Download ZIP**), lalu ekstrak.
3. Salin `.env.example` menjadi `.env` dan isi `ANTHROPIC_API_KEY` (buat di https://console.anthropic.com/settings/keys).
4. Jalankan:
   - **Windows:** klik dua kali `start.bat`
   - **Mac/Linux:** `./start.sh`
5. Browser akan terbuka di `http://127.0.0.1:8000`.

Pertama kali dijalankan, paket Python dan model suara Whisper akan diunduh (beberapa menit).

## Tips

- **Model suara:** `small` seimbang; `large-v3-turbo` paling akurat dan cukup cepat bila ada GPU.
- **Video Facebook/Instagram yang butuh login:** isi `YTDLP_COOKIES_FROM_BROWSER=chrome` di `.env` (login dulu di Chrome).
- **Membuka dari HP di Wi-Fi yang sama:** set `HOST=0.0.0.0` dan `APP_PASSWORD=...` di `.env`, lalu buka `http://<IP-komputer>:8000`.
- 39 bahasa tujuan tersedia, bahasa video dideteksi otomatis.
