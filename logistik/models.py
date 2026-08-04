import uuid
from django.db import models
from django.contrib.auth.models import User
import qrcode
from io import BytesIO
from django.core.files import File

class SuratJalan(models.Model):
    no_surat_jalan = models.CharField(max_length=50, unique=True)
    tujuan = models.CharField(max_length=200)
    plat_nomor_truk = models.CharField(max_length=20)
    
    # --- DUA BARIS INI BARU DITAMBAHKAN ---
    target_palet = models.IntegerField(default=0)  # Batas maksimal palet yang diizinkan dokumen
    termuat_palet = models.IntegerField(default=0) # Angka real-time palet yang sudah masuk truk
    
    status = models.CharField(max_length=20, default='Pending') # Pending, Selesai
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.no_surat_jalan} - {self.plat_nomor_truk}"

# (CATATAN PENTING: Class model lainnya di bawahnya tidak perlu diubah, biarkan seperti semula)

class MasterBarang(models.Model):
    kode_sku = models.CharField(max_length=50, primary_key=True)
    nama_produk = models.CharField(max_length=150)
    kategori = models.CharField(max_length=100)
    tipe_kemasan = models.CharField(max_length=100) # Misal: Palet 50 Sak
    umur_simpan_bulan = models.IntegerField(default=24)

    def __str__(self):
        return f"{self.kode_sku} - {self.nama_produk}"

class Lokasi(models.Model):
    kode_lokasi = models.CharField(max_length=20, unique=True)
    nama_area = models.CharField(max_length=100)
    tipe_zona = models.CharField(max_length=50) # Bagging, Penyimpanan, Loading Dock
    kapasitas_maksimal_palet = models.IntegerField(default=0) # 0 = tanpa batas

    def __str__(self):
        return self.nama_area

# --- 1. TAMBAH MODEL BARU: KAVLING ---
class Kavling(models.Model):
    # Model ini bertindak sebagai KOORDINAT SPESIFIK (Misal: S-01-05)
    kode_kavling = models.CharField(max_length=20, unique=True)
    lokasi_induk = models.ForeignKey(Lokasi, on_delete=models.CASCADE, related_name='daftar_kavling')
    baris = models.CharField(max_length=10) # Contoh: '01'
    slot = models.CharField(max_length=10)  # Contoh: '05'
    
    def __str__(self):
        return f"{self.kode_kavling} - {self.lokasi_induk.nama_area}"

class LotProduksi(models.Model):
    id_lot = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kode_barang = models.ForeignKey(MasterBarang, on_delete=models.CASCADE)
    tanggal_masuk = models.DateTimeField(auto_now_add=True)
    qty = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # --- 2. REVISI: Ubah ForeignKey dari Lokasi menjadi Kavling ---
    lokasi_sekarang = models.ForeignKey(Kavling, on_delete=models.RESTRICT, related_name='lot_tersimpan', null=True, blank=True)

    qr_code_image = models.ImageField(upload_to='qr_codes/', blank=True, null=True)
    batch_sap = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(
        max_length=20, 
        choices=[('Aktif', 'Aktif'), ('Habis', 'Habis Diproses')],
        default='Aktif'
    )
    
    lot_induk = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='lot_turunan'
    )

    def __str__(self):
        id_pendek = str(self.id_lot)[:6].upper()
        return f"{self.kode_barang.nama_produk} | {self.qty} | {id_pendek}"

    def save(self, *args, **kwargs):
        if not self.qr_code_image:
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(str(self.id_lot))
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            file_name = f"QR_{self.id_lot}.png"
            self.qr_code_image.save(file_name, File(buffer), save=False)
        super().save(*args, **kwargs)

class LogTraceability(models.Model):
    id_log = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    id_lot = models.ForeignKey(LotProduksi, on_delete=models.CASCADE)
    
    # --- 3. REVISI: Ubah ForeignKey asal & tujuan dari Lokasi menjadi Kavling ---
    lokasi_asal = models.ForeignKey(Kavling, related_name='mutasi_keluar', on_delete=models.RESTRICT, null=True, blank=True)
    lokasi_tujuan = models.ForeignKey(Kavling, related_name='mutasi_masuk', on_delete=models.RESTRICT, null=True, blank=True)
    
    qty_masuk = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    qty_hasil = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    selisih_rendemen = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    user_scanner = models.ForeignKey(User, on_delete=models.RESTRICT)
    waktu_scan = models.DateTimeField(auto_now_add=True)
    surat_jalan = models.ForeignKey(SuratJalan, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name_plural = "Log Traceability"