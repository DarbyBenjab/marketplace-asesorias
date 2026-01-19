"""
URL configuration for marketplace_backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
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
"""
URL configuration for marketplace_backend project.
"""
from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    
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
    
    # --- 4. FLUJO DE RESERVA Y PAGO ---
    path('asesor/<int:asesor_id>/', views.detalle_asesor, name='detalle_asesor'),
    path('reservar-cita/<int:cita_id>/', views.reservar_hora, name='reservar_hora'),
    path('checkout/<int:reserva_id>/', views.checkout, name='checkout'),
    path('pago-exitoso/<int:reserva_id>/', views.pago_exitoso, name='pago_exitoso'),
    
    # --- 5. PANEL DE CLIENTE (Mis Reservas y Reseñas) ---
    path('mis-reservas/', views.mis_reservas, name='mis_reservas'),
    path('dejar-resena/<int:appointment_id>/', views.dejar_resena, name='dejar_resena'),

    # --- 6. ADMINISTRACIÓN WEB (Para tu jefe) ---
    # AQUÍ ESTABA EL ERROR: Cambié name='panel_admin' por 'panel_administracion'
    path('panel-jefe/', views.panel_admin, name='panel_administracion'),
    
    path('aprobar/<int:asesor_id>/', views.aprobar_asesor, name='aprobar_asesor'),
    path('rechazar/<int:asesor_id>/', views.rechazar_asesor, name='rechazar_asesor'),
    path('jefe/editar-precio/<int:asesor_id>/', views.admin_editar_precio, name='admin_editar_precio'),
    path('jefe/dashboard/', views.dashboard_financiero, name='dashboard_financiero'),
    
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

# Configuración para servir archivos multimedia (CVs, Fotos) en modo DEBUG
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)