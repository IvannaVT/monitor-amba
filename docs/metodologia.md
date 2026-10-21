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

## Interpretación de la ficha (`scripts/parser_ficha.py`)
1. La página se convierte en fragmentos de texto en orden de documento, con su sección (`<h1>-<h6>` o títulos conocidos: *Datos clave*, *Cómo se compone su índice*, *Control*, *Intendente*) y el JSON embebido (solo se parsea).
2. Etiquetas por reglas: igualdad o palabras contenidas (sin tildes), prefiriendo la sección; p. ej. `servicios`+`seguridad` ≠ `seguridad`; `relevamiento propio`/`transparencia activa` ≠ `transparencia` (pilar) ≠ `ASAP`.
3. Valor: tras `:` en el mismo fragmento, en los fragmentos siguientes o, en tarjetas "valor, etiqueta", antes (la orientación se decide por votación entre etiquetas sin ambigüedad). Cada valor se usa una vez.
4. Se rechazan y se informan: porcentajes en puntajes (pesos del pilar), puntajes sobre otra escala (`25 / 50`), valores fuera de 0-100, población sin "2022"/"censo" visible, fechas incompletas.
5. Intendente/partido/frente/asunción/población/sección van a 01 con trazabilidad en 05 (nivel `MEDIO`; `BAJO` si el nombre se infiere por posición). Son datos del portal y quedan **pendientes de verificación oficial**; nombre y apellido no se separan y la coalición no se completa.
6. `DATOS_NO_ENCONTRADOS` lista faltantes, secciones vistas, etiquetas no reconocidas (`sección > etiqueta = valor`) y valores rechazados. Con `--diagnostico DIR` se guardan el HTML público y un volcado de estructura (artefacto `monitor-amba-datos`, carpeta `diagnostico/`; no se commitea).

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
