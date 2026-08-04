"""
URL configuration for sistem_logistik project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from logistik import views 
from django.contrib.auth import views as auth_views
from logistik import views

urlpatterns = [
    path('admin/logout/', auth_views.LogoutView.as_view(next_page='login')),
    path('admin/', admin.site.urls),
    
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    
    # ==========================================
    # 1. RUTE HALAMAN ANTARMUKA (UI)
    # ==========================================
    path('scanner/', views.halaman_scanner, name='scanner'),
    path('laporan/', views.laporan_traceability, name='laporan'),
    path('penerimaan/', views.penerimaan_barang, name='penerimaan'),
    
    # ==========================================
    # 2. RUTE API PROSES & GENERATE
    # ==========================================
    path('proses-scan/', views.proses_scan, name='proses_scan'),
    path('api/generate-batch-qr/', views.generate_batch_qr, name='generate_batch_qr'),

    # ==========================================
    # 3. RUTE API CRUD MASTER DATA (PENGGANTI FUNGSI LAMA)
    # ==========================================
    # Menggunakan <str:tipe> agar 1 URL bisa dipakai untuk barang, lokasi, sj, dan akun
    path('tambah-master/<str:tipe>/', views.tambah_master_ajax, name='tambah_master_ajax'),
    path('edit-master/<str:tipe>/<str:id_data>/', views.edit_master_ajax, name='edit_master_ajax'),
    path('hapus-master/<str:tipe>/<str:id_data>/', views.hapus_master_ajax, name='hapus_master_ajax'),
    path('api/rekomendasi-fifo/', views.api_rekomendasi_fifo, name='api_rekomendasi_fifo'),
    path('api/kepadatan-lokasi/', views.api_kepadatan_lokasi, name='api_kepadatan_lokasi'),

    path('api/rekomendasi-kavling/', views.api_rekomendasi_kavling, name='api_rekomendasi_kavling'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)