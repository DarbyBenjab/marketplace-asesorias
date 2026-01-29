from django.contrib import admin
from .models import User, AsesorProfile, Availability, Appointment
from .models import SoporteUsuario

# 1. Configuración para ver los USUARIOS
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'first_name', 'role', 'is_verified')
    list_filter = ('role', 'is_verified')
    search_fields = ('email', 'first_name', 'username')

# 2. Configuración para ver los PERFILES DE ASESOR (Donde apruebas)
class AsesorProfileAdmin(admin.ModelAdmin):
    # Columnas que verás en la lista
    list_display = ('get_nombre_completo', 'public_title', 'hourly_rate', 'is_approved')
    
    # ESTO ES LO QUE BUSCAS: Te permite poner el tick ✅ directamente en la lista
    list_editable = ('is_approved',) 
    
    # Filtros a la derecha (Para ver solo los "No Aprobados")
    list_filter = ('is_approved',)
    
    # Buscador
    search_fields = ('user__first_name', 'user__email', 'public_title')

    # Función para mostrar el nombre bonito
    def get_nombre_completo(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"
    get_nombre_completo.short_description = 'Asesor'

# 3. Registramos todo
admin.site.register(User, UserAdmin)
admin.site.register(AsesorProfile, AsesorProfileAdmin)
admin.site.register(Availability)
admin.site.register(Appointment)

@admin.register(SoporteUsuario)
class SoporteAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'nombre', 'email', 'fecha_envio', 'leido')
    list_filter = ('tipo', 'leido', 'fecha_envio')
    search_fields = ('nombre', 'email', 'mensaje')
    readonly_fields = ('fecha_envio',)