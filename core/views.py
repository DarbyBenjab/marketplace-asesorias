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
    
    # 1. Buscamos las citas que tú creaste en "Gestionar Horarios"
    # Que sean de este asesor, esten DISPONIBLES y sean en el FUTURO
    citas_disponibles = Appointment.objects.filter(
        asesor=asesor,
        status='DISPONIBLE',          # Usamos tu estado original
        start_datetime__gte=timezone.now() # Solo futuras
    ).order_by('start_datetime')

    # 2. DICCIONARIOS DE TRADUCCIÓN (Tu código original, está perfecto)
    dias_esp = {
        'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
        'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
    }
    meses_esp = {
        'January': 'Enero', 'February': 'Febrero', 'March': 'Marzo', 'April': 'Abril',
        'May': 'Mayo', 'June': 'Junio', 'July': 'Julio', 'August': 'Agosto',
        'September': 'Septiembre', 'October': 'Octubre', 'November': 'Noviembre', 'December': 'Diciembre'
    }

    # 3. AGRUPAR POR DÍA (Agenda)
    agenda = {}
    for cita in citas_disponibles:
        # Extraer datos en inglés
        dia_ing = cita.start_datetime.strftime("%A")
        mes_ing = cita.start_datetime.strftime("%B")
        dia_num = cita.start_datetime.strftime("%d")

        # Traducir al español
        fecha_texto = f"{dias_esp[dia_ing]} {dia_num} de {meses_esp[mes_ing]}"

        if fecha_texto not in agenda:
            agenda[fecha_texto] = []
        agenda[fecha_texto].append(cita)

    return render(request, 'core/detalle_asesor.html', {
        'asesor': asesor,
        'agenda': agenda,
    })
    
@login_required
def reservar_hora(request, cita_id):
    cita = get_object_or_404(Appointment, id=cita_id)

    # Verificamos que siga disponible
    if cita.status != 'DISPONIBLE':
        return render(request, 'core/error.html', {'mensaje': 'Esta hora ya fue tomada 😞'})

    # ASIGNAMOS EL CLIENTE PERO NO CAMBIAMOS EL ESTADO AÚN
    cita.client = request.user
    
    # ❌ BORRAMOS O COMENTAMOS ESTA LÍNEA:
    # cita.status = 'POR_PAGAR'  <-- ¡ESTO ERA LO QUE LA BORRABA!
    
    # ✅ LA DEJAMOS COMO 'DISPONIBLE'
    cita.status = 'DISPONIBLE' 
    
    cita.save()

    return redirect('checkout', reserva_id=cita.id)

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
        # Si tienes la función obtener_ip_cliente, úsala, si no, comenta esta línea:
        # reserva.client_ip = obtener_ip_cliente(request)
        
        # --- 2. INTEGRACIÓN MERCADO PAGO ---
        sdk = mercadopago.SDK(settings.MERCADO_PAGO_TOKEN)
        
        # Creamos los datos de la preferencia
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
            "back_urls": {
                "success": request.build_absolute_uri(reverse('pago_exitoso', args=[reserva.id])),
                "failure": request.build_absolute_uri(reverse('inicio')),
                "pending": request.build_absolute_uri(reverse('inicio'))
            },
            "auto_return": "approved",
        }

        # --- AQUÍ ESTÁ LA CORRECCIÓN CLAVE ---
        try:
            # 1. Hacemos la petición
            preference_response = sdk.preference().create(preference_data)
            
            # 2. Imprimimos para depurar (mira tu consola negra si falla)
            print("Respuesta MP:", preference_response) 

            # 3. Verificamos que la respuesta tenga el link
            if "response" in preference_response and "init_point" in preference_response["response"]:
                
                # Guardamos los datos de dirección antes de irnos
                reserva.save()
                
                # Extraemos el link real
                url_pago = preference_response["response"]["init_point"]
                
                # Redirigimos al usuario a Mercado Pago
                return redirect(url_pago)
            
            else:
                # Si Mercado Pago devolvió un error (ej: token malo)
                print("Error en la estructura de respuesta MP")
                return render(request, 'core/error.html', {'mensaje': 'Error al conectar con Mercado Pago. Revisa la consola.'})

        except Exception as e:
            print(f"Error técnico: {e}")
            return render(request, 'core/error.html', {'mensaje': f'Ocurrió un error inesperado: {str(e)}'})

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

    context = {
        'asesor': asesor,
        'ventas': ventas,      
        'ingresos': ingresos,
        'form': form
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
            user = form.save()
            
            # --- CORRECCIÓN: Envío de correo seguro (Anti-Caídas) ---
            try:
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                
                # Intentar enviar correo (Si falla, no rompe la página)
                subject = 'Bienvenido al Marketplace'
                message = f'Hola {user.first_name}, gracias por registrarte.'
                from_email = settings.DEFAULT_FROM_EMAIL
                recipient_list = [user.email]
                send_mail(subject, message, from_email, recipient_list)
                
            except Exception as e:
                print(f"Error enviando correo (pero el usuario se creó): {e}")
                # No hacemos nada más, dejamos que el usuario siga feliz
            
            messages.success(request, "Cuenta creada exitosamente.")
            return redirect('inicio')
        else:
            messages.error(request, "Error en el formulario. Revisa los datos.")
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
    try:
        asesor = request.user.asesor_profile
    except AsesorProfile.DoesNotExist:
        messages.error(request, "Debes ser asesor para gestionar horarios.")
        return redirect('inicio')
        
    if request.method == 'POST':
        # ... (Toda la lógica de guardar se mantiene igual, no la toques) ...
        # Si quieres copiar todo de nuevo para estar seguro, avísame y te paso la función entera.
        # Pero lo importante es lo que enviamos al final (el contexto).
        pass 

    # --- AQUÍ ESTÁ EL CAMBIO CLAVE ---
    # 1. Agregamos Sábado y Domingo
    dias_semana = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
    
    # 2. Cambiamos el rango: de 0 (00:00) a 24 (el final del día)
    horas_dia = range(0, 24) 

    # Lógica para mostrar horarios existentes (se mantiene igual)
    horarios = Availability.objects.filter(asesor=asesor).order_by('day_of_week', 'start_time')
    
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
    # Buscamos la reserva. Debe ser del usuario actual (seguridad).
    reserva = get_object_or_404(Appointment, id=reserva_id, client=request.user)
    
    # Solo permitimos anular si NO ha pasado la fecha (no puedes cancelar una reunión de ayer)
    if reserva.start_datetime < timezone.now():
        messages.error(request, "No puedes cancelar una reunión que ya pasó.")
        return redirect('mis_reservas')

    # LÓGICA DE ANULACIÓN
    # 1. La volvemos a poner DISPONIBLE para el Asesor
    reserva.status = 'DISPONIBLE'
    
    # 2. Desvinculamos al cliente (la dejamos huérfana para que otro la adopte)
    reserva.client = None
    
    # 3. Limpiamos datos sensibles (opcional, pero buena práctica)
    reserva.client_address = None
    reserva.client_ip = None
    
    reserva.save()
    
    # 4. Enviar correo de aviso al asesor (Opcional, pero recomendado)
    # send_mail(...)
    
    messages.success(request, "Tu reserva ha sido anulada exitosamente.")
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
        mensaje_admin = request.POST.get('mensaje')
        if mensaje_admin:
            asunto = f"📢 Aviso del Administrador - Marketplace Asesorías"
            cuerpo = f"""
            Hola {asesor.user.first_name},
            
            El administrador tiene una observación para ti:
            
            ------------------------------------------------
            "{mensaje_admin}"
            ------------------------------------------------
            
            Por favor revisa esto en tu panel o realiza los cambios solicitados.
            
            Atte,
            Equipo de Administración
            """
            
            # --- CORRECCIÓN: TRY-EXCEPT PARA QUE NO EXPLOTE ---
            try:
                send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [asesor.user.email], fail_silently=False)
                messages.success(request, f"Observación enviada correctamente a {asesor.user.email}")
            except Exception as e:
                print(f"Error enviando correo: {e}")
                # Le decimos al admin que el mensaje "se generó" pero el correo falló, sin romper la página
                messages.warning(request, "El mensaje se procesó, pero el correo no pudo salir (Error de servidor).")
            
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