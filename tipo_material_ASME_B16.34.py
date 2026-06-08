import os
import json
import glob
import time
from google import genai
from google.genai import types
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

# Configuración del cliente
API_KEY = "AQ.Ab8RN6JYfWhnvpnnkTwKsuSyBbcjMcHwHjER2dcqSH1Cr6NLyw"
client = genai.Client(api_key=API_KEY)

# Archivo de destino
ARCHIVO_DESTINO = "especificaciones_materiales.json"

# =====================================================================
# 1. ESQUEMA 100% FIJO
# =====================================================================
class RegistroMaterial(BaseModel):
    material: str             # Guardará "A105", "A216 WCB", etc.
    nominal_designation: str  # Guardará "C-Si", "C-Mn-Si", etc.
    tipo_producto: str        # Guardará "Forgings", "Castings", etc.

class EsquemaEspecificaciones(BaseModel):
    materiales: list[RegistroMaterial]

# =====================================================================
# 2. DETECCIÓN DEL ARCHIVO BASE ASME
# =====================================================================
archivos_encontrados = glob.glob("ASME-B16.34*.pdf")
if not archivos_encontrados:
    raise FileNotFoundError("No se encontró ningún archivo PDF que comience con 'ASME-B16.34'.")

nombre_archivo_original = archivos_encontrados[0]

# =====================================================================
# 3. BUCLE PÁGINA POR PÁGINA
# =====================================================================
reader = PdfReader(nombre_archivo_original)
archivo_temporal = "temp_pagina_individual.pdf"

configuracion = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=EsquemaEspecificaciones,
    temperature=0.0  
)

prompt = (
    "Analiza minuciosamente la tabla del documento adjunto (Table 1 - Material Specification List).\n"
    "Extrae la información fila por fila de las columnas Forgings, Castings, Plates, Bars, Tubular y Bolting.\n\n"
    "Para cada registro:\n"
    "1. En 'material' combina 'Spec. No.' and 'Grade' (ej: 'A216 WCB'). Si 'Grade' es '...', usa solo 'Spec. No.' (ej: 'A105').\n"
    "2. En 'nominal_designation' escribe el valor de su fila.\n"
    "3. En 'tipo_producto' escribe la columna donde lo encontraste (Forgings, Castings, Plates, Bars, Tubular o Bolting)."
)

# Páginas 49 a 56
for num_pagina in range(55, 56):
    print(f"\n📖 Procesando Página {num_pagina}...")
    
    # Cortar página
    writer = PdfWriter()
    writer.add_page(reader.pages[num_pagina - 1])  
    with open(archivo_temporal, "wb") as f_out:
        writer.write(f_out)
        
    # Subir y consultar a Gemini
    archivo_pdf_ia = client.files.upload(file=archivo_temporal)
    
    try:
        response = client.models.generate_content(
            model='gemini-flash-lite-latest',
            contents=[archivo_pdf_ia, prompt],
            config=configuracion
        )
        nuevos_datos = json.loads(response.text)
    except Exception as e:
        print(f"   ❌ Error en página {num_pagina}: {e}")
        if os.path.exists(archivo_temporal): os.remove(archivo_temporal)
        continue
        
    if os.path.exists(archivo_temporal): 
        os.remove(archivo_temporal)

    # =====================================================================
    # 4. GUARDADO HISTÓRICO Y NUEVO CONTROL DE DUPLICADOS (3 OPCIONES)
    # =====================================================================
    if os.path.exists(ARCHIVO_DESTINO):
        with open(ARCHIVO_DESTINO, "r", encoding="utf-8") as f:
            try:
                historico = json.load(f)
            except json.JSONDecodeError:
                historico = {}
    else:
        historico = {}

    # Mapear qué materiales ya existen en el JSON de páginas previas
    materiales_existentes = set()
    for datos_pagina in historico.values():
        for item in datos_pagina.get("materiales", []):
            materiales_existentes.add(item["material"])

    nuevos_materiales = {item["material"] for item in nuevos_datos.get("materiales", [])}
    repetidos = materiales_existentes.intersection(nuevos_materiales)

    proceder_a_guardar = True

    if repetidos:
        print(f"   ⚠️  [ALERTA] Se detectaron materiales que ya existen en el histórico:")
        for mat in repetidos: 
            print(f"      - {mat}")
        
        # Presentamos el nuevo menú interactivo de 3 opciones
        print("\n   ¿Qué deseas hacer con los datos de esta página?")
        print("   [1] Guardar TODO (incluyendo los duplicados)")
        print("   [2] NO guardar nada (omitir la página completa)")
        print("   [3] Guardar SOLO los nuevos (filtrar y eliminar duplicados)")
        
        opcion = input("   Selecciona una opción (1, 2 o 3): ").strip()

        if opcion == '2':
            proceder_a_guardar = False
            print(f"   ❌ Página {num_pagina} descartada por completo.")
            
        elif opcion == '3':
            # Filtramos la lista dejando únicamente los elementos cuyo "material" NO esté registrado
            nuevos_datos["materiales"] = [
                item for item in nuevos_datos["materiales"] 
                if item["material"] not in materiales_existentes
            ]
            
            # Si resulta que todos los materiales de la página eran duplicados, la lista quedará vacía
            if not nuevos_datos["materiales"]:
                proceder_a_guardar = False
                print(f"   ℹ️  Al filtrar los duplicados, no quedaron materiales nuevos. Página {num_pagina} omitida.")
            else:
                print(f"   ✂️  Duplicados eliminados con éxito. Conservando solo los elementos nuevos.")
                
        elif opcion == '1':
            print(f"   🔄 Procediendo a guardar el bloque completo tal como vino...")
            
        else:
            proceder_a_guardar = False
            print(f"   ❌ Opción inválida. Por seguridad, la página {num_pagina} no fue guardada.")

    # Guardado final en el archivo histórico si corresponde
    if proceder_a_guardar:
        llave_pagina = f"pagina_{num_pagina}"
        historico[llave_pagina] = nuevos_datos
        
        with open(ARCHIVO_DESTINO, "w", encoding="utf-8") as f:
            json.dump(historico, f, indent=4, ensure_ascii=False)
            
        print(f"   ✅ Datos indexados en '{ARCHIVO_DESTINO}' bajo la llave: '{llave_pagina}'")
        
    time.sleep(1)

print("\n🎯 Proceso completado exitosamente con el nuevo filtro selectivo.")