# Metodología técnica del extractor (Fase 1)

## Flujo
`extraer.py` → (`normalizar.py` fusiona e incrementa) → (`detectar_cambios.py` genera alertas) → `validar.py` valida y emite el informe.
`python scripts/extraer.py --municipios avellaneda,vicente_lopez,tres_de_febrero` · `python scripts/validar.py`.

## Acceso al portal (https://municipiosargentinos.net/)
1. Se lee `robots.txt`. 404 = sin restricciones declaradas. Si no se puede verificar (error, 5xx, bloqueo), **no se consulta** (falla cerrada) y se registra incidencia.
2. Pausa mínima de 2 s entre solicitudes (o el `Crawl-delay` si es mayor); User-Agent identificable.
3. 401/403/429 y bloqueos de red: sin reintentos ni evasión; incidencia y continuación.
4. Las páginas de cada municipio se encuentran por **enlaces de la portada** (igualdad exacta del nombre) o por `url_portal_municipio` en la config; nunca por patrón de URL. Enlace ausente/ambiguo => incidencia `PAGINA_NO_ENCONTRADA`.
5. Solo se lee texto; scripts y contenido de la página nunca se ejecutan ni se interpretan como instrucciones.

## Interpretación
Pares etiqueta→valor desde tablas, listas de definición y líneas `Etiqueta: valor`; la etiqueta normalizada (sin tildes) debe **coincidir exactamente** con un sinónimo de `CAMPOS_PORTAL`. Valores originales conservados en `05` (`valor_obtenido`); el índice nunca se recalcula. Etiquetas repetidas con valores distintos => incidencia `CONTRADICCION_INTERNA` (se conserva el primero).
**La estructura HTML real del portal no pudo observarse** (ver informe de calidad): los sinónimos son supuestos a ajustar tras la primera ejecución real.

## Trazabilidad y confianza
Cada valor de 04 tiene fila en 05 (fuente, URL, fecha de consulta, método, SHA-256 parcial del HTML). Portal agregador => `MEDIO`.
La página de metodología se verifica textualmente (50/35/15 % y tope de 40 puntos) y se guarda su huella; un cambio de huella genera la alerta `CAMBIO_METODOLOGICO`.

## Incremental
- 01: upsert; nunca se pisa un valor con vacío. 04: nueva fila solo si algún dato cambió. 05: solo fuentes nuevas. 06: id estable; lo que deja de ocurrir pasa a `RESUELTA`.
- Versión previa en `data/historico/AAAA-MM-DD/` antes de modificar. Sin cambios reales no se reescribe nada (no hay commits vacíos).
- Primera ejecución = línea de base sin alertas. Alertas solo entre capturas comparables.

## Alertas (`config/reglas_alertas.json`)
Umbral 10 puntos (escala 0-100) → MEDIA; ≥ 20 → ALTA. Cambio de semáforo → ALTA siempre. Ranking: ≥ 10 posiciones MEDIA, menos INFORMATIVA (umbral propio, configurable). Cambios políticos (intendente CRITICA; coalición/partido/situación legislativa ALTA; presidencia HCD MEDIA). La severidad es prioridad de seguimiento, no responsabilidad legal.
`variacion_absoluta = actual − anterior`; `variacion_relativa_pct = (actual − anterior)/|anterior|·100` (vacío si anterior = 0).

## Fuera de alcance de la Fase 1
Fuentes políticas oficiales (intendentes, HCD, contactos), CABA, matriz integrada, tablero, programación semanal, versión de metodología por captura en 04.
