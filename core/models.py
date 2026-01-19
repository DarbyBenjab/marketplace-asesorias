from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.timezone import now

# 1. USUARIOS Y SEGURIDAD
class User(AbstractUser):
    """
    Usuario personalizado. Soporta Cliente, Asesor y Admin.
    Reemplaza al usuario por defecto de Django.
    """
    ROLES = (
        ('ADMIN', 'Administrador'),
        ('ASESOR', 'Asesor (Oferente)'),
        ('CLIENTE', 'Cliente (Busca servicio)'),
    )
    
    role = models.CharField(max_length=10, choices=ROLES, default='CLIENTE')
    phone = models.CharField("Teléfono", max_length=20, blank=True, null=True)
    timezone = models.CharField("Zona Horaria", max_length=50, default='America/Santiago')
    is_verified = models.BooleanField(default=False)
    
    ROLE_CHOICES = (
        ('CLIENTE', 'Cliente'),
        ('ASESOR', 'Asesor'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='CLIENTE')
    
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
    """
    Información pública del asesor.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='asesor_profile')
    
    # --- CAMPOS NUEVOS (Los que faltaban y daban error) ---
    specialty = models.CharField("Especialidad", max_length=100, default="Consultor") # Nuevo
    description = models.TextField("Biografía Completa", blank=True, null=True)       # Nuevo
    # ------------------------------------------------------

    # --- CAMPOS QUE YA TENÍAS (Mantenlos para no perder datos) ---
    public_title = models.CharField("Título Público", max_length=100, help_text="Ej: Experto en Python")
    experience_summary = models.TextField("Resumen de Experiencia")
    hourly_rate = models.DecimalField("Tarifa por Hora (CLP)", max_digits=10, decimal_places=0)
    is_approved = models.BooleanField("¿Aprobado por Admin?", default=False)
    meeting_link = models.URLField("Enlace a Sala de Reunión", max_length=200, blank=True, null=True)
    
    # Archivo CV (Importante no borrarlo)
    cv_file = models.FileField(upload_to='cvs/', null=True, blank=True)

    def __str__(self):
        return f"Perfil de {self.user.username} - {self.public_title}"

# 3. DISPONIBILIDAD (CALENDARIO)
class Availability(models.Model):
    asesor = models.ForeignKey(AsesorProfile, on_delete=models.CASCADE, related_name='availabilities')
    day_of_week = models.IntegerField("Día (0=Lunes, 6=Domingo)", choices=[
        (0, 'Lunes'), (1, 'Martes'), (2, 'Miércoles'), (3, 'Jueves'), 
        (4, 'Viernes'), (5, 'Sábado'), (6, 'Domingo')
    ])
    start_time = models.TimeField("Hora Inicio")
    end_time = models.TimeField("Hora Fin")

# 4. RESERVAS (EL NEGOCIO)
class Appointment(models.Model):
    STATUS_CHOICES = (
        ('PENDIENTE', 'Pendiente de Aprobación'),
        ('POR_PAGAR', 'Aprobada - Esperando Pago'),
        ('CONFIRMADA', 'Pagada y Confirmada'),
        ('FINALIZADA', 'Realizada'),
        ('CANCELADA', 'Cancelada'),
    )

    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='appointments', null=True, blank=True)
    asesor = models.ForeignKey(AsesorProfile, on_delete=models.CASCADE, related_name='asesor_appointments')
    
    # Fechas siempre en UTC
    start_datetime = models.DateTimeField("Fecha/Hora Inicio")
    end_datetime = models.DateTimeField("Fecha/Hora Fin")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDIENTE')
    meeting_link = models.URLField("Enlace a Sala de Reunión (Zoom/Meet)", max_length=200, blank=True, null=True, help_text="Pega aquí tu link de Zoom o Google Meet personal")
    created_at = models.DateTimeField(auto_now_add=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    client_city = models.CharField(max_length=100, null=True, blank=True)
    client_address = models.CharField(max_length=255, null=True, blank=True)
    client_postal_code = models.CharField(max_length=20, null=True, blank=True)
    
    # Campo para guardar el "Token" de la tarjeta (NO la tarjeta real)
    payment_token = models.CharField(max_length=100, null=True, blank=True)
    def __str__(self):
        return f"Cita: {self.client} con {self.asesor} ({self.status})"

# 5. PAGOS Y RESEÑAS
class Payment(models.Model):
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=0)
    transaction_id = models.CharField("ID MercadoPago", max_length=100)
    payment_status = models.CharField(max_length=20, default='approved')
    created_at = models.DateTimeField(auto_now_add=True)

class Review(models.Model):
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE)
    rating = models.IntegerField("Estrellas (1-5)", choices=[(i, i) for i in range(1, 6)])
    comment = models.TextField("Comentario")
    created_at = models.DateTimeField(auto_now_add=True)

class Review(models.Model):
    asesor = models.ForeignKey(AsesorProfile, on_delete=models.CASCADE, related_name='reviews')
    client = models.ForeignKey(User, on_delete=models.CASCADE) # Quien escribe la reseña
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE) # Una reseña por cita
    
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)]) # 1 a 5 estrellas
    comment = models.TextField("Comentario", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reseña de {self.client.first_name} para {self.asesor}"