from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.timezone import now

# 1. USUARIOS Y SEGURIDAD
class User(AbstractUser):
    """
    Usuario personalizado. Soporta Cliente, Asesor y Admin.
    """
    # Definimos los roles (Solo una vez)
    ROLES = (
        ('ADMIN', 'Administrador'),
        ('ASESOR', 'Asesor (Oferente)'),
        ('CLIENTE', 'Cliente (Busca servicio)'),
    )
    
    role = models.CharField(max_length=10, choices=ROLES, default='CLIENTE')
    phone = models.CharField("Teléfono", max_length=20, blank=True, null=True)
    timezone = models.CharField("Zona Horaria", max_length=50, default='America/Santiago')
    
    # NUEVOS CAMPOS PEDIDOS POR EL JEFE
    mobile = models.CharField("Teléfono Móvil", max_length=15, null=True, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=15, null=True, blank=True)
    birth_date = models.DateField("Fecha de Nacimiento", null=True, blank=True)
    
    # SEGURIDAD (Para el código de correo)
    verification_code = models.CharField(max_length=6, null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    
    # Datos de auditoría
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

# 2. PERFIL CIEGO (LO PÚBLICO)
class AsesorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='asesor_profile')
    
    specialty = models.CharField("Especialidad", max_length=100, default="Consultor")
    description = models.TextField("Biografía Completa", blank=True, null=True)
    public_title = models.CharField("Título Público", max_length=100, help_text="Ej: Experto en Python")
    experience_summary = models.TextField("Resumen de Experiencia")
    
    # MEJORA: Cambiamos el texto a "Por Sesión" ya que ahora el tiempo es variable
    hourly_rate = models.DecimalField("Tarifa por Sesión (CLP)", max_digits=10, decimal_places=0)
    
    is_approved = models.BooleanField("¿Aprobado por Admin?", default=False)
    meeting_link = models.URLField("Enlace a Sala de Reunión", max_length=200, blank=True, null=True)
    
    # Archivo CV
    cv_file = models.FileField(upload_to='cvs/', null=True, blank=True)

    # --- NUEVO CAMPO: DURACIÓN DE LA SESIÓN (PEDIDO POR EL ADMIN) ---
    # Por defecto son 60 minutos, pero el admin puede editarlo a 30, 45, 90, etc.
    session_duration = models.IntegerField("Duración (minutos)", default=60, help_text="Tiempo que dura cada bloque de horario")

    def __str__(self):
        return f"Perfil de {self.user.username} - {self.public_title}"

# 3. DISPONIBILIDAD (CALENDARIO)
class Availability(models.Model):
    asesor = models.ForeignKey(AsesorProfile, on_delete=models.CASCADE, related_name='availabilities')
    date = models.DateField("Fecha")  # CAMBIO: Usamos fecha real (2026-01-25)
    start_time = models.TimeField("Hora Inicio")
    end_time = models.TimeField("Hora Fin")
    is_booked = models.BooleanField(default=False) # Para saber si ya la tomaron

    def __str__(self):
        return f"{self.asesor} - {self.date} a las {self.start_time}"

# 4. RESERVAS (EL NEGOCIO)
class Appointment(models.Model):
    STATUS_CHOICES = (
        ('PENDIENTE', 'Pendiente de Aprobación'),
        ('POR_PAGAR', 'Aprobada - Esperando Pago'),
        ('CONFIRMADA', 'Pagada y Confirmada'),
        ('FINALIZADA', 'Realizada'),
        ('CANCELADA', 'Cancelada'),
        ('REEMBOLSADO', 'Dinero Devuelto'), # NUEVO ESTADO PARA TU REEMBOLSO
    )

    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='appointments', null=True, blank=True)
    asesor = models.ForeignKey(AsesorProfile, on_delete=models.CASCADE, related_name='asesor_appointments')
    
    # Fechas siempre en UTC
    start_datetime = models.DateTimeField("Fecha/Hora Inicio")
    end_datetime = models.DateTimeField("Fecha/Hora Fin")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDIENTE')
    meeting_link = models.URLField("Enlace a Sala de Reunión (Zoom/Meet)", max_length=200, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Datos geográficos del cliente (Opcional)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    client_city = models.CharField(max_length=100, null=True, blank=True)
    client_address = models.CharField(max_length=255, null=True, blank=True)
    client_postal_code = models.CharField(max_length=20, null=True, blank=True)
    
    # --- SISTEMA DE RECLAMOS Y REEMBOLSOS (LO QUE PEDISTE) ---
    reclamo_mensaje = models.TextField(null=True, blank=True, help_text="Razón del reclamo del cliente")
    estado_reclamo = models.CharField(
        max_length=20,
        choices=[
            ('SIN_RECLAMO', 'Sin Reclamo'),
            ('PENDIENTE', 'Revisión Pendiente (Jefe)'),
            ('APROBADO', 'Reembolso Aprobado'),
            ('RECHAZADO', 'Reclamo Rechazado')
        ],
        default='SIN_RECLAMO'
    )
    
    # NOTA: No guardamos la tarjeta real por seguridad.
    # El ID real del pago está en el modelo 'Payment' (abajo).
    payment_token = models.CharField(max_length=100, null=True, blank=True, help_text="Referencia interna, NO es la tarjeta.")

    def __str__(self):
        return f"Cita: {self.client} con {self.asesor} ({self.status})"

# 5. PAGOS Y RESEÑAS
class Payment(models.Model):
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=0)
    
    # ESTE ES EL DATO IMPORTANTE DEL DINERO REAL
    # Aquí se guarda el ID que nos da Mercado Pago (ej: 12345678901)
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
    
class ChatMessage(models.Model):
    # Sender: Quien envía (Puede ser Admin o Asesor)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mensajes_enviados')
    # Recipient: Quien recibe
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mensajes_recibidos')
    
    mensaje = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False)

    def __str__(self):
        return f"De {self.sender.first_name} para {self.recipient.first_name} - {self.fecha.strftime('%d/%m %H:%M')}"