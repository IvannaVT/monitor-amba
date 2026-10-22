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

### Estructura real de la ficha (capturada el 2026-10-15; fixtures en `tests/fixtures/real/`)
- *Datos clave*: pares etiqueta/valor consecutivos (`Índice municipal` → `56,2 / 100`; `Puesto en la provincia` → `44 de 135`; `Hogares con cloacas` → `80,3 %`; `Seguridad, puntaje entre pares` → `47,1 / 100`; `Población (Censo 2022)` → `367.554`).
- Valores compuestos en un solo texto: `4,4 cada 100.000 hab. (17 víctimas en 2025)` (el período sale de la etiqueta: `promedio 2023-2025`) y `4.125 (2026-08; empleados ocupados, ...)` / `3.720 (2023; cargos presupuestados, ...)`. Los **cargos presupuestados no son empleados**: se registran solo en `05` (`cargos_presupuestados`) y `tipo_dato_empleo` = `CARGOS_PRESUPUESTADOS`; `empleados_municipales` se completa únicamente con `EMPLEADOS_OCUPADOS`. "No declara cuántos empleados tiene" no genera dato.
- *Cómo se compone su índice*: `Transparencia` → `(50 % del índice): 50,0 de 100.`; el peso (50/35/15 %) se guarda como observación y nunca como puntaje. `Semáforo de transparencia: amarillo.` aparece solo en algunas fichas; **no se infiere** del color del índice (`Índice verde/amarillo`).
- *Control*: `Último fallo del Tribunal de Cuentas sobre la rendición (2024): aprobada con observaciones.` y `N señales de control registradas ...`.
- *Intendente*: etiqueta (`Intendenta:` / `Intendente interino:`), nombre y `, en funciones desde el AAAA-MM-DD (PARTIDO · frente X).`. La condición solo se registra si la etiqueta dice interino/suplente/reemplazante; el primer elemento entre paréntesis va a `partido_politico` (el portal no distingue partido y frente) y todo queda pendiente de verificación oficial.
- *Partidos para comparar* y *Fuentes* contienen datos de otros municipios o citas: se ignoran. La sección electoral y el grupo salen de la oración `(sección electoral 3, grupo Conurbano)`.

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

## Capa II: ampliación a los 40 municipios
1. **URL de fichas.** Solo están confirmadas las 3 de prueba. `scripts/descubrir_urls.py` (workflow: `accion=descubrir_urls`) reúne enlaces `/m/<slug>/` de la portada, de `/ranking/` y de los sitemaps declarados en `robots.txt`; nunca deduce rutas. Cada candidata se confirma con HTTP 200 y título igual al municipio; si no, queda como incidencia (`URL_NO_ENCONTRADA`, `TITULO_NO_COINCIDE`, `PAGINA_AUSENTE`...). `--aplicar` completa `config/municipios_amba.csv` solo con lo verificado y sin pisar valores; el archivo se descarga como artefacto y se commitea a mano.
2. **Extracción completa.** `accion=extraer`, `modo=completo` (`--municipios todos`). Mismo parser validado; los municipios sin URL verificada generan `PAGINA_NO_ENCONTRADA` y quedan en blanco. No hay programación semanal ni commit automático (`confirmar_cambios=false` por defecto).
3. **Cambio de intendente.** Si cambia `intendente_nombre_completo`, los datos de esa persona (nombre, apellido, condición, asunción, partido, frente, coalición) se reemplazan en bloque, aun por vacíos, para no heredar los de la gestión anterior. Se genera la alerta `CAMBIO_INTENDENTE`.
4. **Cambio de esquema.** Si el encabezado de un CSV cambia, el archivo se migra y la versión previa se conserva en `data/historico/AAAA-MM-DD/`.

## Directorio de vinculación (contactos): relevamiento independiente
`python scripts/contactos.py --municipios avellaneda,vicente_lopez,tres_de_febrero` (workflow `relevar_contactos.yml`, manual; no usa ni modifica la extracción de indicadores).
1. **Fuentes.** Solo los sitios oficiales de `config/sitios_oficiales.csv` (no se deducen dominios). El sitio debe responder 200, nombrar al municipio en título/encabezados y estar en `gob.ar`/`gov.ar` (o marcarse `CONFIRMADO` a mano); si no, no se relevan contactos (`SITIO_NO_VERIFICADO`). Se siguen hasta 12 enlaces por municipio con indicios de contacto/autoridades/organigrama, y el sitio oficial externo del Concejo si la portada lo enlaza. `robots.txt` obligatorio, pausa de 2 s, sin reintentos ante 403/429.
2. **Atribución.** Un correo/teléfono se asigna a una dependencia solo si está en su mismo bloque estructural y el bloque no nombra otra dependencia; encabezado, navegación y pie nunca se atribuyen (el pie solo alimenta el contacto general). Si no se puede atribuir: `DEPENDENCIA_SIN_CANAL`.
3. **Qué se omite.** Correos de dominio no institucional y teléfonos de celular/WhatsApp (solo se cuenta que existían: `CANAL_NO_INSTITUCIONAL_OMITIDO`). Nunca se deducen correos por patrón ni se completan nombres.
4. **Alternativos.** Si no hay oficina de Protocolo/Relaciones identificable, la incidencia lo indica y quedan registrados Mesa de Entradas y el contacto general como canal alternativo.
5. **Incremental.** No se pisan datos con vacíos; si un canal deja de verse se conserva sin vigencia confirmada (`CONTACTO_YA_NO_VISIBLE`); cambio de correo/teléfono → alerta `CAMBIO_CONTACTO_OFICIAL`; nuevo canal → `NUEVO_CONTACTO_OFICIAL` (la primera ejecución es línea de base). Historial en `data/historico/`.
6. **Límites conocidos.** La atribución es heurística (estructura HTML) y debe afinarse con las páginas reales: `--diagnostico DIR` guarda el HTML público consultado. No se leen PDF, correos ofuscados por scripts ni contenido cargado por JavaScript.

### Redirecciones y sitios oficiales (contactos)
- Una redirección (301/302/303/307/308) **no es un error por sí misma**. `ClienteContactos` la sigue a mano: en cada salto verifica `robots.txt` y el certificado TLS (no se desactiva ni se reintenta) y solo la acepta si el destino es del mismo dominio (www/apex/subdominio, http→https) o un dominio listado en `dominios_verificados` de `config/sitios_oficiales.csv` (verificado a mano como oficial de ese municipio). Cualquier otro destino se rechaza como `REDIRECCION_EXTERNA` **sin solicitarlo** (p. ej. un municipio homónimo de otra provincia). Se registran código, URL final y saltos.
- `estado=CONFIRMADO`: una persona verificó que es el sitio oficial (no se exige que el título nombre al municipio). Sin confirmar, se exige título con el nombre y dominio `gob.ar`/`gov.ar`.
- El cliente de indicadores (`extraer.py`) no cambia.

### Dominio correcto por municipio (homónimos)
- Hay municipios homónimos en otras provincias (p. ej. `avellaneda.gob.ar` es Avellaneda, Santa Fe). `DOMINIOS_HOMONIMOS` (en `contactos_parser.py`) bloquea esos dominios aunque el sitio esté `CONFIRMADO` (`SITIO_HOMONIMO`), y también las páginas que se declaran de otra provincia ("Provincia de X" sin "Provincia de Buenos Aires"). Un homónimo no puede ser destino de redirección ni figurar en `dominios_verificados`, y sus correos no se aceptan.
- `validar.py` revisa `config/sitios_oficiales.csv`: https, un dominio por municipio, sin homónimos, `CONFIRMADO` con fuente.
- La evidencia que se guarda (`03.evidencia`, `05.observaciones`) se sanea: los correos no institucionales y las líneas de móvil/WhatsApp se reemplazan por una marca; lo omitido no reaparece en ningún CSV.

### Contacto general, responsables y formularios (ajustes del piloto)
- **Contacto general.** Se reconoce en encabezado/pie/lateral, bloques "contacto" y bloques "Atención al vecino / línea municipal", y se registra como `Contacto institucional general` (`CONTACTO_ALTERNATIVO`), nunca como Ceremonial u otra dependencia. Números cortos municipales (p. ej. 147) solo ahí y con etiqueta explícita.
- **Emergencias.** Nunca se registran 911, 100, 101, 102, 103, 105, 106, 107, 108, 144, 145, 136, 137 ni líneas con "emergencias", bomberos, policía, SAME o violencia (validador incluido).
- **Texto vs. `tel:`.** Prevalece el número publicado (texto visible); si el enlace difiere, queda la incidencia `TELEFONO_DISCREPANCIA` con ambos valores.
- **Responsables.** Además del bloque con canal, se toma la persona publicada justo después del título de la oficina (h3 + p, dt + dd, `strong` + texto), con o sin correo/teléfono: la dependencia queda `DEPENDENCIA_SIN_CANAL` con el responsable, su fuente en `05` y vigencia sin confirmar. Solo hermanos de tipo párrafo/texto y nombres válidos (los menús, sub-listas y descripciones no son personas); el nombre de la oficina nunca va al campo del responsable.
- **Formularios.** Los de suscripción/novedades (newsletter) no son un canal de contacto y se ignoran; solo cuenta un formulario de consulta/mensaje.
- **TLS.** Un error de certificado en `robots.txt` sigue siendo `ROBOTS_NO_VERIFICABLE` (sin desactivar la verificación).

## Directorio de vinculación: ampliación a los 40 municipios
- **Cobertura territorial** (`docs/cobertura_territorial.md`): hoy 3 sitios `CONFIRMADO` (a mano) y 37 `SIN_CONFIGURAR`. **No se dedujeron dominios**: desde el entorno de desarrollo no se podía comprobar ninguno (los sitios municipales, Wikidata y Wikipedia están bloqueados y la búsqueda web no devolvió sitios oficiales fiables).
- **Descubrimiento** (`scripts/descubrir_sitios.py`, se ejecuta en Actions): parte de los enlaces que la ficha del portal publica hacia documentos de la "Municipalidad de <nombre>" (dominios `gob.ar`/`gov.ar`; se excluyen INDEC, tribunales y otras entidades). Cada candidato se confirma con una solicitud (robots.txt y TLS respetados): HTTP 200, título/encabezados con el nombre del municipio, sin ser homónimo de otra provincia ni un dominio ya asignado. Las raíces probadas salen solo del host enlazado (y, si es un subdominio, de su dominio). Estado resultante: `VERIFICADO_TECNICAMENTE` + fuente (ficha, enlace, HTTP, título), **pendiente de confirmación humana** (`CONFIRMADO`). No pisa lo ya cargado.
- **Estados de `config/sitios_oficiales.csv`:** `SIN_CONFIGURAR`, `CANDIDATO_A_VERIFICAR`, `VERIFICADO_TECNICAMENTE` (automático), `CONFIRMADO` (humano). Los dos últimos exigen fuente.
- **Ejecución escalonada** (workflow `relevar_contactos.yml`): `modo=prueba` (3 del piloto), `modo=intermedia` (8: piloto + Lanús, Lomas de Zamora, Quilmes, Morón, San Isidro) y `modo=completo` (40). Con `descubrir_sitios=true` el descubrimiento corre antes y su config se usa **solo en esa ejecución** (se descarga como artefacto). `confirmar_cambios` es `false` por defecto y **nunca commitea en `main`** ni toca `config/`; los resultados se auditan en el artefacto/rama antes de incorporarlos.
- **Contacto general de respaldo.** Sin zonas de contacto reconocibles, en la portada o páginas de contacto se toman los correos/teléfonos institucionales del cuerpo que no pertenezcan a una dependencia (confianza `BAJO`, incidencia `CONTACTO_GENERAL_POR_RESPALDO`). Prioridad: Ceremonial/Protocolo, Relaciones Institucionales, Secretaría Privada, Despacho/Jefatura/Intendencia, Presidencia y Secretaría del Concejo, Mesa de Entradas, contacto general.

## Cobertura territorial: verificados, candidatos y pendientes
- `config/sitios_oficiales.csv` distingue: **CONFIRMADO** (3, verificado por una persona), **VERIFICADO_TECNICAMENTE** (automático en Actions; falta confirmación humana), **CANDIDATO_A_VERIFICAR** (29: dominio propuesto por el asistente a partir de conocimiento previo, **NO comprobado**) y **SIN_CONFIGURAR** (8 pendientes sin candidato: Berisso, Brandsen, Ensenada, Exaltación de la Cruz, Florencio Varela, General Las Heras, General Rodríguez, Presidente Perón). Ningún candidato figura como verificado hasta que se compruebe.
- `scripts/descubrir_sitios.py` (Actions) verifica primero cada candidato (HTTP 200, título con el municipio —admite la forma sin título, p. ej. "San Martín" por "General San Martín"—, dominio gob.ar/gov.ar, sin homónimo ni dominio repetido); si falla, intenta los enlaces de la ficha del portal; si tampoco, queda `CANDIDATO_NO_VERIFICADO` con el motivo. `--aplicar` solo actualiza `SIN_CONFIGURAR`/`CANDIDATO_A_VERIFICAR` en el espacio de trabajo (artefacto), nunca `CONFIRMADO`.
- **Fuentes alternativas** (`fuentes_alternativas`, URL https oficiales cargadas a mano): solo si el sitio principal no se puede relevar (TLS, robots, bloqueo, no verificado) se prueban, con las mismas verificaciones; la incidencia del principal se conserva. Avellaneda (TLS en `mda.gob.ar`) mantiene su incidencia y espera una fuente oficial alternativa indicada por el usuario.
- **Responsables:** también en tablas (celda + celda), con el cargo repetido ("Jefe de Gabinete: …") y en organigramas jerárquicos sin cruzar dependencias.
- **Contacto general:** si deja de verse, el dato previo se conserva sin vigencia confirmada (`CONTACTO_YA_NO_VISIBLE`); el informe separa canales específicos de generales/alternativos.

## Calidad de atribución de contactos (ejecución intermedia)
- **HCD ≠ Municipalidad.** Cada correo se clasifica por su etiqueta local (la que lo precede en su línea/contenedor): `Presidencia` → Presidencia del Concejo; `Secretaría` → Secretaría del Concejo; `Prensa/Comunicación` → *Prensa y Comunicación* (del Concejo o municipal); `Concejo/HCD` y `Contacto` (en bloques con varios canales) → *Contacto institucional general del Concejo Deliberante*. Una página es del Concejo si lo es su sitio, su título o su ruta. Nunca se agrupan correos de Presidencia, Prensa y Contacto en una misma dependencia, ni se atribuyen correos del HCD al contacto general de la Municipalidad (aunque aparezcan en su portada).
- **URL exacta.** Cada correo/teléfono se registra en `05` con la URL de la página donde apareció (no la de otro canal de la misma dependencia); `03.url_fuente` es la del primer canal y `evidencia` lista `valor @ URL` de cada uno.
- **Publicado ≠ vigente.** Un HTTP 200 o que el dato figure en el sitio no prueba que funcione. Estados: `PUBLICADO_SIN_VIGENCIA_CONFIRMADA` (un solo origen), `PUBLICADO_CORROBORADO` (2+ páginas oficiales o fecha de actualización reciente; sigue sin probar que funcione) y `VIGENTE_CONFIRMADO`, **solo** si una persona verificó el canal y lo registró en `config/contactos_verificados.csv` (método y fecha; confianza `ALTO`). `fecha_verificacion` únicamente existe en ese caso.
- **Discrepancia texto/`tel:`.** Se registra el número visible; el del enlace queda solo en la incidencia `TELEFONO_DISCREPANCIA` y nunca figura en `03`/`05`.
- **Responsables.** Además de "título + párrafo" y celda + celda: "Nombre – Cargo", "Cargo: Nombre", "Oficina: Nombre", "Cargo, Nombre" y un encabezado de nivel más profundo (h3 → h4). Si no es inequívoco, queda vacío.
- **Verificación de sitios:** `modo=candidatos` (sitios sin comprobar) y `modo=pendientes` (sin sitio), con `solo_sitios=true` para no relevar contactos.

## Validación territorial: homónimos y fuentes documentadas
- **Estados de `config/sitios_oficiales.csv`** (condiciones distintas, no intercambiables): `CONFIRMADO` (una persona), `OFICIAL_DOCUMENTADO` (el sitio figura en el listado provincial https://www.gba.gob.ar/municipios; condición **documental**), `VERIFICADO_TECNICAMENTE` (HTTP + título + provincia, automático), `CANDIDATO_A_VERIFICAR` (no comprobado) y `SIN_CONFIGURAR`. La **verificación HTTP** de un sitio documentado se registra en su propia columna `verificacion_http` (no cambia su estado); se ejecuta con `modo=documentados`.
- **Dominio no gubernamental** (fuera de gob.ar/gov.ar): solo con `OFICIAL_DOCUMENTADO`/`CONFIRMADO` y una referencia oficial explícita al municipio en `fuente` (`gba.gob.ar/municipios`); el validador lo exige.
- **Homónimos de otra provincia.** `config/dominios_homonimos.csv` (más la base fija) lista dominios que pertenecen a un municipio del mismo nombre de otra provincia (hoy: `avellaneda.gob.ar` → Santa Fe, `ituzaingo.gob.ar` → Corrientes). Esos dominios no se verifican, relevan ni aceptan como alias/redirección en ningún estado. Además, la verificación **automática** exige evidencia **positiva** de la provincia de Buenos Aires ("Provincia de Buenos Aires", "Pcia. de Bs. As." o un enlace a gba.gob.ar); una calle "Buenos Aires" no cuenta. Sin ella el candidato queda `CANDIDATO_NO_VERIFICADO`.
