import random
import mercadopago
import json
import time
from decimal import Decimal
from datetime import datetime, date, timedelta
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.conf import settings
from django.utils import timezone 
from django.utils.timezone import now, localtime
from django.contrib import messages
from django.core.mail import send_mail
from django.db.models import Q, Sum, Count
from django.core.files.storage import FileSystemStorage

from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required

from .models import AsesorProfile, Availability, Appointment, User, Review, Vacation, ChatMessage, SoporteUsuario
from .forms import RegistroUnificadoForm, PerfilAsesorForm, ReviewForm

def lista_asesores(request):
    # 1. Empezamos con TODOS los asesores aprobados
    asesores = AsesorProfile.objects.filter(is_approved=True)

    # 2. Capturamos lo que el usuario escribió en el buscador (si escribió algo)
    query = request.GET.get('q')      # 'q' será el nombre del cuadrito de texto
    precio_max = request.GET.get('precio') # 'precio' será el filtro de dinero

    # 3. FILTRO DE TEXTO (Nombre O Título)
    if query:
        asesores = asesores.filter(
            Q(public_title__icontains=query) |       # Busca en el título (ej: "Experto Python")
            Q(user__first_name__icontains=query) |   # O busca en el nombre (ej: "Mateo")
            Q(user__last_name__icontains=query)      # O busca en el apellido
        )

    # 4. FILTRO DE PRECIO (Menor o igual a...)
    if precio_max:
        try:
            asesores = asesores.filter(hourly_rate__lte=precio_max) # lte = Less Than or Equal
        except ValueError:
            pass # Si el usuario escribe texto en el precio, lo ignoramos

    # 5. Renderizamos
    return render(request, 'core/lista_asesores.html', {
        'asesores': asesores,
        'query_actual': query, # Pasamos esto para que el buscador no se borre al buscar
    })

@login_required
def detalle_asesor(request, asesor_id):
    asesor = get_object_or_404(AsesorProfile, id=asesor_id)
    
    # 1. DEFINIR EL RANGO (AHORA 60 DÍAS PARA EL CLIENTE) 📅
    hoy = date.today()
    limite_cliente = hoy + timedelta(days=60) # <-- CAMBIO AQUÍ: de 30 a 60
    
    # 2. BUSCAR HORARIOS
    horarios_disponibles = Availability.objects.filter(
        asesor=asesor,
        date__gte=hoy,
        date__lte=limite_cliente, # Usamos el nuevo límite
        is_booked=False
    ).order_by('date', 'start_time')

    # 2. DICCIONARIOS DE TRADUCCIÓN
    dias_esp = {
        'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
        'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
    }
    meses_esp = {
        'January': 'Enero', 'February': 'Febrero', 'March': 'Marzo', 'April': 'Abril',
        'May': 'Mayo', 'June': 'Junio', 'July': 'Julio', 'August': 'Agosto',
        'September': 'Septiembre', 'October': 'Octubre', 'November': 'Noviembre', 'December': 'Diciembre'
    }

    # 3. AGRUPAR POR DÍA (Agenda Visual)
    agenda = {}
    for horario in horarios_disponibles:
        # Combinamos fecha y hora para poder usar strftime
        dt_combinado = datetime.combine(horario.date, horario.start_time)

        # Extraer datos en inglés
        dia_ing = dt_combinado.strftime("%A")
        mes_ing = dt_combinado.strftime("%B")
        dia_num = dt_combinado.strftime("%d")

        # Traducir al español (Ej: "Lunes 23 de Enero")
        fecha_texto = f"{dias_esp[dia_ing]} {dia_num} de {meses_esp[mes_ing]}"

        if fecha_texto not in agenda:
            agenda[fecha_texto] = []
        # Agregamos el bloque de horario a la lista de ese día
        agenda[fecha_texto].append(horario)

    return render(request, 'core/detalle_asesor.html', {
        'asesor': asesor,
        'agenda': agenda, # Enviamos la agenda ordenada
    })

@login_required
def reservar_hora(request, cita_id):
    # 'cita_id' es el ID del Availability (Horario)
    try:
        horario = get_object_or_404(Availability, id=cita_id)

        # 1. Seguridad
        if horario.is_booked:
            messages.error(request, "Esa hora ya fue tomada.")
            return redirect('detalle_asesor', asesor_id=horario.asesor.id)

        # 2. Crear Cita
        start_dt = datetime.combine(horario.date, horario.start_time)
        end_dt = datetime.combine(horario.date, horario.end_time)
        
        # Hacemos la fecha "consciente" de la zona horaria (Chile)
        if timezone.is_naive(start_dt):
            start_dt = timezone.make_aware(start_dt)
        if timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt)

        nueva_cita = Appointment.objects.create(
            client=request.user,
            asesor=horario.asesor,
            start_datetime=start_dt,
            end_datetime=end_dt,
            status='POR_PAGAR'
        )

        # 3. Bloquear Horario
        horario.is_booked = True
        horario.save()

        print(f"✅ Cita creada ID: {nueva_cita.id}. Redirigiendo a checkout...")

        # 4. REDIRECCIÓN (Aquí solía fallar)
        # Usamos 'args' en lugar de kwargs para ser más robustos
        return redirect('checkout', reserva_id=nueva_cita.id)

    except Exception as e:
        print(f"❌ CRITICAL ERROR EN RESERVAR: {e}")
        # Si falla, intentamos devolver al usuario al perfil del asesor
        messages.error(request, "Ocurrió un error creando la reserva. Intenta de nuevo.")
        return redirect('inicio')

# Vista simple para la "Caja" (La haremos bonita después)
@login_required
def checkout(request, reserva_id):
    # Buscamos la reserva
    reserva = get_object_or_404(Appointment, id=reserva_id, client=request.user)
    
    if request.method == 'POST':
        # --- 1. CAPTURAR Y GUARDAR DATOS SEGÚN TIPO ---
        tipo_doc = request.POST.get('tipo_documento') # 'BOLETA' o 'FACTURA'
        
        reserva.tipo_documento = tipo_doc
        reserva.rut_facturacion = request.POST.get('rut')
        reserva.telefono_facturacion = request.POST.get('telefono')
        reserva.email_facturacion = request.POST.get('email')
        
        # Dirección Fiscal Común
        reserva.client_address = request.POST.get('direccion')
        reserva.client_city = request.POST.get('ciudad')
        reserva.comuna_facturacion = request.POST.get('comuna') # Nuevo campo

        if tipo_doc == 'BOLETA':
             # En boleta usamos el nombre personal
            reserva.nombre_facturacion = request.POST.get('nombre_boleta')
        else:
            # En factura usamos la Razón Social y el Giro
            reserva.nombre_facturacion = request.POST.get('razon_social')
            reserva.giro_facturacion = request.POST.get('giro')

        reserva.save() # ¡Guardamos todo!
        
        # --- 2. INTEGRACIÓN MERCADO PAGO (IGUAL QUE ANTES) ---
        sdk = mercadopago.SDK(settings.MERCADO_PAGO_TOKEN)
        
        preference_data = {
            "items": [
                {
                    "title": f"Asesoría con {reserva.asesor.user.first_name}",
                    "quantity": 1,
                    "unit_price": float(reserva.asesor.hourly_rate),
                }
            ],
            "payer": {
                "email": reserva.email_facturacion or request.user.email,
                "name": reserva.nombre_facturacion
            },
            "external_reference": str(reserva.id), 
            "back_urls": {
                "success": request.build_absolute_uri(reverse('pago_exitoso', args=[reserva.id])),
                "failure": request.build_absolute_uri(reverse('pago_fallido')),
                "pending": request.build_absolute_uri(reverse('pago_fallido'))
            },
            "auto_return": "approved",
        }

        try:
            preference_response = sdk.preference().create(preference_data)
            if "response" in preference_response and "init_point" in preference_response["response"]:
                url_pago = preference_response["response"]["init_point"]
                return redirect(url_pago)
            else:
                return render(request, 'core/error.html', {'mensaje': 'Error MP.'})
        except Exception as e:
            return render(request, 'core/error.html', {'mensaje': str(e)})

    return render(request, 'core/checkout.html', {'reserva': reserva})

@login_required
def pago_exitoso(request, reserva_id):
    # 1. Buscamos la reserva
    reserva = get_object_or_404(Appointment, id=reserva_id)
    
    # 2. CAPTURAR STATUS DE MERCADO PAGO (Para seguridad extra)
    status_pago = request.GET.get('status')
    
    # 3. VERIFICAMOS SI DEBEMOS CONFIRMAR
    # (Si MP dice 'approved' O si ya estaba 'CONFIRMADA' por si el usuario recarga la página)
    if status_pago == 'approved' or reserva.status == 'CONFIRMADA':
        
        # Solo procesamos si NO estaba confirmada previamente (para no mandar doble correo)
        if reserva.status != 'CONFIRMADA':
            
            # A) Actualizamos estado
            reserva.status = 'CONFIRMADA'
            reserva.save()
            
            # B) Preparamos datos bonitos (Hora local y Link)
            fecha_local = timezone.localtime(reserva.start_datetime)
            link_reunion = reserva.asesor.meeting_link
            if not link_reunion:
                link_reunion = "El asesor te enviará el enlace pronto."

            # C) CORREO 1: AL CLIENTE (Con el Link)
            asunto_cliente = f"✅ Reserva Confirmada con {reserva.asesor.user.first_name}"
            mensaje_cliente = f"""
            Hola {reserva.client.first_name},

            ¡Todo listo! Tu cita ha sido pagada y agendada.

            ----------------------------------------
            📅 Fecha: {fecha_local.strftime("%d/%m/%Y")}
            ⏰ Hora: {fecha_local.strftime("%H:%M")} hrs
            
            🔗 ENLACE DE VIDEOLLAMADA:
            {link_reunion}
            ----------------------------------------

            ¡Te esperamos!
            """

            # D) CORREO 2: AL ASESOR (Aviso de venta)
            asunto_asesor = "💰 ¡Nueva Venta! Tienes una nueva reserva"
            mensaje_asesor = f"""
            Hola {reserva.asesor.user.first_name},
            
            ¡Buenas noticias! {reserva.client.first_name} {reserva.client.last_name} ha reservado contigo.
            
            📅 Fecha: {fecha_local.strftime("%d/%m/%Y")}
            ⏰ Hora: {fecha_local.strftime("%H:%M")}
            👤 Cliente: {reserva.client.email}
            
            Por favor asegúrate de estar puntual.
            """

            # E) ENVIAR LOS CORREOS
            try:
                # Correo al Cliente
                send_mail(
                    asunto_cliente, 
                    mensaje_cliente, 
                    settings.EMAIL_HOST_USER, 
                    [reserva.client.email], 
                    fail_silently=False
                )
                
                # Correo al Asesor
                send_mail(
                    asunto_asesor, 
                    mensaje_asesor, 
                    settings.EMAIL_HOST_USER, 
                    [reserva.asesor.user.email], 
                    fail_silently=False
                )
                print("📧 Correos enviados exitosamente.")
            except Exception as e:
                print(f"⚠️ Error enviando correos: {e}")

        # 4. REDIRECCIÓN FINAL
        messages.success(request, f"¡Pago exitoso! Tu cita está confirmada.")
        return redirect('mis_reservas')

    else:
        # Si el pago falló o está pendiente
        return render(request, 'core/error.html', {'mensaje': 'El pago no fue procesado correctamente.'})

@login_required
def mis_reservas(request):
    # Traer reservas
    reservas = Appointment.objects.filter(client=request.user).order_by('-start_datetime')
    
    ahora = timezone.now()

    for cita in reservas:
        # 1. INICIALIZAR VARIABLES (Por defecto todo apagado para evitar errores)
        cita.mostrar_video = False
        cita.puede_cambiar = False
        cita.puede_reembolsar = False
        cita.horas_restantes = -9999 # Valor negativo por defecto

        # 2. SOLO CALCULAMOS SI LA CITA TIENE FECHA REAL
        if cita.start_datetime:
            # A) Calcular tiempo restante
            diferencia = cita.start_datetime - ahora
            cita.horas_restantes = diferencia.total_seconds() / 3600

            # B) Regla de Videollamada (Aparece 15 min antes, desaparece 1 hora después)
            inicio_video = cita.start_datetime - timedelta(minutes=15)
            fin_video = cita.start_datetime + timedelta(hours=1)
            
            if (inicio_video <= ahora <= fin_video) and cita.status == 'CONFIRMADA':
                cita.mostrar_video = True

            # C) Regla de Reagendar (Solo si faltan más de 48 horas)
            if cita.horas_restantes >= 48 and cita.status == 'CONFIRMADA':
                cita.puede_cambiar = True
            
            # D) Regla de Reembolso (Solo si faltan más de 72 horas)
            if cita.horas_restantes >= 72 and cita.status == 'CONFIRMADA':
                cita.puede_reembolsar = True

    return render(request, 'core/mis_reservas.html', {'reservas': reservas})

@login_required
def panel_asesor(request):
    # 1. DETECCIÓN INTELIGENTE DEL PERFIL
    if hasattr(request.user, 'asesorprofile'):
        asesor = request.user.asesorprofile
    elif hasattr(request.user, 'asesor_profile'):
        asesor = request.user.asesor_profile
    else:
        return redirect('solicitud_asesor')

    # 2. EL PORTERO
    if not asesor.is_approved:
        return render(request, 'core/espera_aprobacion.html')

    # 3. DATOS DE VENTAS
    try:
        ventas = Appointment.objects.filter(asesor=asesor, status='CONFIRMADA').order_by('start_datetime')
    except:
        ventas = []

    # 4. CÁLCULO DE INGRESOS (CORREGIDO ✅)
    try:
        resultado = Appointment.objects.filter(asesor=asesor, status='completed').aggregate(Sum('asesor__hourly_rate'))
        ingresos = resultado['asesor__hourly_rate__sum'] or 0
    except Exception as e:
        print(f"Error calculando ingresos: {e}")
        ingresos = 0

    # 5. EL FORMULARIO
    try:
        form = PerfilAsesorForm(instance=asesor)
    except:
        form = None

    # 6. CHAT BIDIRECCIONAL (Soporte con Admin) 💬
    # Cargamos el historial completo (lo que envié yo Y lo que recibí)
    try:
        mensajes_chat = ChatMessage.objects.filter(
            Q(sender=request.user) | Q(recipient=request.user)
        ).order_by('fecha')
        
        # Contamos cuántos mensajes NO he leído todavía para el globito rojo
        not_read_count = ChatMessage.objects.filter(recipient=request.user, leido=False).count()
    except Exception as e:
        print(f"Error cargando chat: {e}")
        mensajes_chat = []
        not_read_count = 0

    context = {
        'asesor': asesor,
        'ventas': ventas,      
        'ingresos': ingresos,
        'form': form,
        'mensajes_chat': mensajes_chat, # <--- Enviamos la conversación al HTML
        'not_read_count': not_read_count # <--- Enviamos el contador de notificaciones
    }
    return render(request, 'core/panel_asesor.html', context)

# --- PANEL DE JEFE (ADMINISTRACIÓN) ---
@login_required
def panel_admin(request):
    # 1. SEGURIDAD: Solo el Jefe entra
    if not request.user.is_superuser:
        messages.error(request, "Acceso denegado.")
        return redirect('inicio')

    # 2. FILTRADO
    solicitudes = AsesorProfile.objects.filter(is_approved=False)
    asesores_activos = AsesorProfile.objects.filter(is_approved=True)

    try:
        reclamos = Appointment.objects.filter(estado_reclamo='PENDIENTE')
    except:
        try:
            reclamos = Appointment.objects.filter(status='disputed')
        except:
            reclamos = []

    # 3. ESTADÍSTICAS
    total_asesores = AsesorProfile.objects.count()
    total_usuarios = User.objects.count()
    pendientes_count = solicitudes.count()

    # --- NUEVO: CONTAR MENSAJES SIN LEER PARA EL JEFE ---
    mensajes_sin_leer = ChatMessage.objects.filter(recipient=request.user, leido=False).count()

    # --- NUEVO: TRAER MENSAJES DE SOPORTE (FELICITACIONES, SUGERENCIAS, ETC) ---
    mensajes_soporte = SoporteUsuario.objects.all().order_by('-fecha_envio')

    context = {
        'solicitudes': solicitudes,
        'asesores': asesores_activos,
        'reclamos': reclamos,
        'total_asesores': total_asesores,
        'total_usuarios': total_usuarios,
        'pendientes_count': pendientes_count,
        'mensajes_sin_leer': mensajes_sin_leer, 
        'mensajes_soporte': mensajes_soporte, # <--- Agregado aquí
    }
    
    return render(request, 'core/panel_admin.html', context)

# 2. EL BOTÓN DE APROBAR (Acción)
@login_required
@staff_member_required
def aprobar_asesor(request, asesor_id):
    perfil = get_object_or_404(AsesorProfile, id=asesor_id)
    perfil.is_approved = True
    perfil.save()
    return redirect('panel_administracion') # Volvemos al panel tras aprobar

# 3. EL BOTÓN DE RECHAZAR/ELIMINAR (Acción)
@login_required
@staff_member_required
def rechazar_asesor(request, asesor_id):
    perfil = get_object_or_404(AsesorProfile, id=asesor_id)
    # Opcional: Podríamos borrar el usuario entero, o solo dejarlo desaprobado.
    # Por ahora, lo borramos para limpiar la base de datos.
    user = perfil.user
    user.delete() # Esto borra al usuario y al perfil en cascada
    return redirect('panel_administracion')

def registro_unificado(request):
    if request.method == 'POST':
        form = RegistroUnificadoForm(request.POST)
        if form.is_valid():
            # 1. Crear el usuario
            user = form.save()
            
            # 2. AUTO-LOGIN (Versión Blindada)
            try:
                # Especificamos el backend explícitamente para evitar conflictos
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                print(f"✅ Auto-login exitoso para: {user.email}")
            except Exception as e:
                print(f"❌ Error en auto-login: {e}")
                # Si falla el auto-login, al menos lo mandamos al login manual
                messages.success(request, "Cuenta creada. Por favor inicia sesión.")
                return redirect('login')

            # 3. Redirección Inteligente
            messages.success(request, f"¡Bienvenido/a {user.first_name}!")
            
            # Si venía de intentar reservar, lo devolvemos ahí
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            
            # Si no, al Lobby o Inicio
            return redirect('inicio')
        else:
            messages.error(request, "Error en el registro. Revisa los datos.")
    else:
        form = RegistroUnificadoForm()
    
    return render(request, 'core/registro_unificado.html', {'form': form})

# 2. PANTALLA DE VERIFICACIÓN (Poner el código)
def verificar_email(request):
    if request.method == 'POST':
        codigo_ingresado = request.POST.get('codigo')
        user_id = request.session.get('user_id_verify')
        
        user = get_object_or_404(User, id=user_id)
        
        if user.verification_code == codigo_ingresado:
            # ¡CÓDIGO CORRECTO!
            user.is_verified = True
            user.is_active = True # Ahora sí puede entrar
            user.save()
            
            login(request, user) # Lo logueamos automáticamente
            return redirect('lobby') # <--- LO MANDAREMOS AL NUEVO LOBBY
        else:
            return render(request, 'core/verificar_email.html', {'error': 'Código incorrecto', 'email': user.email})

    return render(request, 'core/verificar_email.html')

# 3. EL LOBBY (Donde elige si ser Cliente o Asesor)

@login_required
def lobby(request):
    # 1. SI ES EL JEFE -> AL PANEL ADMIN
    if request.user.is_superuser:
        return redirect('panel_administracion')

    # 2. VERIFICAR SI ES ASESOR (Forma 100% Segura)
    # Buscamos si existe un perfil asociado a este usuario
    es_asesor = AsesorProfile.objects.filter(user=request.user).exists()

    # 3. Mandamos esa información al HTML
    return render(request, 'core/lobby.html', {'es_asesor': es_asesor})

@login_required
def solicitud_asesor(request):
    # --- PASO 1: VERIFICACIÓN SEGURA ---
    # Preguntamos si el usuario ya tiene el atributo 'asesorprofile'
    if hasattr(request.user, 'asesorprofile'):
        # Si YA TIENE perfil, no tiene nada que hacer aquí. ¡Al panel!
        return redirect('panel_asesor')
    
    # Si NO tiene perfil, el código sigue hacia abajo (y mostramos el formulario)

    # --- PASO 2: EL FORMULARIO ---
    if request.method == 'POST':
        # Nota: Asegúrate de que tu PerfilAsesorForm en forms.py tenga los campos correctos
        form = PerfilAsesorForm(request.POST, request.FILES)
        
        if form.is_valid():
            perfil = form.save(commit=False)
            perfil.user = request.user
            # Le ponemos un precio inicial de 0 para evitar errores si no lo definen
            if not perfil.hourly_rate:
                perfil.hourly_rate = 0
            perfil.save()
            
            # ¡Éxito! Ahora sí tiene perfil, lo mandamos al panel
            return redirect('panel_asesor')
    else:
        form = PerfilAsesorForm()

    return render(request, 'core/solicitud_asesor.html', {'form': form})

@login_required
def gestionar_horarios(request):
    # 1. VERIFICACIÓN DE PERFIL
    if hasattr(request.user, 'asesorprofile'):
        asesor = request.user.asesorprofile
    elif hasattr(request.user, 'asesor_profile'):
        asesor = request.user.asesor_profile
    else:
        messages.warning(request, "Crea tu perfil primero.")
        return redirect('solicitud_asesor')
        
    hoy = date.today()
    limite_60_dias = hoy + timedelta(days=60)

    # --- 🤖 AUTOMATIZACIÓN (CORREGIDO: Solo se ejecuta si NO estamos enviando datos) ---
    if request.method == 'GET': # <--- ¡ESTE ES EL CAMBIO CLAVE!
        if asesor.auto_schedule and asesor.active_days and asesor.active_hours:
            dias_guardados = [int(d) for d in asesor.active_days.split(',') if d]
            horas_guardadas = asesor.active_hours.split(',')
            duracion = asesor.session_duration
            
            ultima_disponibilidad = Availability.objects.filter(asesor=asesor).order_by('-date').first()
            
            if ultima_disponibilidad:
                fecha_inicio_auto = ultima_disponibilidad.date + timedelta(days=1)
            else:
                fecha_inicio_auto = hoy

            # Si falta agenda para llegar a los 60 días, rellenamos
            if fecha_inicio_auto <= limite_60_dias:
                fecha_actual = fecha_inicio_auto
                nuevos_bloques = 0
                
                while fecha_actual <= limite_60_dias:
                    if fecha_actual.weekday() in dias_guardados:
                        for hora_str in horas_guardadas:
                            hora_obj = datetime.strptime(hora_str, "%H:%M").time()
                            start_dt = datetime.combine(fecha_actual, hora_obj)
                            end_dt = start_dt + timedelta(minutes=duracion)
                            
                            if not Availability.objects.filter(asesor=asesor, date=fecha_actual, start_time=hora_obj).exists():
                                Availability.objects.create(
                                    asesor=asesor, date=fecha_actual, start_time=hora_obj, end_time=end_dt.time()
                                )
                                nuevos_bloques += 1
                    fecha_actual += timedelta(days=1)
                
                if nuevos_bloques > 0:
                    messages.info(request, f"🔄 Agenda actualizada automáticamente: Se agregaron {nuevos_bloques} bloques nuevos.")


    # --- PROCESAR FORMULARIO MANUAL (POST) ---
    if request.method == 'POST':
        fecha_inicio_str = request.POST.get('fecha_inicio')
        fecha_fin_str = request.POST.get('fecha_fin')
        es_indefinido = request.POST.get('indefinido') == 'on'
        
        dias_elegidos = request.POST.getlist('dias[]')
        horas_elegidas = request.POST.getlist('horas[]')

        if not fecha_inicio_str or not dias_elegidos or not horas_elegidas:
             messages.error(request, "Faltan datos (Fecha inicio, días u horas).")
             return redirect('gestionar_horarios')

        try:
            fecha_inicio_dt = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()
            if fecha_inicio_dt < hoy:
                 messages.error(request, "No puedes usar fechas pasadas.")
                 return redirect('gestionar_horarios')

            # GUARDAR PREFERENCIA
            if es_indefinido:
                asesor.auto_schedule = True
                asesor.active_days = ",".join(dias_elegidos)
                asesor.active_hours = ",".join(horas_elegidas)
                asesor.save()
                
                fecha_fin_dt = fecha_inicio_dt + timedelta(days=60)
                messages.success(request, "✅ Modo Indefinido ACTIVADO. Agenda configurada por 60 días desde la fecha elegida.")
            else:
                asesor.auto_schedule = False
                asesor.save()
                
                if not fecha_fin_str:
                     messages.error(request, "Si no es indefinido, elige fecha de fin.")
                     return redirect('gestionar_horarios')
                fecha_fin_dt = datetime.strptime(fecha_fin_str, "%Y-%m-%d").date()

            if fecha_fin_dt < fecha_inicio_dt:
                 messages.error(request, "Fecha fin errónea.")
                 return redirect('gestionar_horarios')

            # GENERACIÓN
            duracion = asesor.session_duration
            fecha_actual = fecha_inicio_dt # <--- AHORA SÍ RESPETARÁ ESTA FECHA
            creados = 0
            dias_ints = [int(d) for d in dias_elegidos]

            while fecha_actual <= fecha_fin_dt:
                if fecha_actual.weekday() in dias_ints:
                    for hora_str in horas_elegidas:
                        hora_obj = datetime.strptime(hora_str, "%H:%M").time()
                        start_dt = datetime.combine(fecha_actual, hora_obj)
                        end_dt = start_dt + timedelta(minutes=duracion)
                        
                        if not Availability.objects.filter(asesor=asesor, date=fecha_actual, start_time=hora_obj).exists():
                            Availability.objects.create(
                                asesor=asesor, date=fecha_actual, start_time=hora_obj, end_time=end_dt.time()
                            )
                            creados += 1
                fecha_actual += timedelta(days=1)

            if creados > 0:
                messages.success(request, f"Se crearon {creados} bloques nuevos desde el {fecha_inicio_str}.")
            else:
                messages.warning(request, "No se crearon bloques (quizás ya existían).")

        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

        return redirect('gestionar_horarios')

    # --- VISTA GET ---
    bloques = Availability.objects.filter(
        asesor=asesor,
        date__gte=hoy,
        date__lte=limite_60_dias,
        is_booked=False
    ).order_by('date', 'start_time')
    
    lista_horas = [f"{h:02d}:00" for h in range(24)]

    return render(request, 'core/gestionar_horarios.html', {
        'bloques': bloques,
        'hoy': hoy.strftime("%Y-%m-%d"),
        'lista_horas': lista_horas,
        'asesor': asesor
    })

@login_required
def registrar_vacaciones(request):
    if request.method == 'POST':
        inicio_str = request.POST.get('vacaciones_inicio')
        fin_str = request.POST.get('vacaciones_fin')
        
        # Verificación segura del perfil
        if hasattr(request.user, 'asesorprofile'):
            asesor = request.user.asesorprofile
        elif hasattr(request.user, 'asesor_profile'):
            asesor = request.user.asesor_profile
        else:
            return redirect('inicio')

        if inicio_str and fin_str:
            inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            fin = datetime.strptime(fin_str, '%Y-%m-%d').date()
            
            # 1. BORRAR horarios libres en ese rango
            Availability.objects.filter(asesor=asesor, date__range=[inicio, fin], is_booked=False).delete()
            
            # 2. CANCELAR CITAS CONFIRMADAS y AVISAR
            citas_afectadas = Appointment.objects.filter(
                asesor=asesor, 
                start_datetime__date__range=[inicio, fin],
                status='CONFIRMADA'
            )
            
            canceladas = 0
            email_origen = settings.DEFAULT_FROM_EMAIL
            
            for cita in citas_afectadas:
                cita.status = 'CANCELADA'
                cita.save()
                canceladas += 1
                
                # Correo al cliente
                try:
                    asunto = f"⚠️ Cita Cancelada: {asesor.user.first_name} estará ausente"
                    mensaje = f"""
                    Hola {cita.client.first_name},
                    
                    Lamentamos informarte que tu cita programada para el {cita.start_datetime.strftime('%d/%m/%Y')} ha sido cancelada.
                    El motivo es que el asesor estará fuera por vacaciones o motivos personales en esas fechas.
                    
                    Por favor contáctanos para reagendar o solicitar reembolso.
                    """
                    send_mail(asunto, mensaje, email_origen, [cita.client.email], fail_silently=True)
                except:
                    pass

            messages.warning(request, f"🌴 Vacaciones activadas. Se eliminaron horarios y se cancelaron {canceladas} citas (clientes notificados).")
            
    return redirect('gestionar_horarios')

# Extra: Función para BORRAR un horario (si se equivocó)
@login_required
def borrar_horario(request, horario_id):
    horario = get_object_or_404(Availability, id=horario_id)
    # Seguridad: Solo el dueño puede borrarlo
    if horario.asesor.user == request.user:
        horario.delete()
        messages.success(request, "Horario eliminado correctamente.")
    return redirect('gestionar_horarios')

@user_passes_test(lambda u: u.is_superuser)
def admin_editar_precio(request, asesor_id):
    asesor = get_object_or_404(AsesorProfile, id=asesor_id)
    
    if request.method == 'POST':
        nuevo_precio = request.POST.get('nuevo_precio')
        if nuevo_precio:
            asesor.hourly_rate = nuevo_precio
            asesor.save()
            # Volvemos al panel de administración
            return redirect('panel_administracion') 
            
    # Si entra por GET, le mostramos el formulario chiquitito
    return render(request, 'core/admin_editar_precio.html', {'asesor': asesor})
    
@login_required
def dejar_resena(request, appointment_id):
    cita = get_object_or_404(Appointment, id=appointment_id, client=request.user)
    
    # Seguridad: Solo se puede reseñar si la cita ya pasó y está confirmada
    # (Aquí podrías agregar validación de fecha si quisieras ser estricto)
    
    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            resena = form.save(commit=False)
            resena.asesor = cita.asesor
            resena.client = request.user
            resena.appointment = cita
            resena.save()
            return redirect('mis_reservas')
    else:
        form = ReviewForm()

    return render(request, 'core/dejar_resena.html', {'form': form, 'cita': cita})

def perfil_publico(request, asesor_id):
    asesor = get_object_or_404(AsesorProfile, id=asesor_id)
    return render(request, 'core/perfil_publico.html', {'asesor': asesor})

@login_required
def editar_perfil_asesor(request):
    perfil = get_object_or_404(AsesorProfile, user=request.user)

    if request.method == 'POST':
        # USAMOS EL NOMBRE BUENO AHORA 👇
        form = PerfilAsesorForm(request.POST, request.FILES, instance=perfil) 
        if form.is_valid():
            form.save()
            messages.success(request, '¡Tu perfil ha sido actualizado!')
            return redirect('panel_asesor')
    else:
        # USAMOS EL NOMBRE BUENO AHORA 👇
        form = PerfilAsesorForm(instance=perfil)

    return render(request, 'core/panel_asesor.html', {'form': form})

def obtener_ip_cliente(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

@login_required
def anular_reserva(request, reserva_id):
    reserva = get_object_or_404(Appointment, id=reserva_id, client=request.user)
    
    if reserva.start_datetime < timezone.now():
        messages.error(request, "No puedes anular una reunión que ya pasó.")
        return redirect('mis_reservas')

    # --- CORRECCIÓN IMPORTANTE: Convertir a hora local ---
    fecha_hora_local = timezone.localtime(reserva.start_datetime)

    horario = Availability.objects.filter(
        asesor=reserva.asesor,
        date=fecha_hora_local.date(),       # Busca la fecha local
        start_time=fecha_hora_local.time()  # Busca la hora local
    ).first()
    
    if horario:
        horario.is_booked = False 
        horario.save()
    
    reserva.delete()
    
    messages.success(request, "Tu reserva ha sido anulada y el horario liberado.")
    return redirect('mis_reservas')


@login_required
@staff_member_required
def dashboard_financiero(request):
    # 1. Configuración de Fecha
    hoy = timezone.now()
    
    # Filtros: Si no elige nada, mostramos 2026 (para que veas tu venta de prueba)
    # o el año actual si prefieres 'hoy.year'
    anio_por_defecto = 2026 
    
    mes_seleccionado = int(request.GET.get('mes', hoy.month))
    anio_seleccionado = int(request.GET.get('anio', anio_por_defecto))

    # 2. Rango de Años (2026 al 2050)
    anios = list(range(2026, 2051))

    # 3. Consulta Base: Solo citas CONFIRMADAS (Pagadas)
    ventas_historicas = Appointment.objects.filter(status='CONFIRMADA')
    
    # 4. Totales Históricos (Tarjeta Verde)
    ingresos_totales = ventas_historicas.aggregate(Sum('asesor__hourly_rate'))['asesor__hourly_rate__sum'] or 0
    ventas_totales = ventas_historicas.count()
    
    # 5. Totales del Mes Elegido (Tarjeta Azul)
    ventas_del_mes = ventas_historicas.filter(
        start_datetime__year=anio_seleccionado, 
        start_datetime__month=mes_seleccionado
    )
    
    total_ingresos = ventas_del_mes.aggregate(Sum('asesor__hourly_rate'))['asesor__hourly_rate__sum'] or 0
    cantidad_ventas = ventas_del_mes.count()

    # 6. Ranking de Asesores (CORREGIDO 🛠️)
    # Usamos 'asesor_appointments' que es como se llama en tu sistema
    try:
        top_asesores = AsesorProfile.objects.annotate(
            total_ventas=Count('asesor_appointments', filter=Q(asesor_appointments__status='CONFIRMADA'))
        ).order_by('-total_ventas')[:5]
    except:
        # Si falla por nombre, intentamos con el genérico 'appointment_set'
        top_asesores = AsesorProfile.objects.annotate(
            total_ventas=Count('appointment', filter=Q(appointment__status='CONFIRMADA'))
        ).order_by('-total_ventas')[:5]

    # 7. Lista bonita de meses
    nombres_meses = [
        (1, "Enero"), (2, "Febrero"), (3, "Marzo"), (4, "Abril"),
        (5, "Mayo"), (6, "Junio"), (7, "Julio"), (8, "Agosto"),
        (9, "Septiembre"), (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre")
    ]
    
    nombre_mes_actual = nombres_meses[mes_seleccionado - 1][1]

    context = {
        'total_ingresos': total_ingresos,
        'cantidad_ventas': cantidad_ventas,
        'ingresos_totales': ingresos_totales,
        'ventas_totales': ventas_totales,
        'top_asesores': top_asesores,
        'mes_seleccionado': mes_seleccionado,
        'anio_seleccionado': anio_seleccionado,
        'nombre_mes_actual': nombre_mes_actual,
        'nombres_meses': nombres_meses,
        'anios': anios, # Esta variable debe coincidir con el HTML
    }
    return render(request, 'core/dashboard_financiero.html', context)

@login_required
def borrar_cuenta_confirmacion(request):
    if request.method == 'POST':
        password = request.POST.get('password')
        
        # 1. VERIFICAR CONTRASEÑA (Seguridad)
        if not request.user.check_password(password):
            messages.error(request, "La contraseña ingresada es incorrecta.")
            return redirect('borrar_cuenta_confirmacion')
            
        # 2. PROCESO DE "CIERRE Y LIBERACIÓN"
        user = request.user
        
        # Guardamos el email original por si queremos enviarle un correo de despedida (opcional)
        email_original = user.email 
        
        # A) Cambiamos el usuario y email para LIBERARLOS
        # Ponemos un prefijo con la fecha para que sean únicos y no estorben
        timestamp = int(time.time())
        user.username = f"cerrada_{timestamp}_{user.username}"
        user.email = f"cerrada_{timestamp}_{user.email}"
        
        # B) Desactivamos la cuenta (Ya no podrá entrar)
        user.is_active = False
        
        # C) Guardamos los cambios
        user.save()
        
        # D) Si es asesor, ocultamos su perfil del buscador
        if hasattr(user, 'asesorprofile'):
            perfil = user.asesorprofile
            perfil.is_approved = False # Lo quitamos de la lista pública
            perfil.save()
            
            # Opcional: Cancelar citas futuras automáticamente aquí si quisieras
            
        # 3. CERRAR SESIÓN Y REDIRIGIR
        logout(request)
        messages.success(request, "Tu cuenta ha sido cerrada correctamente. Tu correo ha sido liberado por si deseas volver a registrarte en el futuro.")
        return redirect('inicio')

    return render(request, 'core/borrar_cuenta.html')
@login_required
def solicitar_reembolso(request, reserva_id):
    cita = get_object_or_404(Appointment, id=reserva_id, client=request.user)
    
    if request.method == 'POST':
        motivo = request.POST.get('motivo')
        
        # Validar tiempo (Seguridad Backend - 72 Horas)
        diferencia = cita.start_datetime - timezone.now()
        horas_restantes = diferencia.total_seconds() / 3600
        
        if horas_restantes < 72:
            messages.error(request, "El plazo de reembolso (72h antes) ha expirado.")
            return redirect('mis_reservas')
            
        # Procesar Reclamo
        cita.reclamo_mensaje = motivo
        cita.estado_reclamo = 'PENDIENTE'
        cita.save()
        
        messages.info(request, "Solicitud de reembolso enviada (Multa del 15% aplicará).")
        return redirect('mis_reservas')
        
    return render(request, 'core/solicitar_reembolso.html', {'reserva': cita})

@staff_member_required
def resolver_reclamo(request, reserva_id, accion):
    reserva = get_object_or_404(Appointment, id=reserva_id)
    
    if accion == 'aprobar':
        reserva.estado_reclamo = 'APROBADO'
        reserva.status = 'REEMBOLSADO' # Cambiamos el estado general
        reserva.save()
        messages.success(request, f"Reembolso aprobado para la cita #{reserva.id}. (Recuerda devolver el dinero en Mercado Pago manualmente).")
        
        # Aquí podrías enviar correo al cliente avisando
        
    elif accion == 'rechazar':
        reserva.estado_reclamo = 'RECHAZADO'
        reserva.save()
        messages.warning(request, "El reclamo ha sido rechazado.")
    
    return redirect('panel_administracion')

# 1. ENVIAR OBSERVACIÓN (EMAIL)
@login_required
@staff_member_required
def admin_enviar_observacion(request, asesor_id):
    asesor = get_object_or_404(AsesorProfile, id=asesor_id)
    
    if request.method == 'POST':
        texto_mensaje = request.POST.get('mensaje')
        if texto_mensaje:
            # --- CORRECCIÓN: Usamos ChatMessage (el nuevo sistema) ---
            ChatMessage.objects.create(
                sender=request.user,       # El admin que envía (Tú)
                recipient=asesor.user,     # El asesor que recibe
                mensaje=texto_mensaje
            )
            messages.success(request, f"Mensaje enviado al chat de {asesor.user.first_name}.")
            return redirect('panel_administracion')

    return render(request, 'core/admin_enviar_observacion.html', {'asesor': asesor})

# 2. EDITAR DURACIÓN DE SESIÓN
@login_required
@staff_member_required
def admin_editar_duracion(request, asesor_id):
    asesor = get_object_or_404(AsesorProfile, id=asesor_id)
    
    if request.method == 'POST':
        nueva_duracion = request.POST.get('duracion') # Viene en minutos (30, 45, 60...)
        if nueva_duracion:
            asesor.session_duration = int(nueva_duracion)
            asesor.save()
            messages.success(request, f"Duración actualizada a {nueva_duracion} minutos para {asesor.user.first_name}.")
            return redirect('panel_administracion')
            
    return render(request, 'core/admin_editar_duracion.html', {'asesor': asesor})

# --- TRUCO PARA VOLVERSE JEFE (SOLO SI SE BORRÓ) ---
@login_required
def secreto_admin(request):
    # Damos superpoderes al usuario actual
    request.user.is_staff = True
    request.user.is_superuser = True
    request.user.save()
    
    # Creamos el perfil de Asesor automáticamente si no existe (para evitar errores)
    if not hasattr(request.user, 'asesor_profile'):
        AsesorProfile.objects.create(
            user=request.user,
            public_title="Administrador",
            experience_summary="Perfil administrativo",
            hourly_rate=0,
            session_duration=60
        )
        
    messages.success(request, "¡HACK: Ahora eres Administrador Supremo! 👑")
    return redirect('panel_administracion')

def pago_fallido(request):
    # Recuperamos el ID
    cita_id = request.GET.get('external_reference')
    
    if cita_id:
        try:
            cita = Appointment.objects.get(id=cita_id)
            
            # --- CORRECCIÓN DE ZONA HORARIA 🌍 ---
            # Convertimos la hora de la cita (UTC) a la hora local del servidor
            # para que coincida con el horario original (Availability)
            fecha_hora_local = timezone.localtime(cita.start_datetime)

            # Buscamos el bloque de horario usando la HORA LOCAL
            horario = Availability.objects.filter(
                asesor=cita.asesor,
                date=fecha_hora_local.date(),
                start_time=fecha_hora_local.time()
            ).first()
            
            if horario:
                horario.is_booked = False  # ¡LIBERADO! 🟢
                horario.save()
                print(f"✅ Horario recuperado y liberado: {fecha_hora_local}")
            else:
                print(f"⚠️ ALERTA: No se encontró el horario original para {fecha_hora_local}")

            # Borramos la cita
            cita.delete() 
            
            messages.warning(request, "El proceso de pago fue cancelado y el horario ha sido liberado.")
        except Appointment.DoesNotExist:
            pass
            
    return redirect('inicio')

@login_required
def asesor_enviar_mensaje(request):
    """Permite al asesor responder desde la burbuja"""
    if request.method == 'POST':
        mensaje = request.POST.get('mensaje')
        # Buscamos al admin (el primer superusuario)
        admin_user = User.objects.filter(is_superuser=True).first()
        
        if mensaje and admin_user:
            ChatMessage.objects.create(
                sender=request.user,
                recipient=admin_user,
                mensaje=mensaje
            )
            # No enviamos 'messages.success' para que no moleste la alerta verde, 
            # el mensaje aparecerá en el chat automáticamente.
        
    return redirect('panel_asesor')

@staff_member_required
def admin_chat_dashboard(request):
    """Vista del Centro de Mensajes para el Jefe"""
    # 1. Obtenemos todos los mensajes
    mensajes = ChatMessage.objects.all()
    
    # 2. Identificamos IDs únicos de usuarios (Asesores)
    ids_usuarios = set()
    for m in mensajes:
        if not m.sender.is_superuser: ids_usuarios.add(m.sender.id)
        if not m.recipient.is_superuser: ids_usuarios.add(m.recipient.id)
    
    asesores_objs = User.objects.filter(id__in=ids_usuarios)
    
    # 3. CONSTRUIMOS UNA LISTA INTELIGENTE
    # Para saber si hay no leídos por cada asesor
    lista_chats = []
    
    for asesor in asesores_objs:
        # Contamos mensajes que ÉL me envió a MÍ y que NO he leído
        no_leidos = ChatMessage.objects.filter(
            sender=asesor, 
            recipient=request.user, 
            leido=False
        ).count()
        
        # Guardamos el objeto y el contador
        lista_chats.append({
            'usuario': asesor,
            'no_leidos': no_leidos
        })
    
    # Ordenamos: Los que tienen mensajes no leídos primero
    lista_chats.sort(key=lambda x: x['no_leidos'], reverse=True)
    
    return render(request, 'core/admin_chat_list.html', {'lista_chats': lista_chats})

@staff_member_required
def admin_chat_detail(request, usuario_id):
    """Chat individual entre Jefe y un Asesor"""
    otro_usuario = get_object_or_404(User, id=usuario_id)
    
    # 1. GUARDAR MENSAJE DEL ADMIN (Si enviaste uno)
    if request.method == 'POST':
        texto = request.POST.get('mensaje')
        if texto:
            ChatMessage.objects.create(
                sender=request.user,
                recipient=otro_usuario,
                mensaje=texto
            )
            return redirect('admin_chat_detail', usuario_id=usuario_id)

    # 2. MARCAR COMO LEÍDOS AL ENTRAR
    ChatMessage.objects.filter(
        sender=otro_usuario, 
        recipient=request.user, 
        leido=False
    ).update(leido=True)

    # 3. CARGAR HISTORIAL (¡IMPORTANTE! Para que no salga en blanco)
    historial = ChatMessage.objects.filter(
        Q(sender=request.user, recipient=otro_usuario) | 
        Q(sender=otro_usuario, recipient=request.user)
    ).order_by('fecha')

    return render(request, 'core/admin_chat_detail.html', {
        'otro_usuario': otro_usuario,
        'historial': historial # Enviamos los mensajes para pintarlos de inmediato
    })
    
@login_required
def api_obtener_mensajes(request, usuario_id=None):
    """
    Devuelve los mensajes en formato JSON para que JavaScript los lea.
    Si es Asesor: Habla con el Admin (usuario_id=None).
    Si es Admin: Habla con el usuario_id especificado.
    """
    if request.user.is_superuser:
        otro_usuario = get_object_or_404(User, id=usuario_id)
    else:
        # Si soy asesor, mi interlocutor es el Admin
        otro_usuario = User.objects.filter(is_superuser=True).first()

    if not otro_usuario:
        return JsonResponse({'mensajes': []})

    # Buscar conversación
    mensajes = ChatMessage.objects.filter(
        Q(sender=request.user, recipient=otro_usuario) | 
        Q(sender=otro_usuario, recipient=request.user)
    ).order_by('fecha')

    lista_mensajes = []
    for m in mensajes:
        # 2. LA CORRECCIÓN MÁGICA: Convertimos UTC -> Hora Local (Chile)
        fecha_chilena = localtime(m.fecha) 

        lista_mensajes.append({
            'es_mio': m.sender == request.user,
            'mensaje': m.mensaje,
            # 3. Usamos la variable convertida, no la original
            'hora': fecha_chilena.strftime("%H:%M") 
        })

    return JsonResponse({'mensajes': lista_mensajes})

@login_required
def api_marcar_leido(request, usuario_id=None):
    """Marca los mensajes como leídos cuando abres la ventanita"""
    if request.method == 'POST':
        if request.user.is_superuser:
            otro_usuario = get_object_or_404(User, id=usuario_id)
        else:
            otro_usuario = User.objects.filter(is_superuser=True).first()
        
        # Marcar como leídos los que recibí de esa persona
        ChatMessage.objects.filter(sender=otro_usuario, recipient=request.user).update(leido=True)
        
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'})

@login_required
def solicitar_cambio_hora(request, reserva_id):
    cita = get_object_or_404(Appointment, id=reserva_id, client=request.user)
    
    if request.method == 'POST':
        motivo = request.POST.get('motivo_cambio')
        
        # Validar tiempo (Seguridad Backend)
        diferencia = cita.start_datetime - timezone.now()
        horas_restantes = diferencia.total_seconds() / 3600
        
        if horas_restantes < 48:
            messages.error(request, "Ya no es posible solicitar cambios (menos de 48h).")
            return redirect('mis_reservas')

        # Guardar Solicitud
        cita.solicitud_cambio = True
        cita.motivo_cambio = motivo
        cita.estado_solicitud = 'PENDIENTE'
        cita.save()
        
        messages.success(request, "Solicitud enviada. Si se aprueba, deberás pagar el 15% de recargo.")
        return redirect('mis_reservas')
    
    return redirect('mis_reservas')

@login_required
def enviar_soporte(request):
    if request.method == 'POST':
        # Recibir datos del formulario
        tipo = request.POST.get('tipo')
        nombre = request.POST.get('nombre')
        telefono = request.POST.get('telefono')
        email = request.POST.get('email')
        mensaje = request.POST.get('mensaje')
        archivo = request.FILES.get('archivo') # IMPORTANTE: Así se reciben archivos

        # Guardar en Base de Datos
        SoporteUsuario.objects.create(
            tipo=tipo,
            nombre=nombre,
            telefono=telefono,
            email=email,
            mensaje=mensaje,
            archivo=archivo
        )

        messages.success(request, "¡Mensaje enviado correctamente! El equipo lo revisará pronto.")
        return redirect('lobby') # O redirigir a donde prefieras

    # Si es GET (ver el formulario), pre-llenamos datos si el usuario tiene perfil
    context = {
        'nombre_user': request.user.first_name + ' ' + request.user.last_name,
        'email_user': request.user.email,
        'telefono_user': request.user.phone if hasattr(request.user, 'phone') else ''
    }
    return render(request, 'core/soporte_form.html', context)