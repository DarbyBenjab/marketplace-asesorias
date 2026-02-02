from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.timezone import now
from django.utils import timezone # <--- AGREGADO: Para cálculos exactos de hora
from datetime import timedelta    # <--- AGREGADO: Para sumar/restar minutos y horas

# ==========================================
# 1. USUARIOS Y SEGURIDAD
# ==========================================
class User(AbstractUser):
    """
    Usuario personalizado. Soporta Cliente, Asesor y Admin.
    """
    ROLES = (
        ('ADMIN', 'Administrador'),
        ('ASESOR', 'Asesor (Oferente)'),
        ('CLIENTE', 'Cliente (Busca servicio)'),
    )
    
    role = models.CharField(max_length=10, choices=ROLES, default='CLIENTE')
    phone = models.CharField("Teléfono", max_length=20, blank=True, null=True)
    timezone = models.CharField("Zona Horaria", max_length=50, default='America/Santiago')
    
    # CAMPOS DE CONTACTO ADICIONALES
    mobile = models.CharField("Teléfono Móvil", max_length=15, null=True, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=15, null=True, blank=True)
    birth_date = models.DateField("Fecha de Nacimiento", null=True, blank=True)
    
    # SEGURIDAD Y AUDITORÍA
    verification_code = models.CharField(max_length=6, null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

# ==========================================
# 2. PERFIL CIEGO (LO PÚBLICO)
# ==========================================
class AsesorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='asesor_profile')
    
    specialty = models.CharField("Especialidad", max_length=100, default="Consultor")
    description = models.TextField("Biografía Completa", blank=True, null=True)
    public_title = models.CharField("Título Público", max_length=100, help_text="Ej: Experto en Python")
    experience_summary = models.TextField("Resumen de Experiencia")
    
    hourly_rate = models.DecimalField("Tarifa por Sesión (CLP)", max_digits=10, decimal_places=0)
    
    is_approved = models.BooleanField("¿Aprobado por Admin?", default=False)
    meeting_link = models.URLField("Enlace a Sala de Reunión", max_length=200, blank=True, null=True)
    
    cv_file = models.FileField(upload_to='cvs/', null=True, blank=True)
    session_duration = models.IntegerField("Duración (minutos)", default=60, help_text="Tiempo que dura cada bloque de horario")

    # AUTOMATIZACIÓN DE AGENDA
    auto_schedule = models.BooleanField(default=False, verbose_name="Modo Automático") 
    active_days = models.CharField(max_length=50, blank=True, default="", help_text="Días activos (0=Lunes, 6=Domingo)") 
    active_hours = models.TextField(blank=True, default="", help_text="Lista de horas activas separadas por coma") 

    def __str__(self):
        return f"Perfil de {self.user.username} - {self.public_title}"

# ==========================================
# 3. DISPONIBILIDAD (CALENDARIO)
# ==========================================
class Availability(models.Model):
    asesor = models.ForeignKey(AsesorProfile, on_delete=models.CASCADE, related_name='availabilities')
    date = models.DateField("Fecha")
    start_time = models.TimeField("Hora Inicio")
    end_time = models.TimeField("Hora Fin")
    is_booked = models.BooleanField(default=False)

    class Meta:
        ordering = ['date', 'start_time'] # Mejora: Ordenar cronológicamente

    def __str__(self):
        return f"{self.asesor} - {self.date} a las {self.start_time}"

# ==========================================
# 4. RESERVAS (LÓGICA DE NEGOCIO POTENTE)
# ==========================================
class Appointment(models.Model):
    STATUS_CHOICES = (
        ('PENDIENTE', 'Pendiente de Aprobación'),
        ('POR_PAGAR', 'Aprobada - Esperando Pago'),
        ('CONFIRMADA', 'Pagada y Confirmada'),
        ('FINALIZADA', 'Realizada'),
        ('CANCELADA', 'Cancelada'),
        ('REEMBOLSADO', 'Dinero Devuelto'), 
    )

    SOLICITUD_CHOICES = (
        ('NINGUNA', 'Sin Solicitud'),
        ('PENDIENTE', 'Solicitud Pendiente'),
        ('APROBADA', 'Cambio Aprobado (Pagar Multa)'),
        ('FINALIZADA', 'Cambio Realizado'),
        ('RECHAZADA', 'Solicitud Rechazada'),
    )

    RECLAMO_CHOICES = (
        ('SIN_RECLAMO', 'Sin Reclamo'),
        ('PENDIENTE', 'Revisión Pendiente (Jefe)'),
        ('APROBADO', 'Reembolso Aprobado'),
        ('RECHAZADO', 'Reclamo Rechazado'),
    )

    # RELACIONES
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='appointments', null=True, blank=True)
    asesor = models.ForeignKey('AsesorProfile', on_delete=models.CASCADE, related_name='asesor_appointments')
    
    # FECHAS
    start_datetime = models.DateTimeField("Fecha/Hora Inicio")
    end_datetime = models.DateTimeField("Fecha/Hora Fin")
    
    # ESTADO Y REUNIÓN
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDIENTE')
    meeting_link = models.URLField("Enlace a Sala de Reunión (Zoom/Meet)", max_length=200, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # DATOS GEOGRÁFICOS (BASE)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    client_city = models.CharField(max_length=100, null=True, blank=True)
    client_address = models.CharField(max_length=255, null=True, blank=True)
    client_postal_code = models.CharField(max_length=20, null=True, blank=True)

    # ==========================================
    # NUEVOS CAMPOS DE FACTURACIÓN
    # ==========================================
    TIPO_DOCUMENTO_CHOICES = (
        ('BOLETA', 'Boleta'),
        ('FACTURA', 'Factura'),
    )
    
    tipo_documento = models.CharField(max_length=10, choices=TIPO_DOCUMENTO_CHOICES, default='BOLETA')
    
    # Datos Fiscales
    rut_facturacion = models.CharField("RUT", max_length=12, null=True, blank=True)
    telefono_facturacion = models.CharField("Teléfono", max_length=15, null=True, blank=True)
    email_facturacion = models.EmailField("Email Facturación", null=True, blank=True)
    nombre_facturacion = models.CharField("Nombre / Razón Social", max_length=150, null=True, blank=True)
    
    # Solo Factura
    giro_facturacion = models.CharField("Giro", max_length=150, null=True, blank=True)
    comuna_facturacion = models.CharField("Comuna", max_length=100, null=True, blank=True)
    # ==========================================

    # RECLAMOS (72H)
    reclamo_mensaje = models.TextField(null=True, blank=True, help_text="Razón del reclamo del cliente")
    estado_reclamo = models.CharField(max_length=20, choices=RECLAMO_CHOICES, default='SIN_RECLAMO')
    
    # CAMBIO DE HORA (48H + MULTA)
    solicitud_cambio = models.BooleanField(default=False, help_text="¿El cliente solicitó cambiar la hora?") 
    motivo_cambio = models.TextField(blank=True, null=True, help_text="Motivo por el cual quiere cambiar la hora")
    estado_solicitud = models.CharField(max_length=20, choices=SOLICITUD_CHOICES, default='NINGUNA')
    multa_pagada = models.BooleanField(default=False, help_text="¿Pagó el 15% de recargo?")

    # PAGO
    payment_token = models.CharField(max_length=100, null=True, blank=True, help_text="Referencia interna")

    # ==========================================
    # LÓGICA AGREGADA PARA HTML (MIS RESERVAS)
    # ==========================================
    @property
    def horas_restantes(self):
        """Retorna cuántas horas faltan para la cita (o negativas si ya pasó)."""
        if not self.start_datetime:
            return 0
        ahora = timezone.now()
        diferencia = self.start_datetime - ahora
        return diferencia.total_seconds() / 3600

    @property
    def puede_reembolsar(self):
        """Regla: Solo si faltan más de 72 horas y está confirmada."""
        return self.status == 'CONFIRMADA' and self.horas_restantes > 72

    @property
    def puede_cambiar(self):
        """Regla: Solo si faltan más de 48 horas y está confirmada."""
        return self.status == 'CONFIRMADA' and self.horas_restantes > 48

    @property
    def mostrar_video(self):
        """
        Regla: Mostrar botón 15 min antes y hasta que termine la cita.
        Solo si está pagada (CONFIRMADA).
        """
        if self.status != 'CONFIRMADA':
            return False
        
        ahora = timezone.now()
        inicio_visible = self.start_datetime - timedelta(minutes=15)
        
        # Si por alguna razón no hay fecha fin, asumimos 1 hora después del inicio
        fin_real = self.end_datetime if self.end_datetime else (self.start_datetime + timedelta(hours=1))
        
        return inicio_visible <= ahora <= fin_real

    class Meta:
        ordering = ['-start_datetime'] # Mejora: Las más recientes primero

    def __str__(self):
        return f"Cita: {self.client} con {self.asesor} ({self.status})"

# ==========================================
# 5. PAGOS Y RESEÑAS
# ==========================================
class Payment(models.Model):
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=0)
    transaction_id = models.CharField("ID MercadoPago", max_length=100)
    payment_status = models.CharField(max_length=20, default='approved')
    created_at = models.DateTimeField(auto_now_add=True)

class Review(models.Model):
    asesor = models.ForeignKey(AsesorProfile, on_delete=models.CASCADE, related_name='reviews')
    client = models.ForeignKey(User, on_delete=models.CASCADE)
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE)
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    comment = models.TextField("Comentario", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reseña de {self.client.first_name} para {self.asesor}"

class Vacation(models.Model):
    asesor = models.ForeignKey(AsesorProfile, on_delete=models.CASCADE)
    start_date = models.DateField("Desde")
    end_date = models.DateField("Hasta")
    reason = models.CharField("Motivo", max_length=200, default="Vacaciones")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Vacaciones de {self.asesor}: {self.start_date} al {self.end_date}"

# ==========================================
# 6. CHAT SISTEMA
# ==========================================
class ChatMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mensajes_enviados')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mensajes_recibidos')
    mensaje = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False)

    class Meta:
        ordering = ['fecha'] # Mejora: Ordenar mensajes por fecha

    def __str__(self):
        return f"De {self.sender.first_name} para {self.recipient.first_name} - {self.fecha.strftime('%d/%m %H:%M')}"

# ==========================================
# 7. SISTEMA DE RECLAMOS / SUGERENCIAS
# ==========================================
class SoporteUsuario(models.Model):
    TIPO_CHOICES = (
        ('FELICITACION', '🎉 Felicitación'),
        ('SUGERENCIA', '💡 Sugerencia'),
        ('RECLAMO', '⚠️ Reclamo'),
    )

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='SUGERENCIA')
    nombre = models.CharField("Nombre", max_length=100)
    telefono = models.CharField("Teléfono", max_length=20)
    email = models.EmailField("Email")
    mensaje = models.TextField("Mensaje")
    archivo = models.FileField("Adjuntar Archivo", upload_to='reclamos/', null=True, blank=True)
    
    fecha_envio = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False) # Para que el admin sepa si ya lo vio

    def __str__(self):
        return f"{self.get_tipo_display()} de {self.nombre}"