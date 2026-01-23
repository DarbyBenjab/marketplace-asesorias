"""
URL configuration for marketplace_backend project.
"""
from django.contrib import admin
from django.urls import path, include, re_path  # <--- SE AGREGÓ include y re_path
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve  # <--- IMPORTANTE: Se agregó serve
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # --- AGREGO ESTO PARA QUE FUNCIONE ALLAUTH (Google Login) ---
    path('accounts/', include('allauth.urls')),

    # --- 1. PORTADA Y BUSCADOR ---
    path('', views.lista_asesores, name='inicio'),
    
    # --- 2. AUTENTICACIÓN (Login / Logout / Registro) ---
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='lobby'), name='logout'),
    path('registro/', views.registro_unificado, name='registro_unificado'),
    path('verificar-email/', views.verificar_email, name='verificar_email'),
    path('lobby/', views.lobby, name='lobby'),
    path('asesor/<int:asesor_id>/perfil/', views.perfil_publico, name='perfil_publico'),
    path('borrar-cuenta/', views.borrar_cuenta_confirmacion, name='borrar_cuenta_confirmacion'),

    # --- 3. GESTIÓN DEL ASESOR ---
    path('panel-asesor/', views.panel_asesor, name='panel_asesor'),
    path('solicitud-asesor/', views.solicitud_asesor, name='solicitud_asesor'),
    path('mis-horarios/', views.gestionar_horarios, name='gestionar_horarios'),
    path('borrar-horario/<int:horario_id>/', views.borrar_horario, name='borrar_horario'),
    path('panel-asesor/editar/', views.editar_perfil_asesor, name='editar_perfil_asesor'),
    path('registrar-vacaciones/', views.registrar_vacaciones, name='registrar_vacaciones'),
    
    # --- 4. FLUJO DE RESERVA Y PAGO ---
    path('asesor/<int:asesor_id>/', views.detalle_asesor, name='detalle_asesor'),
    path('reservar-cita/<int:cita_id>/', views.reservar_hora, name='reservar_hora'),
    path('checkout/<int:reserva_id>/', views.checkout, name='checkout'),
    path('pago-exitoso/<int:reserva_id>/', views.pago_exitoso, name='pago_exitoso'),
    
    # --- 5. PANEL DE CLIENTE (Mis Reservas y Reseñas) ---
    path('mis-reservas/', views.mis_reservas, name='mis_reservas'),
    path('dejar-resena/<int:appointment_id>/', views.dejar_resena, name='dejar_resena'),
    path('anular-reserva/<int:reserva_id>/', views.anular_reserva, name='anular_reserva'),
    path('solicitar-reembolso/<int:reserva_id>/', views.solicitar_reembolso, name='solicitar_reembolso'),

    # --- 6. ADMINISTRACIÓN WEB (Para tu jefe) ---
    path('panel-jefe/', views.panel_admin, name='panel_administracion'),
    path('aprobar/<int:asesor_id>/', views.aprobar_asesor, name='aprobar_asesor'),
    path('rechazar/<int:asesor_id>/', views.rechazar_asesor, name='rechazar_asesor'),
    path('jefe/editar-precio/<int:asesor_id>/', views.admin_editar_precio, name='admin_editar_precio'),
    path('jefe/dashboard/', views.dashboard_financiero, name='dashboard_financiero'),
    path('jefe/resolver-reclamo/<int:reserva_id>/<str:accion>/', views.resolver_reclamo, name='resolver_reclamo'),
    
    # --- 7. RECUPERACIÓN DE CONTRASEÑA ---
    path('reset_password/', 
         auth_views.PasswordResetView.as_view(template_name="core/password_reset.html"), 
         name='password_reset'),

    path('reset_password_sent/', 
         auth_views.PasswordResetDoneView.as_view(template_name="core/password_reset_sent.html"), 
         name='password_reset_done'),

    path('reset/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(template_name="core/password_reset_form.html"), 
         name='password_reset_confirm'),

    path('reset_password_complete/', 
         auth_views.PasswordResetCompleteView.as_view(template_name="core/password_reset_done.html"), 
         name='password_reset_complete'),
]

# --- BLOQUE MÁGICO PARA VER ARCHIVOS EN RENDER ---
# 1. Configuración normal para modo DEBUG (Tu PC)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# 2. Configuración FORZADA para ver archivos en Producción (Render)
# Esto permite que Django entregue los archivos media aunque DEBUG sea False
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {
        'document_root': settings.MEDIA_ROOT,
    }),
]