import random  
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout 
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from datetime import timedelta, datetime, date
from django.contrib.admin.views.decorators import staff_member_required
from .models import AsesorProfile, Availability, Appointment, User, Review, Vacation
from .forms import RegistroUnificadoForm, PerfilAsesorForm
from .forms import ReviewForm
from django.db.models import Q
from django.db.models import Sum, Count
from django.core.mail import send_mail
from datetime import datetime, timedelta
from django.contrib import messages
from decimal import Decimal
import mercadopago
from django.urls import reverse
from django.conf import settings
from django.utils.timezone import now
from .models import AdminMessage  

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

# core/views.py

@login_required
def detalle_asesor(request, asesor_id):
    asesor = get_object_or_404(AsesorProfile, id=asesor_id)
    
    # 1. BUSCAMOS LOS HORARIOS DISPONIBLES (Availability)
    #  - Que sean de este asesor
    #  - Que sean de hoy en adelante (date >= today)
    #  - Que NO estén ya reservados (is_booked=False)
    horarios_disponibles = Availability.objects.filter(
        asesor=asesor,
        date__gte=date.today(), # Importante: usar date.today() para comparar fechas
        is_booked=False         # Solo los que están libres
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
    
# En core/views.py

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
        # --- 1. GUARDAR DATOS DEL CLIENTE ---
        reserva.client_address = request.POST.get('direccion')
        reserva.client_city = request.POST.get('ciudad')
        reserva.client_postal_code = request.POST.get('codigo_postal')
        reserva.save() # Guardamos los datos de dirección antes de ir a MP
        
        # --- 2. INTEGRACIÓN MERCADO PAGO ---
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
                "email": request.user.email
            },
            # --- CAMBIO 1: ETIQUETA DE RASTREO (IMPORTANTE) ---
            "external_reference": str(reserva.id), 

            "back_urls": {
                "success": request.build_absolute_uri(reverse('pago_exitoso', args=[reserva.id])),
                # --- CAMBIO 2: RUTAS DE ESCAPE ---
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
                return render(request, 'core/error.html', {'mensaje': 'Error de conexión con Mercado Pago.'})

        except Exception as e:
            return render(request, 'core/error.html', {'mensaje': f'Error técnico: {str(e)}'})

    return render(request, 'core/checkout.html', {'reserva': reserva})

@login_required
def pago_exitoso(request, reserva_id):
    # Buscamos la reserva
    reserva = get_object_or_404(Appointment, id=reserva_id)
    
    # 1. CAPTURAR STATUS DE MERCADO PAGO
    status_pago = request.GET.get('status') 
    
    # 2. VALIDACIÓN PRINCIPAL (Aprobado o ya estaba confirmada)
    if status_pago == 'approved' or reserva.status == 'CONFIRMADA':
        
        # CASO A: PRIMERA VEZ QUE ENTRA (CONFIRMAMOS TODO)
        if reserva.status == 'DISPONIBLE':
            
            # ¡BLOQUEAMOS LA HORA! 🔒
            reserva.status = 'CONFIRMADA'
            reserva.client = request.user
            reserva.save()
            
            # --- CORRECCIÓN DE HORA Y LINK ---
            fecha_local = timezone.localtime(reserva.start_datetime)
            link_reunion = reserva.asesor.meeting_link
            if not link_reunion or link_reunion == 'None':
                link_reunion = "El asesor te enviará el enlace pronto."

            # PREPARAR CORREOS
            asunto_cliente = "¡Reserva Confirmada!"
            mensaje_cliente = f"""
            Hola {request.user.first_name},
            Reserva confirmada para el {fecha_local.strftime("%d/%m/%Y")} a las {fecha_local.strftime("%H:%M")}.
            Link: {link_reunion}
            """
            
            asunto_asesor = "💰 ¡Nueva Venta! Tienes una reserva"
            mensaje_asesor = f"""
            Hola {reserva.asesor.user.first_name},
            ¡Buenas noticias! {request.user.first_name} {request.user.last_name} ha reservado una hora contigo.
            
            📅 Fecha: {fecha_local.strftime("%d/%m/%Y")}
            ⏰ Hora: {fecha_local.strftime("%H:%M")}
            👤 Cliente: {request.user.email}
            """

            # ENVIAR CORREOS CON RED DE SEGURIDAD 🛡️
            try:
                # Usamos settings.DEFAULT_FROM_EMAIL en lugar del correo fijo
                email_origen = settings.DEFAULT_FROM_EMAIL
                
                send_mail(asunto_cliente, mensaje_cliente, email_origen, [request.user.email], fail_silently=False)
                send_mail(asunto_asesor, mensaje_asesor, email_origen, [reserva.asesor.user.email], fail_silently=False)
            except Exception as e:
                # Si falla el correo, NO rompemos la página. Solo avisamos en consola.
                print(f"⚠️ Error enviando correos de confirmación: {e}")

        # CASO B: SI YA ESTABA CONFIRMADA (Reload), no hacemos nada extra.
        
        # FINAL: MOSTRAR PANTALLA DE ÉXITO
        return render(request, 'core/payment_success.html', {'appointment': reserva})

    # 3. SI EL PAGO FALLÓ
    else:
        return render(request, 'core/error.html', {'mensaje': 'El pago no fue aprobado o fue cancelado.'})

@login_required
def mis_reservas(request):
    # CORRECCIÓN: Ordenamos por 'start_datetime' (fecha de la reunión) 
    # porque 'created_at' a veces no existe en el modelo y causa Error 500.
    reservas = Appointment.objects.filter(client=request.user).order_by('-start_datetime')
    
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
    # Como Appointment no tiene 'price', sumamos el 'hourly_rate' del asesor asociado.
    try:
        resultado = Appointment.objects.filter(asesor=asesor, status='completed').aggregate(Sum('asesor__hourly_rate'))
        # Django crea un nombre automático raro para esto, así que usamos el índice
        ingresos = resultado['asesor__hourly_rate__sum'] or 0
    except Exception as e:
        print(f"Error calculando ingresos: {e}")
        ingresos = 0

    # 5. EL FORMULARIO
    try:
        form = PerfilAsesorForm(instance=asesor)
    except:
        form = None

    # 6. MENSAJES DEL ADMIN (¡LO NUEVO! 💬)
    # Buscamos mensajes donde el destinatario sea el usuario actual
    try:
        mensajes_admin = AdminMessage.objects.filter(destinatario=request.user).order_by('-fecha')
    except Exception as e:
        print(f"Error cargando mensajes: {e}")
        mensajes_admin = []

    context = {
        'asesor': asesor,
        'ventas': ventas,      
        'ingresos': ingresos,
        'form': form,
        'mensajes_admin': mensajes_admin  # <--- Enviamos los mensajes al HTML
    }
    return render(request, 'core/panel_asesor.html', context)

# --- PANEL DE JEFE (ADMINISTRACIÓN) ---
@login_required
def panel_admin(request):
    # 1. SEGURIDAD: Solo el Jefe entra
    if not request.user.is_superuser:
        messages.error(request, "Acceso denegado.")
        return redirect('inicio')

    # 2. FILTRADO (A prueba de errores)
    solicitudes = AsesorProfile.objects.filter(is_approved=False)
    asesores_activos = AsesorProfile.objects.filter(is_approved=True)

    # --- CORRECCIÓN AQUÍ ---
    # Intentamos buscar reclamos de las DOS formas posibles para que no falle
    try:
        # Intento 1: Si tu modelo usa 'estado_reclamo' (lo más probable)
        reclamos = Appointment.objects.filter(estado_reclamo='PENDIENTE')
    except:
        try:
            # Intento 2: Si tu modelo usa 'status' (versión alternativa)
            reclamos = Appointment.objects.filter(status='disputed')
        except:
            # Si todo falla, lista vacía para que NO de error 500
            reclamos = []

    # 3. ESTADÍSTICAS
    total_asesores = AsesorProfile.objects.count()
    total_usuarios = User.objects.count()
    pendientes_count = solicitudes.count()

    context = {
        'solicitudes': solicitudes,
        'asesores': asesores_activos,
        'reclamos': reclamos,
        'total_asesores': total_asesores,
        'total_usuarios': total_usuarios,
        'pendientes_count': pendientes_count,
    }
    
    # Asegúrate de que este nombre coincida con tu archivo HTML real
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
    # 1. DETECCIÓN DEL PERFIL
    if hasattr(request.user, 'asesorprofile'):
        asesor = request.user.asesorprofile
    elif hasattr(request.user, 'asesor_profile'):
        asesor = request.user.asesor_profile
    else:
        messages.error(request, "Debes ser asesor para gestionar horarios.")
        return redirect('inicio')
        
    # 2. PROCESAR EL FORMULARIO (GUARDAR)
    if request.method == 'POST':
        dias_elegidos = request.POST.getlist('dias[]')  # Lista de días (0=Lunes, 6=Domingo)
        horas_elegidas = request.POST.getlist('horas[]') # Lista de horas ("09:00", "10:00")
        fecha_fin_str = request.POST.get('fecha_fin')
        
        if dias_elegidos and horas_elegidas and fecha_fin_str:
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            fecha_actual = date.today()
            
            # Bucle para crear los horarios
            # (Simplificado: Iteramos desde hoy hasta fecha_fin)
            delta = fecha_fin - fecha_actual
            
            creados = 0
            for i in range(delta.days + 1):
                dia_obj = fecha_actual + timedelta(days=i)
                # Si el día de la semana (0-6) está en lo que eligió el usuario
                if str(dia_obj.weekday()) in dias_elegidos:
                    for hora_str in horas_elegidas:
                        hora_inicio = datetime.strptime(hora_str, '%H:%M').time()
                        # Crear Availability
                        Availability.objects.get_or_create(
                            asesor=asesor,
                            date=dia_obj,
                            start_time=hora_inicio,
                            defaults={'end_time': (datetime.combine(dia_obj, hora_inicio) + timedelta(hours=1)).time()}
                        )
                        creados += 1
            
            messages.success(request, f"¡Listo! Se crearon {creados} bloques de horario.")
            return redirect('gestionar_horarios')
        else:
            messages.error(request, "Por favor selecciona días, horas y fecha límite.")

    # 3. MOSTRAR LA PÁGINA
    dias_semana = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
    horas_dia = range(0, 24) 
    horarios = Availability.objects.filter(asesor=asesor).order_by('date', 'start_time')
    
    context = {
        'dias_semana': dias_semana,
        'horas_dia': horas_dia,
        'horarios': horarios
    }
    return render(request, 'core/gestionar_horarios.html', context)

@login_required
def registrar_vacaciones(request):
    try:
        asesor = request.user.asesor_profile
    except:
        return redirect('inicio')
        
    if request.method == 'POST':
        inicio_str = request.POST.get('vacaciones_inicio')
        fin_str = request.POST.get('vacaciones_fin')
        
        if inicio_str and fin_str:
            inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            fin = datetime.strptime(fin_str, '%Y-%m-%d').date()
            
            # 1. Guardar Vacaciones
            Vacation.objects.create(asesor=asesor, start_date=inicio, end_date=fin)
            
            # 2. BORRAR horarios disponibles en ese rango (Limpiar agenda)
            Availability.objects.filter(asesor=asesor, date__range=[inicio, fin], is_booked=False).delete()
            
            # 3. GESTIONAR CITAS YA AGENDADAS (EL PROBLEMA)
            citas_afectadas = Appointment.objects.filter(
                asesor=asesor, 
                start_datetime__date__range=[inicio, fin],
                status='CONFIRMADA'
            )
            
            email_origen = settings.DEFAULT_FROM_EMAIL
            
            for cita in citas_afectadas:
                # Cancelar cita
                cita.status = 'CANCELADA'
                cita.save()
                
                # ENVIAR CORREO AL CLIENTE 📧
                asunto = f"⚠️ Cita Cancelada: {asesor.user.first_name} ha entrado en vacaciones"
                mensaje = f"""
                Hola {cita.client.first_name},
                
                Lamentamos informarte que tu cita del {cita.start_datetime.strftime('%d/%m/%Y')} ha sido cancelada
                porque el asesor tuvo una urgencia personal o vacaciones.
                
                Por favor, contáctanos para tu reembolso o reagendar.
                """
                try:
                    send_mail(asunto, mensaje, email_origen, [cita.client.email], fail_silently=True)
                except:
                    pass
            
            messages.warning(request, f"Vacaciones registradas. Se cancelaron {citas_afectadas.count()} citas y se notificó a los clientes.")
            
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
    # 1. Buscamos la reserva del usuario actual
    reserva = get_object_or_404(Appointment, id=reserva_id, client=request.user)
    
    # 2. Seguridad: No permitir anular si la cita ya pasó
    if reserva.start_datetime < timezone.now():
        messages.error(request, "No puedes anular una reunión que ya pasó.")
        return redirect('mis_reservas')

    # 3. LIBERAR EL HORARIO (Availability) - ¡Paso Clave!
    # Buscamos el bloque original en la agenda del asesor
    horario = Availability.objects.filter(
        asesor=reserva.asesor,
        date=reserva.start_datetime.date(),
        start_time=reserva.start_datetime.time()
    ).first()
    
    if horario:
        horario.is_booked = False  # <--- ¡AQUÍ ESTÁ LA MAGIA! Vuelve a estar verde/disponible
        horario.save()
    
    # 4. ELIMINAMOS LA CITA
    # La borramos para que desaparezca de tu lista y del panel del asesor
    reserva.delete()
    
    messages.success(request, "Tu reserva ha sido anulada y el horario liberado.")
    return redirect('mis_reservas')

@login_required
@staff_member_required
def dashboard_financiero(request):
    # 1. Obtenemos la fecha actual por defecto
    hoy = timezone.now()
    
    # 2. CAPTURAMOS LOS FILTROS DEL HTML (Si el jefe eligió algo)
    # Si no eligió nada, usamos el mes y año actuales.
    mes_seleccionado = int(request.GET.get('mes', hoy.month))
    anio_seleccionado = int(request.GET.get('anio', hoy.year))

    # 3. OBTENER TODAS LAS VENTAS CONFIRMADAS (HISTÓRICO TOTAL)
    ventas_totales = Appointment.objects.filter(status='CONFIRMADA')
    
    # Cálculo Histórico (Desde el inicio de los tiempos)
    dinero_historico = ventas_totales.aggregate(Sum('asesor__hourly_rate'))['asesor__hourly_rate__sum'] or 0
    cantidad_historica = ventas_totales.count()
    
    # 4. FILTRAR POR EL MES Y AÑO ELEGIDOS
    ventas_del_mes = ventas_totales.filter(
        start_datetime__year=anio_seleccionado, 
        start_datetime__month=mes_seleccionado
    )
    
    # Cálculo del Mes Específico
    dinero_mes = ventas_del_mes.aggregate(Sum('asesor__hourly_rate'))['asesor__hourly_rate__sum'] or 0
    cantidad_mes = ventas_del_mes.count()

    # 5. RANKING DE ASESORES (TOP 5)
    asesores_top = AsesorProfile.objects.annotate(
        total_ventas=Count('asesor_appointments', filter=Q(asesor_appointments__status='CONFIRMADA'))
    ).order_by('-total_ventas')[:5]

    # --- LISTA DE MESES (Para que salga bonito en el HTML) ---
    nombres_meses = [
        (1, "Enero"), (2, "Febrero"), (3, "Marzo"), (4, "Abril"),
        (5, "Mayo"), (6, "Junio"), (7, "Julio"), (8, "Agosto"),
        (9, "Septiembre"), (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre")
    ]
    nombre_mes_actual = nombres_meses[mes_seleccionado - 1][1]

    return render(request, 'core/dashboard_financiero.html', {
        'dinero_historico': dinero_historico,
        'cantidad_historica': cantidad_historica,
        
        'dinero_mes': dinero_mes,         # Dinero del mes elegido
        'cantidad_mes': cantidad_mes,     # Cantidad del mes elegido
        
        'top_asesores': asesores_top,
        
        # Enviamos datos para que el filtro recuerde qué elegiste
        'mes_seleccionado': mes_seleccionado,
        'anio_seleccionado': anio_seleccionado,
        'nombre_mes_actual': nombre_mes_actual,
        'nombres_meses': nombres_meses,
        'anios_posibles': range(2024, 2031), # Del 2024 al 2030
    })
    
@login_required
def borrar_cuenta_confirmacion(request):
    if request.method == 'POST':
        password = request.POST.get('password')
        
        # 1. VERIFICAR CONTRASEÑA POR SEGURIDAD
        if not request.user.check_password(password):
            messages.error(request, "La contraseña ingresada es incorrecta.")
            return redirect('borrar_cuenta_confirmacion')
            
        # 2. LÓGICA ESPECÍFICA PARA ASESORES (Opcional pero recomendado)
        # Si es asesor, podríamos querer enviar un correo a los clientes afectados antes de borrar.
        # Por ahora, el borrado en cascada de Django se encargará de eliminar las citas.
        # Si el usuario tiene un perfil de asesor, al borrar el usuario, se borra el perfil y sus citas.

        # 3. BORRAR EL USUARIO
        user = request.user
        user.delete() # <--- ¡AQUÍ OCURRE LA MAGIA! Borra todo en cascada.
        
        # 4. CERRAR SESIÓN Y REDIRIGIR
        logout(request)
        messages.success(request, "Tu cuenta ha sido eliminada permanentemente. ¡Esperamos verte de nuevo!")
        return redirect('inicio')

    return render(request, 'core/borrar_cuenta.html')

@login_required
def solicitar_reembolso(request, reserva_id):
    reserva = get_object_or_404(Appointment, id=reserva_id, client=request.user)
    
    if request.method == 'POST':
        motivo = request.POST.get('motivo')
        if motivo:
            reserva.reclamo_mensaje = motivo
            reserva.estado_reclamo = 'PENDIENTE'
            reserva.save()
            messages.info(request, "Tu solicitud de reembolso ha sido enviada al administrador para revisión.")
            return redirect('mis_reservas')
    
    # Renderizamos un formulario simple
    return render(request, 'core/solicitar_reembolso.html', {'reserva': reserva})

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
            # --- AQUÍ EL CAMBIO: GUARDAMOS EN BD EN VEZ DE ENVIAR EMAIL ---
            AdminMessage.objects.create(
                destinatario=asesor.user,
                mensaje=texto_mensaje
            )
            messages.success(request, f"Mensaje enviado internamente a {asesor.user.first_name}.")
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
    # Recuperamos el ID de la cita que viene en la URL desde MercadoPago (external_reference)
    cita_id = request.GET.get('external_reference')
    
    if cita_id:
        try:
            # 1. Buscamos la cita fallida
            cita = Appointment.objects.get(id=cita_id)
            
            # 2. LIBERAMOS EL HORARIO (Availability)
            # Buscamos el bloque de horario que coincida con el asesor, fecha y hora de la cita
            horario = Availability.objects.filter(
                asesor=cita.asesor,
                date=cita.start_datetime.date(),
                start_time=cita.start_datetime.time()
            ).first()
            
            if horario:
                horario.is_booked = False  # <--- ¡AQUÍ ESTÁ LA MAGIA! Lo liberamos.
                horario.save()
            
            # 3. Borramos la cita "fantasma" o la marcamos como CANCELADA
            cita.delete() # La borramos para que no ensucie la base de datos
            
            messages.warning(request, "El proceso de pago fue cancelado y el horario ha sido liberado.")
        except Appointment.DoesNotExist:
            pass
            
    return redirect('inicio')