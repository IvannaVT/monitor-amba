# Metodología técnica del extractor (Fase 1)

## Flujo
`extraer.py` → (`normalizar.py` fusiona e incrementa) → (`detectar_cambios.py` genera alertas) → `validar.py` valida y emite el informe.
`python scripts/extraer.py --municipios avellaneda,vicente_lopez,tres_de_febrero` · `python scripts/validar.py`.

## Acceso al portal (https://municipiosargentinos.net/)
1. Se lee `robots.txt`. 404 = sin restricciones declaradas. Si no se puede verificar (error, 5xx, bloqueo), **no se consulta** (falla cerrada) y se registra incidencia.
2. Pausa mínima de 2 s entre solicitudes (o el `Crawl-delay` si es mayor); User-Agent identificable.
3. 401/403/429 y bloqueos de red: sin reintentos ni evasión; incidencia y continuación.
4. **Prioridad:** la URL de `url_portal_municipio` (config; hoy las fichas `/m/<slug>/` de Avellaneda, Vicente López y Tres de Febrero). Solo si falta o responde 404/410 se usa como respaldo la portada (enlaces y rutas `/m/<slug>/` halladas en su HTML, igualdad exacta del nombre). Nunca se deduce una URL por patrón.
5. Cada incidencia de acceso guarda código HTTP, URL final, redirecciones y causa (URLs sin query ni credenciales). Redirecciones a otro dominio no se siguen. 403/401/429/robots/red: sin reintento ni respaldo.
6. Tipos: `PAGINA_AUSENTE` (404/410), `PAGINA_NO_ENCONTRADA` (portada leída OK pero sin enlace y sin URL configurada), `ACCESO_DENEGADO_HTTP`, `LIMITE_SOLICITUDES_429`, `ERROR_HTTP`, `RESPUESTA_VACIA`, `REDIRECCION_EXTERNA`, etc.
7. El informe de ejecución (`--informe-ejecucion`) separa solicitudes exitosas, respuestas bloqueadas, páginas ausentes, otros errores y municipios con datos extraídos.
8. Solo se lee texto; scripts y contenido de la página nunca se ejecutan ni se interpretan como instrucciones.

## Interpretación
Pares etiqueta→valor desde tablas, listas de definición, líneas `Etiqueta: valor` y JSON embebido (`__NEXT_DATA__`, `application/json`, solo parseado); la etiqueta normalizada (sin tildes) debe **coincidir exactamente** con un sinónimo de `CAMPOS_PORTAL`. Valores originales conservados en `05` (`valor_obtenido`); el índice nunca se recalcula. Etiquetas repetidas con valores distintos => incidencia `CONTRADICCION_INTERNA` (se conserva el primero).
Los sinónimos son supuestos a ajustar con la ficha real: cuando faltan campos, la incidencia `DATOS_NO_ENCONTRADOS` lista las etiquetas no reconocidas de la ficha.

## Trazabilidad y confianza
Cada valor de 04 tiene fila en 05 (fuente, URL, fecha de consulta, método, SHA-256 parcial del HTML). Portal agregador => `MEDIO`.
La página de metodología se verifica textualmente (50/35/15 % y tope de 40 puntos) y se guarda su huella; un cambio de huella genera la alerta `CAMBIO_METODOLOGICO`.

## Incremental
- 01: upsert; nunca se pisa un valor con vacío. 04: nueva fila solo si algún dato difiere del último valor conocido de cada campo (las ausencias no cuentan como cambio); las alertas comparan el último y el anterior valor no vacío. 05: solo fuentes nuevas. 06: id estable; lo que deja de ocurrir pasa a `RESUELTA`.
- Versión previa en `data/historico/AAAA-MM-DD/` antes de modificar. Sin cambios reales no se reescribe nada (no hay commits vacíos).
- Primera ejecución = línea de base sin alertas. Alertas solo entre capturas comparables.

## Alertas (`config/reglas_alertas.json`)
Umbral 10 puntos (escala 0-100) → MEDIA; ≥ 20 → ALTA. Cambio de semáforo → ALTA siempre. Ranking: ≥ 10 posiciones MEDIA, menos INFORMATIVA (umbral propio, configurable). Cambios políticos (intendente CRITICA; coalición/partido/situación legislativa ALTA; presidencia HCD MEDIA). La severidad es prioridad de seguimiento, no responsabilidad legal.
`variacion_absoluta = actual − anterior`; `variacion_relativa_pct = (actual − anterior)/|anterior|·100` (vacío si anterior = 0).

## Fuera de alcance de la Fase 1
Fuentes políticas oficiales (intendentes, HCD, contactos), CABA, matriz integrada, tablero, programación semanal, versión de metodología por captura en 04.
