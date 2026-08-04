from django.contrib import admin
# Pastikan memanggil semua model yang Anda gunakan
from .models import Lokasi, LotProduksi, LogTraceability, MasterBarang, SuratJalan

# Mendaftarkan model master secara sederhana
admin.site.register(Lokasi)
admin.site.register(MasterBarang)
admin.site.register(SuratJalan)

# Kustomisasi tabel LotProduksi (QR Code) agar mudah difilter/dihapus
@admin.register(LotProduksi)
class LotProduksiAdmin(admin.ModelAdmin):
    # Menampilkan kolom-kolom ini di tabel Admin
    list_display = ('id_lot', 'kode_barang', 'batch_sap', 'qty', 'status', 'lokasi_sekarang')
    # Menambahkan kotak pencarian di atas tabel
    search_fields = ('id_lot', 'batch_sap')
    # Menambahkan filter di samping kanan tabel
    list_filter = ('status', 'lokasi_sekarang')

# Kustomisasi tabel Log Pergerakan
@admin.register(LogTraceability)
class LogTraceabilityAdmin(admin.ModelAdmin):
    list_display = ('waktu_scan', 'id_lot', 'lokasi_asal', 'lokasi_tujuan', 'user_scanner')
    search_fields = ('id_lot__id_lot',)
    list_filter = ('user_scanner', 'waktu_scan')

# --- PENGATURAN TEKS DASHBOARD ---
admin.site.site_header = "Dashboard Admin"  # Teks di pojok kiri atas
admin.site.site_title = "Sistem Traceability"    # Teks di tab browser
admin.site.index_title = "Manajemen Logistik & Traceability" # Teks di atas daftar tabel
admin.site.site_url = None