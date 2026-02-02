"""
URL configuration for marketplace_backend project.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
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
    path('pago-fallido/', views.pago_fallido, name='pago_fallido'),
    
    # --- 5. PANEL DE CLIENTE (Mis Reservas y Reseñas) ---
    path('mis-reservas/', views.mis_reservas, name='mis_reservas'),
    path('dejar-resena/<int:appointment_id>/', views.dejar_resena, name='dejar_resena'),
    path('anular-reserva/<int:reserva_id>/', views.anular_reserva, name='anular_reserva'),
    path('solicitar-reembolso/<int:reserva_id>/', views.solicitar_reembolso, name='solicitar_reembolso'),
    path('solicitar-cambio/<int:reserva_id>/', views.solicitar_cambio_hora, name='solicitar_cambio_hora'),
    path('lista-asesores/', views.lista_asesores, name='lista_asesores'),
    path('soporte/', views.enviar_soporte, name='enviar_soporte'),

    # --- 6. ADMINISTRACIÓN WEB (Para tu jefe) ---
    path('panel-jefe/', views.panel_admin, name='panel_administracion'), # <--- ESTA ES LA TUYA (Correcta)
    path('secreto-admin/', views.secreto_admin, name='secreto_admin'),   # <--- ESTA ES LA NUEVA QUE AGREGAMOS
    
    path('aprobar/<int:asesor_id>/', views.aprobar_asesor, name='aprobar_asesor'),
    path('rechazar/<int:asesor_id>/', views.rechazar_asesor, name='rechazar_asesor'),
    path('jefe/editar-precio/<int:asesor_id>/', views.admin_editar_precio, name='admin_editar_precio'),
    path('jefe/dashboard/', views.dashboard_financiero, name='dashboard_financiero'),
    path('jefe/resolver-reclamo/<int:reserva_id>/<str:accion>/', views.resolver_reclamo, name='resolver_reclamo'),
    path('jefe/observacion/<int:asesor_id>/', views.admin_enviar_observacion, name='admin_enviar_observacion'),
    path('jefe/editar-duracion/<int:asesor_id>/', views.admin_editar_duracion, name='admin_editar_duracion'),
    
    path('asesor/enviar-mensaje/', views.asesor_enviar_mensaje, name='asesor_enviar_mensaje'),
    path('jefe/chats/', views.admin_chat_dashboard, name='admin_chat_dashboard'),
    path('jefe/chat/<int:usuario_id>/', views.admin_chat_detail, name='admin_chat_detail'),
    
    path('api/chat/get/<int:usuario_id>/', views.api_obtener_mensajes, name='api_obtener_mensajes_admin'),
    path('api/chat/get/', views.api_obtener_mensajes, name='api_obtener_mensajes_asesor'),
    
    path('api/chat/read/<int:usuario_id>/', views.api_marcar_leido, name='api_marcar_leido_admin'),
    path('api/chat/read/', views.api_marcar_leido, name='api_marcar_leido_asesor'),
    
    # --- 7. RECUPERACIÓN DE CONTRASEÑA ---
    # --- 7. RECUPERACIÓN DE CONTRASEÑA (CORREGIDO) ---
    path('reset_password/', 
         auth_views.PasswordResetView.as_view(template_name="core/password_reset_form.html"), 
         name='password_reset'),

    path('reset_password_sent/', 
         auth_views.PasswordResetDoneView.as_view(template_name="core/password_reset_done.html"), 
         name='password_reset_done'),

    path('reset/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(template_name="core/password_reset_confirm.html"), 
         name='password_reset_confirm'),

    path('reset_password_complete/', 
         auth_views.PasswordResetCompleteView.as_view(template_name="core/password_reset_complete.html"), 
         name='password_reset_complete'),
]

# --- BLOQUE MÁGICO PARA VER ARCHIVOS EN RENDER ---
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {
        'document_root': settings.MEDIA_ROOT,
    }),
]