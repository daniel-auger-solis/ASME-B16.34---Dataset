import os
import json
import glob
import time
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import Optional
from pypdf import PdfReader, PdfWriter

# Configuración del cliente
API_KEY = "AQ.Ab8RN6JYfWhnvpnnkTwKsuSyBbcjMcHwHjER2dcqSH1Cr6NLyw"
client = genai.Client(api_key=API_KEY)

ARCHIVO_DESTINO = "historico_materiales.json"

# =====================================================================
# 1. LISTA DE PÁGINAS A PROCESAR (Matriz completa)
# =====================================================================
paginas_materiales = [
    (158, 159),# Group 3.2
]

# =====================================================================
# 2. ESQUEMAS DE PYDANTIC
# =====================================================================
class VectoresPresionTemperatura(BaseModel):
    temperaturas: list[str]  
    class_150: list[float]
    class_300: list[float]
    class_600: list[float]
    class_900: list[float]
    class_1500: list[float]
    class_2500: list[float]
    class_4500: list[float]

class TiposDeClase(BaseModel):
    standard_class_A: Optional[VectoresPresionTemperatura] = None
    special_class_B: Optional[VectoresPresionTemperatura] = None

class SistemaUnidades(BaseModel):
    SI: Optional[TiposDeClase] = None
    US: Optional[TiposDeClase] = None

class EsquemaMatrizASME(BaseModel):
    materiales: list[str]
    unidades: SistemaUnidades

# =====================================================================
# 3. DETECCIÓN DEL ARCHIVO BASE
# =====================================================================
archivos_encontrados = glob.glob("ASME-B16.34*.pdf")
if not archivos_encontrados:
    raise FileNotFoundError("No se encontró ningún archivo PDF que comience con 'ASME-B16.34'.")

nombre_archivo_original = archivos_encontrados[0]
print(f"📄 Archivo maestro detectado: {nombre_archivo_original}\n")

# =====================================================================
# 4. BUCLE PRINCIPAL DE PROCESAMIENTO
# =====================================================================
reader = PdfReader(nombre_archivo_original)
archivo_recortado = "temp_loop_recortado.pdf"

configuracion = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=EsquemaMatrizASME,
    temperature=0.0  
)

prompt = (
    "Analiza el fragmento de documento técnico adjunto. Extrae la lista de materiales del encabezado "
    "y mapea por completo las tablas de presión-temperatura separando por el sistema de unidades "
    "(SI o US) y por el tipo de clase (Standard Class A o Special Class B)."
)

for i, (pag_inicio, pag_fin) in enumerate(paginas_materiales, start=1):
    print(f"\n🚀 [Progreso {i}/{len(paginas_materiales)}] Procesando rango: Páginas {pag_inicio} al {pag_fin}...")
    
    # 4.1. Generar el recorte PDF de este bloque
    writer = PdfWriter()
    for num_pagina in range(pag_inicio - 1, pag_fin):
        writer.add_page(reader.pages[num_pagina])
    
    with open(archivo_recortado, "wb") as f_out:
        writer.write(f_out)
        
    # 4.2. Subir fragmento a Gemini
    archivo_pdf_ia = client.files.upload(file=archivo_recortado)
    
    # 4.3. Llamar a la API
    print("   Esperando respuesta de Gemini...")
    try:
        response = client.models.generate_content(
            model='gemini-flash-lite-latest',
            contents=[archivo_pdf_ia, prompt],
            config=configuracion
        )
        nuevos_datos = json.loads(response.text)
    except Exception as e:
        print(f"   ❌ Error procesando este bloque: {e}")
        if os.path.exists(archivo_recortado): os.remove(archivo_recortado)
        continue # Salta al siguiente bloque si falla la API
        
    # Limpieza del archivo temporal local de esta iteración
    if os.path.exists(archivo_recortado): 
        os.remove(archivo_recortado)

    # 4.4. Cargar histórico actual para control de duplicados
    if os.path.exists(ARCHIVO_DESTINO):
        with open(ARCHIVO_DESTINO, "r", encoding="utf-8") as f:
            try:
                historico = json.load(f)
            except json.JSONDecodeError:
                historico = {}
    else:
        historico = {}

    # Extraer materiales acumulados hasta el momento
    materiales_existentes = set()
    for contenido in historico.values():
        if "materiales" in contenido:
            materiales_existentes.update(contenido["materiales"])

    # Validar duplicados de la iteración actual
    nuevos_materiales = nuevos_datos.get("materiales", [])
    repetidos = materiales_existentes.intersection(set(nuevos_materiales))

    proceder_a_guardar = True

    if repetidos:
        print(f"   ⚠️  [ALERTA] Materiales repetidos detectados en este bloque:")
        for mat in repetidos:
            print(f"      - {mat}")
        
        # Interrupción controlada por terminal
        respuesta = input("   ¿Deseas guardar este bloque de todas formas? (s/n): ").strip().lower()
        if respuesta != 's':
            proceder_a_guardar = False
            print("   ❌ Bloque omitido por el usuario.")

    # 4.5. Guardar los datos en una nueva llave correlativa
    if proceder_a_guardar:
        numero_carga = len(historico) + 1
        nueva_llave = f"carga_{numero_carga}"
        
        historico[nueva_llave] = nuevos_datos
        
        with open(ARCHIVO_DESTINO, "w", encoding="utf-8") as f:
            json.dump(historico, f, indent=4, ensure_ascii=False)
            
        print(f"   ✅ Guardado exitoso en '{ARCHIVO_DESTINO}' -> llave: '{nueva_llave}'")
    
    # Pausa de cortesía para no saturar la tasa de transferencia por segundo de la API (Rate Limits)
    time.sleep(1)

print("\n🎯 ¡Todos los bloques de la lista han sido procesados!")