from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, AsesorProfile, Review
from .models import Availability

# 1. Formulario para Cliente (Registro)

class RegistroUnificadoForm(UserCreationForm):
    first_name = forms.CharField(label="Nombres", max_length=100, required=True)
    last_name = forms.CharField(label="Apellidos", max_length=100, required=True)
    
    mobile = forms.CharField(label="Teléfono Móvil", max_length=15, required=True)
    whatsapp = forms.CharField(label="WhatsApp", max_length=15, required=True)
    
    birth_date = forms.DateField(
        label="Fecha de Nacimiento", 
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=True
    )
    
    # El jefe pidió que el correo sea el usuario
    email = forms.EmailField(label="Correo Electrónico (Será tu Usuario)", required=True)

    class Meta:
        model = User
        # EL JEFE PIDIÓ ESTE ORDEN ESPECÍFICO:
        fields = ['first_name', 'last_name', 'mobile', 'whatsapp', 'birth_date', 'email']
        # Quitamos 'username' de aquí arriba para que no salga en la pantalla

    def save(self, commit=True):
        user = super().save(commit=False)
        
        # Aseguramos minúsculas aquí también
        user.email = user.email.lower() 
        user.username = user.email 
        
        user.role = 'CLIENTE'
        user.is_verified = False
        
        if commit:
            user.save()
        return user
    
    def clean_email(self):
        """Validar que el email no exista y pasarlo a minúsculas."""
        email = self.cleaned_data.get('email')
        
        # 1. Pasamos a minúsculas por si acaso
        if email:
            email = email.lower()

        # 2. Verificamos si existe
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Este correo electrónico ya está registrado. Por favor usa otro o recupera tu contraseña.")
            
        return email

# 2. Formulario de Perfil Asesor (Panel de Gestión) <--- ESTE ES EL QUE FALTABA
class PerfilAsesorForm(forms.ModelForm):
    class Meta:
        model = AsesorProfile
        fields = ['public_title', 'experience_summary', 'description', 'hourly_rate', 'meeting_link', 'cv_file']
        
        widgets = {
            'public_title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Experto en Django'}),
            'experience_summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Biografía detallada...'}),
            'hourly_rate': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 25000'}),
            'meeting_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://meet.google.com/...'}),
            'cv_file': forms.FileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'public_title': 'Título Profesional',
            'hourly_rate': 'Valor Hora (CLP)',
            # ... pon las etiquetas que quieras
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # LÓGICA DE SEGURIDAD: Si ya tiene precio, lo bloqueamos para que no lo cambie solo
        if self.instance and self.instance.pk and self.instance.hourly_rate:
            # Si el usuario NO es superuser (esto se controla en la vista, aquí solo visual)
            # Dejamos el campo readonly para que se vea pero no se toque
            self.fields['hourly_rate'].widget.attrs['readonly'] = True
            self.fields['hourly_rate'].help_text = "🔒 Precio fijado. Contacta al Admin para cambiarlo."

class DisponibilidadForm(forms.ModelForm):
    class Meta:
        model = Availability
        fields = ['day_of_week', 'start_time', 'end_time']
        labels = {
            'day_of_week': 'Día de la Semana',
            'start_time': 'Hora de Inicio (Ej: 09:00)',
            'end_time': 'Hora de Fin (Ej: 18:00)',
        }
        widgets = {
            'experience_summary': forms.Textarea(attrs={'rows': 4}),
            'meeting_link': forms.URLInput(attrs={'placeholder': 'Ej: https://meet.google.com/abc-defg-hij'})
        }

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['rating', 'comment']
        widgets = {
            'rating': forms.Select(attrs={'class': 'form-control'}), # O RadioSelect si prefieres círculos
            'comment': forms.Textarea(attrs={'rows': 3, 'placeholder': '¿Qué tal fue tu experiencia? (Opcional)'}),
        }
        labels = {
            'rating': 'Calificación (1-5 Estrellas)',
            'comment': 'Tu Opinión'
        }
        
