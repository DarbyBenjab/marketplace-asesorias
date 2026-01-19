import random  
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout 
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from datetime import timedelta, datetime
from django.contrib.admin.views.decorators import staff_member_required
from .models import AsesorProfile, Availability, Appointment, User, Review
from .forms import RegistroUnificadoForm, PerfilAsesorForm
from .forms import DisponibilidadForm
from .forms import ReviewForm
from .forms import AsesorPerfilForm
from django.db.models import Q
from django.db.models import Sum, Count
from django.core.mail import send_mail
from datetime import datetime, timedelta
from django.contrib import messages
from decimal import Decimal
import mercadopago
from django.urls import reverse
from django.conf import settings

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
    reserva = get_object_or_404(Appointment, id=reserva_id, client=request.user)
    
    if request.method == 'POST':
        # --- 1. GUARDAR DATOS DEL CLIENTE (Igual que antes) ---
        reserva.client_address = request.POST.get('direccion')
        reserva.client_city = request.POST.get('ciudad')
        reserva.client_postal_code = request.POST.get('codigo_postal')
        reserva.client_ip = obtener_ip_cliente(request)
        
        # --- 2. INTEGRACIÓN MERCADO PAGO ---
        # Iniciamos el SDK con tu TOKEN DE PRUEBA
        # (Idealmente esto va en settings.py, pero por ahora ponlo aquí)
        sdk = mercadopago.SDK(settings.MERCADO_PAGO_TOKEN)
        
        # Creamos los datos de la preferencia (La "Factura")
        preference_data = {
            "items": [
                {
                    "title": f"Asesoría con {reserva.asesor.user.first_name}",
                    "quantity": 1,
                    "unit_price": float(reserva.asesor.hourly_rate), # Precio real del asesor
                }
            ],
            "payer": {
                "email": request.user.email  # El email del que paga
            },
            # A DÓNDE VUELVE EL USUARIO DESPUÉS DE PAGAR
            "back_urls": {
                # Construimos la URL completa (http://127.0.0.1:8000/...)
                "success": request.build_absolute_uri(reverse('pago_exitoso', args=[reserva.id])),
                "failure": request.build_absolute_uri(reverse('inicio')), # O una vista de error
                "pending": request.build_absolute_uri(reverse('inicio'))
            },
            "auto_return": "approved", # Vuelve automático apenas paga
        }

        # Le pedimos el link a Mercado Pago
        preference_response = sdk.preference().create(preference_data)
        preference = preference_response["response"]

        # Guardamos la reserva con los datos actualizados
        reserva.save()
        
        # --- 3. REDIRIGIMOS A MERCADO PAGO ---
        # En lugar de ir a 'pago_exitoso', lo mandamos a la web amarilla de pago
        return redirect(preference["init_point"])

    return render(request, 'core/checkout.html', {'reserva': reserva})

@login_required
def pago_exitoso(request, reserva_id):
    # Buscamos la reserva
    reserva = get_object_or_404(Appointment, id=reserva_id)
    
    # --- 1. CAPTURAR RESPUESTA DE MERCADO PAGO (NUEVO) ---
    # Mercado Pago agrega ?status=approved a la URL cuando vuelve
    status_pago = request.GET.get('status') 
    
    # --- 2. VALIDACIÓN PRINCIPAL ---
    # Entramos si:
    # A) Mercado Pago dice explícitamente 'approved' (Pago Real)
    # B) O si la reserva sigue 'DISPONIBLE' (Para compatibilidad si pruebas sin pagar)
    if status_pago == 'approved' or reserva.status == 'DISPONIBLE':
        
        # CASO A: PRIMERA VEZ QUE ENTRA (CONFIRMAMOS TODO)
        if reserva.status == 'DISPONIBLE':
            
            # ¡BLOQUEAMOS LA HORA! 🔒
            reserva.status = 'CONFIRMADA'
            reserva.client = request.user
            reserva.save()
            
            # --- CORRECCIÓN DE HORA ---
            fecha_local = timezone.localtime(reserva.start_datetime)
            
            # Validación del link
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
            
            Por favor, asegúrate de que tu link de reunión funcione.
            """

            # ENVIAR CORREOS
            try:
                send_mail(asunto_cliente, mensaje_cliente, 'darbybenjamin000@gmail.com', [request.user.email], fail_silently=True)
                send_mail(asunto_asesor, mensaje_asesor, 'darbybenjamin000@gmail.com', [reserva.asesor.user.email], fail_silently=True)
            except Exception as e:
                print(f"Error correos: {e}")

        # CASO B: EL USUARIO RECARGÓ LA PÁGINA (YA ERA SUYA)
        elif reserva.status == 'CONFIRMADA' and reserva.client == request.user:
            pass # No hacemos nada, solo le mostramos el éxito de nuevo
            
        # CASO C: ERROR RARO (PAGÓ PERO ALGUIEN SE LA GANÓ UN MILISEGUNDO ANTES)
        else:
            return render(request, 'core/error.html', {'mensaje': 'Lo sentimos, alguien tomó esta hora justo mientras pagabas.'})
                
        # FINAL: MOSTRAR PANTALLA DE ÉXITO
        return render(request, 'core/payment_success.html', {'appointment': reserva})

    # --- 3. SI EL PAGO FALLÓ (RECHAZADO O PENDIENTE) ---
    else:
        return render(request, 'core/error.html', {'mensaje': 'El pago no fue aprobado o fue cancelado.'})

@login_required
def mis_reservas(request):
    # Trae todas las reservas de ESTE cliente, ordenadas por fecha
    reservas = Appointment.objects.filter(client=request.user).order_by('-created_at')
    return render(request, 'core/mis_reservas.html', {'reservas': reservas})

@login_required
def panel_asesor(request):
    """
    Vista HÍBRIDA:
    1. Si no tiene perfil -> Lo manda a registrarse.
    2. Si ya tiene perfil -> Muestra el panel de control y permite editar datos.
    """
    
    # 1. INTENTAMOS OBTENER EL PERFIL
    try:
        perfil = AsesorProfile.objects.get(user=request.user)
    except AsesorProfile.DoesNotExist:
        return redirect('solicitud_asesor')

    # --- SI LLEGAMOS AQUÍ, ES PORQUE EL PERFIL SÍ EXISTE ---

    # 🔴 NUEVO: Obtenemos la hora actual para filtrar
    ahora = timezone.now()

    # 2. Buscamos sus ventas (Citas confirmadas Y FUTURAS)
    mis_ventas = Appointment.objects.filter(
        asesor=perfil, 
        status='CONFIRMADA',
        start_datetime__gte=ahora  # 🔴 NUEVO: Solo muestra las que vienen (Greater Than or Equal)
    ).order_by('start_datetime')

    # 3. Procesamos el formulario por si quiere actualizar sus datos
    if request.method == 'POST':
        form = PerfilAsesorForm(request.POST, request.FILES, instance=perfil)
        if form.is_valid():
            form.save()
            return render(request, 'core/panel_asesor.html', {
                'form': form, 
                'perfil': perfil, 
                'mensaje': 'Datos actualizados correctamente ✅',
                'ventas': mis_ventas
            })
    else:
        form = PerfilAsesorForm(instance=perfil)

    # 4. Mostramos el panel final
    return render(request, 'core/panel_asesor.html', {
        'form': form, 
        'perfil': perfil,
        'ventas': mis_ventas
    })

@login_required
def redireccionar_usuario(request):
    if request.user.role == 'ASESOR':
        return redirect('panel_asesor')
    else:
        return redirect('inicio')

# 1. EL PANEL DEL JEFE (Vista)
@login_required
@staff_member_required # <--- Solo tú y tu jefe (Superusuarios) pueden entrar aquí
def panel_administracion(request):
    # Buscamos a todos los asesores que NO están aprobados (False)
    asesores_pendientes = AsesorProfile.objects.filter(is_approved=False)
    
    # Opcional: También mostrar los ya aprobados por si quiere bloquear a alguien
    asesores_activos = AsesorProfile.objects.filter(is_approved=True)

    return render(request, 'core/panel_admin.html', {
        'pendientes': asesores_pendientes,
        'activos': asesores_activos
    })

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
            
            # GENERAR CÓDIGO DE 6 DÍGITOS
            codigo = str(random.randint(100000, 999999))
            user.verification_code = codigo
            user.save()
            
            # SIMULAR ENVÍO DE CORREO (MIRA LA CONSOLA NEGRA)
            print(f"------------------------------------------------")
            print(f"📧 EMAIL PARA {user.email}: TU CÓDIGO ES {codigo}")
            print(f"------------------------------------------------")
            
            # Guardamos el ID del usuario en la sesión para saber a quién verificar
            request.session['user_id_verify'] = user.id
            
            return redirect('verificar_email')
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
    # 1. BÚSQUEDA INTELIGENTE DEL PERFIL
    perfil = AsesorProfile.objects.filter(user=request.user).first()

    if not perfil:
        return redirect('lobby')

    # 2. Lógica para AGREGAR un horario
    if request.method == 'POST':
        fecha = request.POST.get('fecha')
        hora = request.POST.get('hora')
        
        if fecha and hora:
            # A. Convertimos el texto (ej: "2026-01-25" y "16:00") a un objeto de tiempo real
            fecha_hora_str = f"{fecha} {hora}"
            start_dt = datetime.strptime(fecha_hora_str, "%Y-%m-%d %H:%M")
            
            # B. Hacemos que la fecha entienda de zonas horarias (para que Django no reclame)
            start_dt = timezone.make_aware(start_dt)
            
            # C. CALCULAMOS EL FINAL (Sumamos 1 hora) <--- AQUÍ ESTABA EL ERROR
            end_dt = start_dt + timedelta(hours=1) 
            
            # D. Guardamos con inicio Y fin
            Appointment.objects.create(
                asesor=perfil,
                client=None,
                start_datetime=start_dt,
                end_datetime=end_dt, # <--- SOLUCIÓN: Ahora sí guardamos el fin
                status='DISPONIBLE'
            )
            return redirect('gestionar_horarios')

    # 3. Mostrar horarios
    horarios = Appointment.objects.filter(
        asesor=perfil,
        start_datetime__gte=timezone.now(),
        status='DISPONIBLE'
    ).order_by('start_datetime')

    return render(request, 'core/gestionar_horarios.html', {'horarios': horarios})

# Extra: Función para BORRAR un horario (si se equivocó)
@login_required
def borrar_horario(request, horario_id):
    # Buscamos el horario, asegurándonos de que pertenezca al asesor actual (seguridad)
    # Asumiendo que usas 'Appointment' para los horarios libres
    horario = get_object_or_404(Appointment, id=horario_id)
    
    # Verificamos que este horario sea del usuario que está logueado
    if horario.asesor.user == request.user:
        horario.delete()
        # Opcional: messages.success(request, "Horario eliminado")
    
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
@user_passes_test(lambda u: u.is_superuser) # Seguridad: Solo el Jefe entra
def panel_admin(request):
    # Lista de pendientes y activos
    pendientes = AsesorProfile.objects.filter(is_approved=False)
    activos = AsesorProfile.objects.filter(is_approved=True)
    
    return render(request, 'core/panel_admin.html', {
        'pendientes': pendientes,
        'activos': activos
    })

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
    # 1. Buscamos el perfil del usuario actual
    perfil = get_object_or_404(AsesorProfile, user=request.user)

    if request.method == 'POST':
        form = AsesorPerfilForm(request.POST, instance=perfil)
        if form.is_valid():
            form.save()
            messages.success(request, '¡Tu perfil ha sido actualizado!')
            return redirect('panel_asesor')
    else:
        # Si es GET, mostramos el formulario con los datos actuales
        form = AsesorPerfilForm(instance=perfil)

    # Volvemos a la normalidad
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
    # 1. OBTENER TODAS LAS VENTAS CONFIRMADAS
    ventas_totales = Appointment.objects.filter(status='CONFIRMADA')
    
    # 2. CÁLCULO HISTÓRICO
    dinero_total = ventas_totales.aggregate(Sum('asesor__hourly_rate'))['asesor__hourly_rate__sum'] or 0
    cantidad_total = ventas_totales.count()
    
    # 3. CÁLCULO DE ESTE MES
    hoy = timezone.now()
    ventas_mes = ventas_totales.filter(
        start_datetime__year=hoy.year, 
        start_datetime__month=hoy.month
    )
    dinero_mes = ventas_mes.aggregate(Sum('asesor__hourly_rate'))['asesor__hourly_rate__sum'] or 0
    cantidad_mes = ventas_mes.count()

    # 4. EL "%" (CORREGIDO Y REDONDEADO)
    # Convertimos a entero (int) para eliminar los decimales aquí mismo
    raw_ganancia = dinero_total * Decimal('0.10')
    ganancia_plataforma = int(raw_ganancia) # <--- Al hacerlo int, quitamos los decimales

    # 5. RANKING DE ASESORES
    asesores = AsesorProfile.objects.annotate(
        total_ventas=Count('asesor_appointments', filter=Q(asesor_appointments__status='CONFIRMADA'))
    ).order_by('-total_ventas')[:5]

    return render(request, 'core/dashboard_financiero.html', {
        'dinero_total': dinero_total,
        'cantidad_total': cantidad_total,
        'dinero_mes': dinero_mes,
        'cantidad_mes': cantidad_mes,
        'ganancia_plataforma': ganancia_plataforma,
        'top_asesores': asesores,
        'mes_actual': hoy.strftime("%B")
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