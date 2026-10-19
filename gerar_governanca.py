from pathlib import Path

BASE_DIR = Path.cwd()

APPS = [
    "core_sistema",
    "clientes_agenda",
    "kanban_projetos",
    "equipe",
    "financeiro",
]

# 1. Cria o apps.py correto dentro de cada pasta em apps/
for app in APPS:
    app_dir = BASE_DIR / "apps" / app
    class_name = "".join(word.capitalize() for word in app.split("_")) + "Config"
    apps_py_content = f"""from django.apps import AppConfig

class {class_name}(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.{app}'
"""
    (app_dir / "apps.py").write_text(apps_py_content, encoding="utf-8")
    print(f"[OK] Configurado: apps/{app}/apps.py")

# 2. Atualiza o core_config/settings.py automaticamente (Idioma PT-BR, Fuso e Apps)
settings_path = BASE_DIR / "core_config" / "settings.py"
if settings_path.exists():
     texto = settings_path.read_text(encoding="utf-8")
    
    # Registra os 5 apps no INSTALLED_APPS
     if "'apps.core_sistema'" not in texto:
        apps_str = "\n    # Apps do Sistema Marcenaria\n" + "".join([f"    'apps.{a}',\n" for a in APPS])
        texto = texto.replace("'django.contrib.staticfiles',", "'django.contrib.staticfiles'," + apps_str)
    
    # Configura pasta global de templates
     texto = texto.replace("'DIRS': [],", "'DIRS': [BASE_DIR / 'templates'],")
    
    # Configura Português do Brasil e Horário
     texto = texto.replace("LANGUAGE_CODE = 'en-us'", "LANGUAGE_CODE = 'pt-br'")
     texto = texto.replace("TIME_ZONE = 'UTC'", "TIME_ZONE = 'America/Sao_Paulo'")
    
     settings_path.write_text(texto, encoding="utf-8")
     print("[OK] core_config/settings.py atualizado com os 5 apps, templates e PT-BR!")
else:
    print("[ERRO] Rode primeiro: django-admin startproject core_config .")