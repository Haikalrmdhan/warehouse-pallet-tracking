import json
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.models import User, Group
from django.db.models import Q, Count, Subquery, OuterRef, Min
from django.utils import timezone 
from datetime import timedelta
from django.contrib.auth.views import LoginView
from django.urls import reverse
import qrcode
from io import BytesIO
from django.core.files import File
from django.core.paginator import Paginator
import uuid
from django.http import HttpResponseForbidden
from .models import LotProduksi, Lokasi, LogTraceability, MasterBarang, SuratJalan, Kavling

# ==========================================
# KONSTANTA HAK AKSES GUDANG (PENGAMAN KODE)
# ==========================================
ROLE_OPERATOR = 'Operator'
ROLE_SUPERVISOR = 'Supervisor'
ROLE_ADMIN = 'Admin'

# ==========================================
# CUSTOM LOGIN VIEW
# ==========================================
class CustomLoginView(LoginView):
    template_name = 'login.html'

    def get_success_url(self):
        user = self.request.user
        if user.groups.filter(name=ROLE_OPERATOR).exists():
            return reverse('scanner')
        elif user.groups.filter(name=ROLE_SUPERVISOR).exists():
            return reverse('laporan')
        elif user.groups.filter(name=ROLE_ADMIN).exists():
            return reverse('penerimaan')
        return reverse('admin:index')

# ==========================================
# HALAMAN SCANNER (OPERATOR FORKLIFT)
# ==========================================
@login_required 
def halaman_scanner(request):
    if request.user.is_superuser:
        nama_role = "Superadmin"
    elif request.user.groups.filter(name=ROLE_SUPERVISOR).exists():
        nama_role = "Kepala Gudang"
    else:
        nama_role = "Operator Gudang"
        
    if not request.user.groups.filter(name=ROLE_OPERATOR).exists():
        return HttpResponseForbidden("<h1>403 Akses Ditolak</h1><p>Maaf, halaman ini hanya dapat diakses oleh Operator Gudang.</p>")

    riwayat_terbaru = LogTraceability.objects.filter(
        user_scanner=request.user
    ).select_related('lokasi_tujuan', 'surat_jalan', 'id_lot__kode_barang').order_by('-waktu_scan')[:20]
        
    daftar_sj = SuratJalan.objects.filter(status='Pending')

    # --- LOGIKA REKOMENDASI FIFO ---
    rekomendasi_fifo = LotProduksi.objects.filter(
        status='Aktif',
        lokasi_sekarang__isnull=False
    ).select_related('kode_barang', 'lokasi_sekarang__lokasi_induk').order_by('tanggal_masuk')[:3]

    for lot in rekomendasi_fifo:
        if lot.tanggal_masuk:
            lot.umur_hari = (timezone.now() - lot.tanggal_masuk).days
        else:
            lot.umur_hari = 0

    context = {
        'daftar_sj': daftar_sj, 
        'nama_role': nama_role,
        'riwayat_hari_ini': riwayat_terbaru,
        'rekomendasi_fifo': rekomendasi_fifo,
        'daftar_barang': MasterBarang.objects.all(),
    }
    return render(request, 'scanner.html', context)

@login_required 
def proses_scan(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        id_lot_scanned = data.get('id_lot')
        mode_scan = data.get('mode_scan') 
        
        lokasi_tujuan_id = data.get('lokasi_tujuan_id') # Sekarang berisi ID Kavling
        surat_jalan_id = data.get('surat_jalan_id')

        try:
            with transaction.atomic():
                lot_barang = LotProduksi.objects.get(id_lot=id_lot_scanned)
                
                if lot_barang.status == 'Terkirim' and mode_scan != 'batal_muat':
                    return JsonResponse({'status': 'error', 'message': 'Gagal! Palet ini sudah tercatat terkirim dan keluar dari gudang.'})

                lokasi_awal = lot_barang.lokasi_sekarang

                # --- JALUR 1: MODE PINDAH KAVLING ---
                if mode_scan == 'pindah':
                    if not lokasi_tujuan_id:
                        return JsonResponse({'status': 'error', 'message': 'Pilih lokasi kavling tujuan terlebih dahulu!'})
                        
                    # Mengunci baris kavling mikro yang dituju
                    lokasi_akhir = Kavling.objects.select_for_update().select_related('lokasi_induk').get(id=lokasi_tujuan_id)

                    if lokasi_awal and lokasi_awal.id == lokasi_akhir.id:
                        return JsonResponse({'status': 'error', 'message': f'Palet sudah berada di Kavling {lokasi_akhir.kode_kavling}!'})

                    # Validasi apakah kavling tujuan tersebut sedang ditempati palet aktif lain
                    if LotProduksi.objects.filter(lokasi_sekarang=lokasi_akhir, status='Aktif').exists():
                        return JsonResponse({'status': 'error', 'message': f'Gagal! Kavling {lokasi_akhir.kode_kavling} sudah terisi palet lain.'})

                    # Validasi kapasitas total blok makro
                    if lokasi_akhir.lokasi_induk.kapasitas_maksimal_palet > 0:
                        isi_sekarang = LotProduksi.objects.filter(lokasi_sekarang__lokasi_induk=lokasi_akhir.lokasi_induk, status='Aktif').count()
                        if isi_sekarang >= lokasi_akhir.lokasi_induk.kapasitas_maksimal_palet:
                            return JsonResponse({'status': 'error', 'message': f'Gagal! Kapasitas {lokasi_akhir.lokasi_induk.nama_area} sudah penuh ({isi_sekarang}/{lokasi_akhir.lokasi_induk.kapasitas_maksimal_palet}).'})

                    lot_barang.lokasi_sekarang = lokasi_akhir
                    lot_barang.save()

                    LogTraceability.objects.create(
                        id_lot=lot_barang,
                        lokasi_asal=lokasi_awal, 
                        lokasi_tujuan=lokasi_akhir,
                        qty_masuk=lot_barang.qty, 
                        qty_hasil=lot_barang.qty, 
                        user_scanner=request.user 
                    )
                    return JsonResponse({'status': 'success', 'message': f"Sukses! Palet berhasil dipindah ke Kavling {lokasi_akhir.kode_kavling}."})
                    
                # --- JALUR 2: MODE MUAT KE TRUK (DISPATCH) ---
                elif mode_scan == 'dispatch':
                    if not surat_jalan_id:
                        return JsonResponse({'status': 'error', 'message': 'Pilih Surat Jalan terlebih dahulu!'})
                    
                    sj = SuratJalan.objects.select_for_update().get(id=surat_jalan_id)

                    if sj.target_palet > 0 and sj.termuat_palet >= sj.target_palet:
                        return JsonResponse({'status': 'error', 'message': f'Gagal! Kuota muatan SJ {sj.no_surat_jalan} sudah terpenuhi ({sj.termuat_palet}/{sj.target_palet} Palet).'})

                    # --- BLOK VALIDASI FIFO ---
                    lot_tertua = LotProduksi.objects.filter(
                        kode_barang=lot_barang.kode_barang,
                        status='Aktif'
                    ).order_by('tanggal_masuk').first()

                    if lot_tertua and lot_tertua.id_lot != lot_barang.id_lot:
                        if lot_barang.tanggal_masuk and lot_tertua.tanggal_masuk:
                            selisih_waktu = lot_barang.tanggal_masuk - lot_tertua.tanggal_masuk
                            if selisih_waktu.days > 0: 
                                lokasi_prioritas = lot_tertua.lokasi_sekarang.kode_kavling if lot_tertua.lokasi_sekarang else "Gudang"
                                pesan_error = (
                                    f"PELANGGARAN FIFO! Terdapat stok yang lebih lama mengendap. "
                                    f"Silakan ambil LOT: {str(lot_tertua.id_lot)[:8].upper()} di Kavling {lokasi_prioritas} terlebih dahulu."
                                )
                                return JsonResponse({'status': 'error', 'message': pesan_error})

                    lot_barang.status = 'Terkirim'
                    lot_barang.lokasi_sekarang = None 
                    lot_barang.save()

                    sj.termuat_palet += 1
                    if sj.target_palet > 0 and sj.termuat_palet >= sj.target_palet:
                        sj.status = 'Selesai'
                    sj.save()

                    LogTraceability.objects.create(
                        id_lot=lot_barang,
                        lokasi_asal=lokasi_awal, 
                        lokasi_tujuan=None,
                        qty_masuk=lot_barang.qty, 
                        qty_hasil=lot_barang.qty, 
                        user_scanner=request.user,
                        surat_jalan=sj 
                    )
                    
                    if sj.status == 'Selesai':
                        pesan_sukses = f"Sukses! SJ: {sj.no_surat_jalan} OTOMATIS SELESAI ({sj.termuat_palet}/{sj.target_palet} Palet)."
                    else:
                        pesan_sukses = f"Sukses! Palet dimuat ke SJ: {sj.no_surat_jalan} ({sj.termuat_palet}/{sj.target_palet} Palet)."

                    return JsonResponse({'status': 'success', 'message': pesan_sukses})

                # --- JALUR 3: MODE BATAL MUAT ---
                elif mode_scan == 'batal_muat':
                    if lot_barang.status != 'Terkirim':
                        return JsonResponse({'status': 'error', 'message': 'Gagal! Palet ini BUKAN berstatus Terkirim/Muat.'})
                    
                    log_terakhir = LogTraceability.objects.filter(
                        id_lot=lot_barang, 
                        surat_jalan__isnull=False
                    ).order_by('-waktu_scan').first()

                    if not log_terakhir:
                        return JsonResponse({'status': 'error', 'message': 'Gagal! Riwayat Surat Jalan untuk palet ini tidak ditemukan.'})

                    sj = log_terakhir.surat_jalan
                    lokasi_pengembalian = log_terakhir.lokasi_asal

                    if not lokasi_pengembalian:
                        return JsonResponse({'status': 'error', 'message': 'Gagal! Titik lokasi awal sebelum muat tidak diketahui.'})

                    # Cek jika kavling asal ternyata sudah terisi palet lain saat ditinggal
                    if LotProduksi.objects.filter(lokasi_sekarang=lokasi_pengembalian, status='Aktif').exists():
                        return JsonResponse({'status': 'error', 'message': f'Gagal! Kavling asal ({lokasi_pengembalian.kode_kavling}) sudah diisi palet lain. Silakan pindahkan manual via menu admin.'})

                    lot_barang.status = 'Aktif'
                    lot_barang.lokasi_sekarang = lokasi_pengembalian
                    lot_barang.save()

                    if sj.termuat_palet > 0:
                        sj.termuat_palet -= 1
                    
                    if sj.status == 'Selesai' and sj.termuat_palet < sj.target_palet:
                        sj.status = 'Pending'
                    sj.save()

                    LogTraceability.objects.create(
                        id_lot=lot_barang,
                        lokasi_asal=None, 
                        lokasi_tujuan=lokasi_pengembalian,
                        surat_jalan=sj,
                        qty_masuk=lot_barang.qty, 
                        qty_hasil=lot_barang.qty, 
                        user_scanner=request.user
                    )
                    return JsonResponse({'status': 'success', 'message': f"Batal Muat Sukses! Palet dilepas dari {sj.no_surat_jalan} & dikembalikan ke Kavling {lokasi_pengembalian.qrcode_kavling if hasattr(lokasi_pengembalian, 'qrcode_kavling') else lokasi_pengembalian.kode_kavling}."})

        except LotProduksi.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'QR Code tidak dikenali sistem!'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Terjadi kesalahan: {str(e)}'})

    return JsonResponse({'status': 'error', 'message': 'Metode tidak diizinkan'})

# --- API NEW: SMART SUGGESTION UNTUK MENDAPATKAN KAVLING KOSONG ---
@login_required
def api_rekomendasi_kavling(request):
    blok_id = request.GET.get('blok_id')
    if not blok_id:
        return JsonResponse({'status': 'error', 'message': 'Blok ID tidak disediakan'})
    
    # Mencari kavling yang terikat pada blok_id dan tidak memiliki lot berstatus 'Aktif'
    kavling_kosong = Kavling.objects.filter(lokasi_induk_id=blok_id).annotate(
        jumlah_aktif=Count('lot_tersimpan', filter=Q(lot_tersimpan__status='Aktif'))
    ).filter(jumlah_aktif=0).order_by('baris', 'slot')
    
    data_kavling = []
    for kav in kavling_kosong:
        data_kavling.append({
            'id': kav.id,
            'kode_kavling': kav.kode_kavling
        })
        
    # Ambil baris pertama sebagai rekomendasi otomatis terbaik
    rekomendasi_terbaik_id = data_kavling[0]['id'] if data_kavling else None
    
    return JsonResponse({
        'status': 'success',
        'data': data_kavling,
        'rekomendasi_terbaik_id': rekomendasi_terbaik_id
    })

@login_required
def api_rekomendasi_fifo(request):
    kode_sku = request.GET.get('sku')
    if not kode_sku:
        return JsonResponse({'status': 'error', 'message': 'SKU tidak valid'})

    rekomendasi = LotProduksi.objects.filter(
        kode_barang__kode_sku=kode_sku,
        status='Aktif',
        lokasi_sekarang__isnull=False
    ).select_related('kode_barang', 'lokasi_sekarang__lokasi_induk').order_by('tanggal_masuk')[:3]

    data_hasil = []
    waktu_sekarang = timezone.now()
    
    for lot in rekomendasi:
        umur = (waktu_sekarang - lot.tanggal_masuk).days if lot.tanggal_masuk else 0
        data_hasil.append({
            'id_lot_short': str(lot.id_lot)[:8].upper(),
            'id_lot_full': str(lot.id_lot),
            'nama_produk': lot.kode_barang.nama_produk,
            'batch_sap': lot.batch_sap,
            'qty_lengkap': f"{lot.qty} {lot.kode_barang.tipe_kemasan}",
            'lokasi': f"Kavling {lot.lokasi_sekarang.kode_kavling} ({lot.lokasi_sekarang.lokasi_induk.nama_area})",
            'umur_hari': umur
        })
    return JsonResponse({'status': 'success', 'data': data_hasil})

@login_required
def api_kepadatan_lokasi(request):
    try:
        # Menghitung kapasitas terisi dari relasi berjenjang Lokasi -> Kavling -> LotProduksi
        lokasi_list = Lokasi.objects.annotate(
            terisi=Count('daftar_kavling__lot_tersimpan', filter=Q(daftar_kavling__lot_tersimpan__status='Aktif'))
        ).order_by('nama_area')

        data_hasil = []
        for loc in lokasi_list:
            kapasitas = loc.kapasitas_maksimal_palet
            terisi = loc.terisi
            persentase = int((terisi / kapasitas) * 100) if kapasitas > 0 else 0

            if persentase >= 100:
                status_warna = 'danger'
                teks_status = 'Penuh'
            elif persentase >= 75:
                status_warna = 'warning'
                teks_status = 'Hampir Penuh'
            else:
                status_warna = 'success'
                teks_status = 'Tersedia'

            data_hasil.append({
                'id': loc.id,
                'nama_area': loc.nama_area,
                'terisi': terisi,
                'kapasitas': kapasitas,
                'persentase': persentase,
                'status_warna': status_warna,
                'teks_status': teks_status
            })
        return JsonResponse({'status': 'success', 'data': data_hasil})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

# ==========================================
# HALAMAN LAPORAN (KEPALA GUDANG)
# ==========================================
@login_required
def laporan_traceability(request):
    if not request.user.groups.filter(name=ROLE_SUPERVISOR).exists():
        return HttpResponseForbidden("<h1>403 Akses Ditolak</h1><p>Maaf, halaman ini hanya dapat diakses oleh Kepala Gudang.</p>")
    
    query_lot = request.GET.get('q', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    user_scan = request.GET.get('user_scan', '')
    lokasi_awal = request.GET.get('lokasi_awal', '')
    lokasi_tujuan = request.GET.get('lokasi_tujuan', '')
    surat_jalan_filter = request.GET.get('surat_jalan', '')
    status_aktif = request.GET.get('status_aktif', '')
    dispatch_hari_ini = request.GET.get('dispatch_hari_ini', '')
    inbound_hari_ini = request.GET.get('inbound_hari_ini', '')
    
    hari_ini = timezone.now().date()
    riwayat_log = LogTraceability.objects.select_related(
        'id_lot', 'id_lot__kode_barang', 'surat_jalan', 'lokasi_asal__lokasi_induk', 'lokasi_tujuan__lokasi_induk'
    ).order_by('-waktu_scan')

    log_terakhir = LogTraceability.objects.filter(id_lot=OuterRef('id_lot')).order_by('-waktu_scan')
    lot_info = None

    if query_lot:
        lot_info = LotProduksi.objects.filter(id_lot__icontains=query_lot).first()
        riwayat_log = riwayat_log.filter(id_lot=lot_info) if lot_info else riwayat_log.none()

    if start_date:
        riwayat_log = riwayat_log.filter(waktu_scan__date__gte=start_date)
    if end_date:
        riwayat_log = riwayat_log.filter(waktu_scan__date__lte=end_date)
    if user_scan:
        riwayat_log = riwayat_log.filter(user_scanner__username__icontains=user_scan)
    if lokasi_awal: 
        riwayat_log = riwayat_log.filter(lokasi_asal__lokasi_induk_id=lokasi_awal)
    if lokasi_tujuan: 
        riwayat_log = riwayat_log.filter(id_log=Subquery(log_terakhir.values('id_log')[:1]), lokasi_tujuan__lokasi_induk_id=lokasi_tujuan, id_lot__status='Aktif')
    if surat_jalan_filter:
        riwayat_log = riwayat_log.filter(surat_jalan_id=surat_jalan_filter, lokasi_tujuan__isnull=True, id_lot__status='Terkirim').order_by('id_lot', '-waktu_scan').distinct('id_lot')

    if status_aktif == '1':
        riwayat_log = riwayat_log.filter(id_lot__status='Aktif')
        log_terbaru = LogTraceability.objects.filter(id_lot=OuterRef('id_lot')).order_by('-waktu_scan')
        riwayat_log = riwayat_log.filter(id_log=Subquery(log_terbaru.values('id_log')[:1]))

    if dispatch_hari_ini == '1':
        riwayat_log = riwayat_log.filter(waktu_scan__date=hari_ini, surat_jalan__isnull=False, lokasi_tujuan__isnull=True, id_lot__status='Terkirim')

    if inbound_hari_ini == '1':
        riwayat_log = riwayat_log.filter(waktu_scan__date=hari_ini, lokasi_asal__isnull=True)  

    total_palet_aktif = LotProduksi.objects.filter(status='Aktif').count()
    palet_terkirim_hari_ini = LogTraceability.objects.filter(waktu_scan__date=hari_ini, surat_jalan__isnull=False, lokasi_tujuan__isnull=True, id_lot__status='Terkirim').count()
    palet_masuk_hari_ini = LogTraceability.objects.filter(waktu_scan__date=hari_ini, lokasi_asal__isnull=True).count()

    pemetaan_gudang = Lokasi.objects.annotate(
        jumlah_palet=Count('daftar_kavling__lot_tersimpan', filter=Q(daftar_kavling__lot_tersimpan__status='Aktif'))
    ).order_by('nama_area')

    chart_labels = [loc.nama_area for loc in pemetaan_gudang]
    chart_data = [loc.jumlah_palet for loc in pemetaan_gudang]

    context = {
        'riwayat_log': riwayat_log,
        'daftar_lokasi': Lokasi.objects.all().order_by('nama_area'),
        'lot_info': lot_info,
        'query_lot': query_lot,
        'start_date': start_date,
        'end_date': end_date,
        'total_palet_aktif': total_palet_aktif,
        'palet_terkirim_hari_ini': palet_terkirim_hari_ini,
        'palet_masuk_hari_ini': palet_masuk_hari_ini,
        'total_alert': 0,
        'pemetaan_gudang': pemetaan_gudang,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'daftar_sj': SuratJalan.objects.all().order_by('-created_at'),
        'sj_terpilih': surat_jalan_filter,
        'status_aktif': status_aktif,
        'dispatch_hari_ini': dispatch_hari_ini,
        'inbound_hari_ini': inbound_hari_ini,
    }
    return render(request, 'laporan.html', context)

@login_required
def dashboard_kepala_gudang(request):
    context = {
        'zona_labels': ['Zona A', 'Zona B', 'Zona C'],
        'zona_data': [15, 25, 10],
        'chart_labels': ['Zona A', 'Zona B', 'Zona C'],
        'chart_data': [15, 25, 10],
    }
    return render(request, 'laporan.html', context)

# ==========================================
# HALAMAN ADMIN GUDANG (KELOLA MASTER)
# ==========================================
@login_required
def penerimaan_barang(request):
    if not request.user.groups.filter(name=ROLE_ADMIN).exists():
        return HttpResponseForbidden("<h1>403 Akses Ditolak</h1><p>Maaf, halaman ini hanya dapat diakses oleh Admin Gudang.</p>")
    
    query_sj = request.GET.get('q_sj', '').strip()
    status_sj = request.GET.get('status_sj', '').strip()
    sj_list = SuratJalan.objects.all().order_by('-created_at')

    if query_sj:
        sj_list = sj_list.filter(Q(no_surat_jalan__icontains=query_sj) | Q(plat_nomor_truk__icontains=query_sj))
    if status_sj:
        sj_list = sj_list.filter(status__iexact=status_sj)

    paginator = Paginator(sj_list, 10)
    page_number = request.GET.get('page')
    daftar_sj_paginated = paginator.get_page(page_number)

    context = {
        'daftar_barang': MasterBarang.objects.all().order_by('kode_sku'),
        'daftar_lokasi': Lokasi.objects.all().order_by('nama_area'),
        'daftar_sj': daftar_sj_paginated,
        'daftar_semua_barang': MasterBarang.objects.all().order_by('kode_sku'),
        'daftar_semua_lokasi': Lokasi.objects.all().order_by('nama_area'),
        'daftar_user': User.objects.filter(is_superuser=False).order_by('username'),     
        'q_sj': query_sj,
        'status_sj': status_sj,
    }
    return render(request, 'penerimaan.html', context)

# ==========================================
# API GENERATE QR MASSAL
# ==========================================
@login_required
def generate_batch_qr(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            batch_sap = data.get('batch_sap')
            kode_barang_id = data.get('kode_barang')
            jumlah_palet = int(data.get('jumlah_palet'))
            qty_per_palet = float(data.get('qty_per_palet'))
            # kavling_id = data.get('lokasi_id') # Form admin menyuplai ID Kavling
            lokasi_makro_id = data.get('lokasi_id')

            barang = MasterBarang.objects.get(kode_sku=kode_barang_id)
            # kavling = Kavling.objects.get(id=kavling_id)
            kavling = Kavling.objects.filter(lokasi_induk_id=lokasi_makro_id).first()

            hasil_qrs = []

            with transaction.atomic():
                for i in range(jumlah_palet):
                    lot_baru = LotProduksi.objects.create(
                        kode_barang=barang,
                        qty=qty_per_palet,
                        lokasi_sekarang=kavling,
                        status='Aktif',
                        batch_sap=batch_sap  
                    )
                    LogTraceability.objects.create(
                        id_lot=lot_baru,
                        lokasi_asal=None, 
                        lokasi_tujuan=kavling,
                        qty_masuk=qty_per_palet,
                        qty_hasil=qty_per_palet,
                        user_scanner=request.user
                    )
                    hasil_qrs.append({
                        'id_lot': str(lot_baru.id_lot),
                        'batch_sap': batch_sap,
                        'nama_barang': barang.nama_produk,
                        'qty': f"{qty_per_palet} {barang.tipe_kemasan}",
                        'url': lot_baru.qr_code_image.url if lot_baru.qr_code_image else ""
                    })
            return JsonResponse({'status': 'success', 'qrs': hasil_qrs})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

# ==========================================
# API PENGELOLAAN MASTER DATA (CRUD SENTRAL)
# ==========================================
@login_required
def tambah_master_ajax(request, tipe):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            if tipe == 'barang':
                MasterBarang.objects.create(
                    kode_sku=data.get('kode_sku'), nama_produk=data.get('nama_produk'),
                    kategori=data.get('kategori'), tipe_kemasan=data.get('tipe_kemasan'),
                    umur_simpan_bulan=int(data.get('umur_simpan', 24))
                )
            elif tipe == 'lokasi':
                    kode_lokasi=data.get('kode_lokasi')
                    nama_area=data.get('nama_area')
                    tipe_zona=data.get('tipe_zona')

                    # Parameter pembentuk grid kavling
                    jumlah_baris = int(data.get('jumlah_baris', 1))
                    slot_per_baris = int(data.get('slot_per_baris', 1))
                    total_kapasitas = jumlah_baris * slot_per_baris

                    # Gunakan transaction.atomic agar jika gagal generate kavling, lokasi batal dibuat
                    with transaction.atomic():
                        # 2. Buat Data Induk (Area Makro)
                        lokasi_baru = Lokasi.objects.create(
                            kode_lokasi=kode_lokasi, 
                            nama_area=nama_area,
                            tipe_zona=tipe_zona, 
                            kapasitas_maksimal_palet=total_kapasitas
                        )
                        
                        # 3. Looping Auto-Generate Kavling (Area Mikro)
                        kavling_list = []
                        for b in range(1, jumlah_baris + 1):
                            for s in range(1, slot_per_baris + 1):
                                # Format padding nol (misal: baris 1 menjadi '01')
                                str_baris = f"{b:02d}"
                                str_slot = f"{s:02d}"
                                
                                # Menghasilkan kode seperti U-01-05
                                kode_kv = f"{kode_lokasi}-{str_baris}-{str_slot}"
                                
                                kavling_list.append(Kavling(
                                    kode_kavling=kode_kv,
                                    lokasi_induk=lokasi_baru,
                                    baris=str_baris,
                                    slot=str_slot
                                ))
                        
                        # 4. Simpan ratusan kavling sekaligus dalam satu eksekusi query (Sangat cepat)
                        if kavling_list:
                            Kavling.objects.bulk_create(kavling_list)

            elif tipe == 'suratjalan':
                SuratJalan.objects.create(
                    no_surat_jalan=data.get('no_sj').strip().upper(), tujuan=data.get('tujuan'),
                    plat_nomor_truk=data.get('truk').strip().upper(), target_palet=int(data.get('target_palet', 0))
                )
            elif tipe == 'akun':
                username = data.get('username').strip()
                if User.objects.filter(username=username).exists():
                    return JsonResponse({'status': 'error', 'message': 'Username sudah terpakai!'})
                user = User.objects.create_user(username=username, password=data.get('password'))
                group, _ = Group.objects.get_or_create(name=data.get('role'))
                user.groups.add(group)
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
def edit_master_ajax(request, tipe, id_data):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            if tipe == 'barang':
                brg = MasterBarang.objects.get(kode_sku=id_data)
                brg.nama_produk = data.get('nama_produk')
                brg.kategori = data.get('kategori')
                brg.tipe_kemasan = data.get('tipe_kemasan')
                brg.umur_simpan_bulan = int(data.get('umur_simpan', 24))
                brg.save()
            elif tipe == 'lokasi':
                loc = Lokasi.objects.get(id=id_data)
                loc.kode_lokasi = data.get('kode_lokasi')
                loc.nama_area = data.get('nama_area')
                loc.tipe_zona = data.get('tipe_zona')
                loc.kapasitas_maksimal_palet = int(data.get('kapasitas', 0))
                loc.save()
            elif tipe == 'suratjalan':
                sj = SuratJalan.objects.get(id=id_data)
                if 'tujuan' in data: sj.tujuan = data.get('tujuan')
                if 'truk' in data: sj.plat_nomor_truk = data.get('truk').strip().upper()
                if 'status' in data: sj.status = data.get('status') 
                if 'target_palet' in data: sj.target_palet = int(data.get('target_palet', 0)) 
                sj.save()
            elif tipe == 'akun':
                usr = User.objects.get(id=id_data)
                if data.get('password'):
                    usr.set_password(data.get('password'))
                    usr.save()
                usr.groups.clear()
                group, _ = Group.objects.get_or_create(name=data.get('role'))
                usr.groups.add(group)
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
def hapus_master_ajax(request, tipe, id_data):
    if request.method == 'POST':
        try:
            if tipe == 'barang': MasterBarang.objects.get(kode_sku=id_data).delete()
            elif tipe == 'lokasi': Lokasi.objects.get(id=id_data).delete()
            elif tipe == 'suratjalan': SuratJalan.objects.get(id=id_data).delete()
            elif tipe == 'akun':
                usr = User.objects.get(id=id_data)
                if usr.is_superuser: return JsonResponse({'status': 'error', 'message': 'Superadmin tidak boleh dihapus!'})
                usr.delete()
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': "Data tidak bisa dihapus karena sedang digunakan dalam riwayat."})