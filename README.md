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
