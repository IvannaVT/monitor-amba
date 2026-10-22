# Insumo preliminar: Ejecutivo municipal AMBA (corte 22/10/2026)

**No es dato validado ni está en `data/actual/`.** Proviene de `origen/Base_Ejecutivo_AMBA_2026-10-22.xlsx` (entregada por el usuario) y se regenera con `python scripts/importar_insumo.py`.
Alcance: Ejecutivo municipal, intendente en funciones, partido, alianza y Protocolo/Ceremonial. HCD y otras dimensiones quedan fuera.

| Archivo | Contenido |
|---|---|
| `municipios.csv` | 41 jurisdicciones (40 municipios + CABA): intendente, condición, partido, alianza, tipo y URL de la fuente de autoridad |
| `contactos.csv` | 50 vías: `categoria`, `tipo_casilla` (proveedor vs dominio oficial), `uso_oficial`, `evidencia` depurada y `evidencia_original` |
| `fuentes.csv` | 82 fuentes con `tipo_fuente` (MUNICIPAL / PROVINCIAL / SECUNDARIA_WIKIPEDIA) |
| `discrepancias.csv` | Faltantes y diferencias; `proceso` = ACTIONS (se puede relevar) o MANUAL (requiere documento municipal) |

Reglas: los estados originales se conservan (ningún contacto pasa a vigente); la evidencia depurada solo recorta texto y omite números de emergencia (el original queda en `evidencia_original`); un correo de proveedor público (p. ej. Gmail) figure o no en el sitio oficial queda "a confirmar"; los datos del directorio provincial no sobrescriben los actuales sin contraste con documentación municipal reciente.
