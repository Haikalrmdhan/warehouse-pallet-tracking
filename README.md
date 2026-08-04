# 🏭 Warehouse Pallet Tracking System

Aplikasi pelacakan palet gudang berbasis web menggunakan teknologi 
QR Code.

## 📋 Deskripsi

Sistem ini dirancang untuk menjembatani celah visibilitas (blind spot) 
pada area penyimpanan pasca pengemasan, dengan mencatat setiap 
perpindahan palet secara digital melalui pemindaian QR Code.

## ⚙️ Teknologi

- **Backend**: Python / Django
- **Database**: PostgreSQL
- **Frontend**: HTML, CSS, JavaScript
- **Identifikasi**: QR Code (UUID)

## 🚀 Fitur Utama

- Generate QR Code unik per palet berbasis Batch Produksi
- Scan pindah lokasi dengan rekomendasi kapasitas area
- Validasi FIFO aktif pada proses muat ke truk
- Laporan visual pergerakan palet dengan filter dan cetak PDF
- Role-Based Access Control (Admin, Operator, Kepala Gudang)

## 🛠️ Cara Menjalankan

1. Clone repository
2. Masuk ke folder project
3. Buat virtual environment dan aktifkan
4. Install dependencies
5. Buat file `.env` berdasarkan `.env.example` dan isi dengan 
   konfigurasi database PostgreSQL
6. Jalankan migrasi
7. Jalankan server
8. Buka browser dan akses `http://127.0.0.1:8000`

## 👥 Role Pengguna

| Role | Akses |
|------|-------|
| Admin Gudang | Generate QR Code, kelola Surat Jalan, Lokasi, Barang, Akun |
| Operator Lapangan | Scan pindah lokasi, muat ke truk, batal muat |
| Kepala Gudang | Dashboard laporan, filter pelacakan, cetak PDF |

## 📚 Penelitian

Dibangun sebagai bagian dari skripsi:
**"Rancang Bangun Aplikasi Pelacakan Palet Gudang Berbasis Web 
Menggunakan Teknologi QR Code"**
