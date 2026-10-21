# Monitor AMBA 2026

Sistema de inteligencia político-institucional para los 40 municipios bonaerenses del AMBA.
Especificación: [docs/ESPECIFICACION.md](docs/ESPECIFICACION.md).

## Estado: Fase 1 (extractor + validación)
- `scripts/extraer.py` · `normalizar.py` · `detectar_cambios.py` · `validar.py` (+ `comun.py`).
- 8 CSV en `data/actual/` (esquemas de la spec; ver [diccionario](docs/diccionario_datos.md)), historial en `data/historico/`.
- Workflow manual: *Actions → Actualizar MONITOR AMBA → Run workflow* (programación semanal **desactivada**).
- **No se ha logrado ninguna extracción real todavía**: el entorno de desarrollo no tenía acceso al portal. Ver [informe de calidad](docs/informe_calidad.md).

## Uso local
```bash
pip install -r requirements.txt
python -m pytest -q                                   # pruebas offline con datos sintéticos
python scripts/extraer.py --municipios avellaneda,vicente_lopez,tres_de_febrero
python scripts/validar.py --modo prueba --informe docs/informe_calidad.md
```
Sin APIs pagas ni IA: solo `requests`, `beautifulsoup4`, `lxml`. Respeta `robots.txt` y no elude bloqueos. Detalles: [metodología](docs/metodologia.md).

## Directorio de vinculación institucional
Relevamiento de canales de contacto (Ceremonial y Protocolo, Relaciones Institucionales, Secretaría Privada, Despacho/Jefatura, Concejo Deliberante, Mesa de Entradas) en `data/actual/03_amba_contactos_protocolo.csv`.
`python scripts/contactos.py --municipios avellaneda,vicente_lopez,tres_de_febrero` · workflow manual *Relevar contactos institucionales AMBA*. Independiente de los indicadores. Ver [metodología](docs/metodologia.md).
