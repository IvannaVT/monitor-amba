# Diccionario de datos

Esquemas literales de la especificación (sec. 16). Generado desde `scripts/comun.py::ESQUEMAS`.
Formato: UTF-8 con BOM, `;`, decimales con coma, fechas `AAAA-MM-DD`, faltantes en blanco.

Nota: `señales_control` conserva la `ñ` tal como figura en la especificación.

## 01_amba_municipios.csv

- Capa: I/II · Estado: Fase 1: identificación + 7 indicadores del portal. Política/Concejo: Fase 2.
- Clave natural: `municipio_id`
- Columnas (35): `municipio_id`, `municipio`, `seccion_electoral`, `poblacion_2022`, `sitio_oficial`, `intendente_nombre`, `intendente_apellido`, `intendente_nombre_completo`, `intendente_condicion`, `fecha_asuncion`, `partido_politico`, `frente_electoral`, `coalicion_actual`, `presidente_hcd`, `total_bancas`, `bancas_oficialismo`, `bancas_aliadas`, `bancas_oposicion`, `bancas_independientes`, `bancas_sin_verificar`, `porcentaje_oficialismo`, `porcentaje_apoyo_confirmado`, `situacion_legislativa`, `indice_global`, `ranking_provincial`, `transparencia_puntaje`, `transparencia_semaforo`, `servicios_seguridad_puntaje`, `seguridad_puntaje`, `control_puntaje`, `email_municipal`, `telefono_municipal`, `sitio_hcd`, `fecha_verificacion`, `snapshot_id`

## 02_amba_concejos_bloques.csv

- Capa: I · Estado: Solo esquema (Fase 2).
- Clave natural: `municipio_id, bloque_id`
- Columnas (14): `municipio_id`, `bloque_id`, `bloque_nombre`, `partido_o_frente`, `bancas`, `presidente_bloque_nombre`, `presidente_bloque_apellido`, `posicion_frente_intendente`, `tipo_alineamiento`, `documento_respaldo`, `url_fuente`, `fecha_composicion`, `fecha_verificacion`, `snapshot_id`

## 03_amba_contactos_protocolo.csv

- Capa: I · Estado: Solo esquema (Fase 2).
- Clave natural: `municipio_id, organismo, dependencia`
- Columnas (17): `municipio_id`, `organismo`, `dependencia`, `tipo_contacto`, `responsable_nombre`, `responsable_apellido`, `cargo`, `email_institucional`, `telefono_institucional`, `interno`, `direccion`, `horario_atencion`, `sitio_web`, `url_fuente`, `fecha_verificacion`, `estado_contacto`, `snapshot_id`

## 04_amba_indicadores.csv

- Capa: II · Estado: Implementado (extracción del portal).
- Clave natural: `municipio_id, snapshot_id`
- Columnas (37): `municipio_id`, `snapshot_id`, `fecha_extraccion`, `fecha_actualizacion_portal`, `indice_global`, `ranking_provincial`, `ranking_pares`, `grupo_comparacion`, `transparencia_puntaje`, `transparencia_relevamiento_propio`, `transparencia_asap`, `transparencia_semaforo`, `presupuesto_publicado`, `ejecucion_publicada`, `servicios_seguridad_puntaje`, `seguridad_puntaje`, `homicidios_tasa_100k`, `homicidios_periodo`, `victimas_homicidio_ultimo_anio`, `victimas_homicidio_anio`, `cobertura_agua_pct`, `cobertura_cloacas_pct`, `cobertura_gas_pct`, `control_puntaje`, `ultimo_fallo_htc`, `ejercicio_fallo_htc`, `señales_control`, `cargos_htc_monto`, `multas_htc_monto`, `presupuesto_total`, `presupuesto_anio`, `gasto_por_habitante`, `gasto_periodo`, `empleados_municipales`, `cargos_presupuestados`, `tipo_dato_empleo`, `empleo_periodo`, `url_fuente`

## 05_amba_fuentes.csv

- Capa: transversal · Estado: Implementado.
- Clave natural: `fuente_id`
- Columnas (16): `fuente_id`, `municipio_id`, `entidad`, `campo_verificado`, `valor_obtenido`, `fuente_tipo`, `organismo`, `documento_titulo`, `documento_url`, `fecha_documento`, `periodo_referencia`, `fecha_consulta`, `metodo_extraccion`, `nivel_confianza`, `observaciones`, `snapshot_id`

## 06_amba_incidencias.csv

- Capa: transversal · Estado: Implementado.
- Clave natural: `incidencia_id`
- Columnas (14): `incidencia_id`, `municipio_id`, `campo`, `tipo_incidencia`, `descripcion`, `url_afectada`, `fuente_1`, `fuente_2`, `impacto`, `accion_recomendada`, `estado_resolucion`, `fecha_deteccion`, `fecha_ultima_revision`, `snapshot_id`

## 07_caba_institucional.csv

- Capa: I · Estado: Solo esquema (Fase 2).
- Clave natural: `jurisdiccion_id`
- Columnas (24): `jurisdiccion_id`, `jurisdiccion`, `jefe_gobierno_nombre`, `jefe_gobierno_apellido`, `cargo`, `condicion_funcional`, `partido_politico`, `coalicion_actual`, `fecha_asuncion`, `legislatura_total_bancas`, `legislatura_bancas_oficialismo`, `legislatura_bancas_aliadas`, `legislatura_bancas_oposicion`, `legislatura_bancas_sin_verificar`, `presidente_legislatura`, `situacion_legislativa`, `contacto_protocolo`, `email_institucional`, `telefono_institucional`, `sitio_gobierno`, `sitio_legislatura`, `fuentes`, `fecha_verificacion`, `snapshot_id`

## 08_amba_alertas_cambios.csv

- Capa: III · Estado: Implementado (indicadores, semáforo, política, metodología).
- Clave natural: `alerta_id`
- Columnas (20): `alerta_id`, `municipio_id`, `snapshot_anterior`, `snapshot_actual`, `fecha_deteccion`, `fecha_evento`, `capa_analitica`, `categoria_alerta`, `variable`, `valor_anterior`, `valor_actual`, `variacion_absoluta`, `variacion_relativa_pct`, `severidad`, `impacto_institucional`, `descripcion`, `estado_verificacion`, `fuente_documental`, `url_fuente`, `estado_seguimiento`

## Valores controlados

- `nivel_confianza`: ALTO, MEDIO, BAJO, SIN_VERIFICAR (los datos del portal agregador se registran como MEDIO; el ALTO se reserva a documentos oficiales primarios).
- `transparencia_semaforo`: VERDE, AMARILLO, ROJO.
- `situacion_legislativa`: MAYORIA_PROPIA, MAYORIA_CON_ALIADOS, MINORIA, EMPATE, SIN_VERIFICAR.
- `severidad`: CRITICA, ALTA, MEDIA, INFORMATIVA.
- `tipo_incidencia` (extractor): ACCESO_BLOQUEADO_RED, ROBOTS_NO_VERIFICABLE, PROHIBIDO_POR_ROBOTS, ACCESO_DENEGADO_HTTP, LIMITE_SOLICITUDES_429, ERROR_HTTP, TIMEOUT, ERROR_CONEXION, PAGINA_NO_ENCONTRADA, DATOS_NO_ENCONTRADOS, CONTRADICCION_INTERNA, METODOLOGIA_NO_CONFIRMADA.
- `municipio_id`: provisorio `ba_<slug>`; se migrará al código INDEC una vez validado (`config/municipios_amba.csv::indec_codigo`, hoy vacío para no inventar).
- `municipio_id = GLOBAL` en 05/06/08: hechos que no pertenecen a un municipio (metodología).

## Capa II (40 municipios): campos añadidos o con reglas nuevas
- `04.cargos_presupuestados` (añadida respecto de la especificación): puestos fijados en el presupuesto, **no personas**. Nunca se vuelca en `empleados_municipales`, que solo recibe `EMPLEADOS_OCUPADOS`. `tipo_dato_empleo` y `empleo_periodo` indican el tipo y el año de la medición.
- `01.intendente_nombre` / `intendente_apellido`: solo se separan cuando el nombre completo tiene exactamente dos palabras sin partículas, guiones, apóstrofos ni puntos. En cualquier otro caso quedan vacíos (se registra la incidencia `NOMBRE_NO_SEPARADO`) y se resuelven en `config/intendentes_nombres.csv` (revisión manual, coincidencia exacta del nombre completo). `intendente_nombre_completo` conserva siempre el texto original.
- `config/municipios_amba.csv`: `indec_codigo` (formato `06xxx`, único) e `indec_fuente`. El código lo publica el portal en los metadatos de la ficha; **no está verificado contra el nomenclador oficial del INDEC** y por eso no reemplaza todavía a `municipio_id`.

## Directorio de vinculación institucional (03_amba_contactos_protocolo.csv)
Esquema de la especificación + 3 columnas al final: `responsable_nombre_completo` (nombre publicado, sin honorífico), `fecha_consulta` (cuándo se leyó la fuente) y `evidencia` (texto breve de la fuente donde se halló el dato).
- Clave natural: `municipio_id` + `organismo` + `dependencia`. Una fila por dependencia; varios correos/teléfonos/internos se unen con `; `.
- `dependencia` (canónicas): Ceremonial y Protocolo; Relaciones Institucionales; Secretaría Privada del Intendente; Despacho del Intendente / Jefatura de Gabinete; Presidencia del Concejo Deliberante; Secretaría del Concejo Deliberante; Mesa de Entradas; Contacto institucional general.
- `tipo_contacto` (tipo de canal): `ESPECIFICO_PROTOCOLO`, `RELACIONES_INSTITUCIONALES`, `DESPACHO`, `CONCEJO`, `CONTACTO_ALTERNATIVO`.
- `estado_contacto`: `VIGENTE_CONFIRMADO` (el mismo canal figura en 2+ páginas oficiales distintas, o la página muestra una actualización de los últimos 12 meses); `PUBLICADO_SIN_VIGENCIA_CONFIRMADA` (publicado en el sitio oficial, sin corroboración ni fecha); `DEPENDENCIA_SIN_CANAL` (la oficina figura pero sin correo/teléfono atribuible); `NO_ENCONTRADO`.
- `sitio_web`: formulario o página de contacto cuando existe; `url_fuente`: página donde se halló; el resto de las páginas y la confianza (`ALTO`: vigente confirmado; `MEDIO`: un solo bloque; `BAJO`: contacto general) están en `05` (`entidad = contacto:<dependencia>`).
- `fecha_verificacion` queda vacía si no hay canal; `responsable_nombre`/`apellido` solo se completan con la regla conservadora de dos palabras.

### 03: estados y canales (actualización)
`estado_contacto`: `VIGENTE_CONFIRMADO` (verificado por una persona), `PUBLICADO_CORROBORADO` (2+ páginas oficiales o fecha reciente), `PUBLICADO_SIN_VIGENCIA_CONFIRMADA`, `DEPENDENCIA_SIN_CANAL`, `NO_ENCONTRADO`. Dependencias alternativas nuevas: *Prensa y Comunicación*, *Contacto institucional general del Concejo Deliberante* y *Prensa y Comunicación del Concejo Deliberante* (`CONTACTO_ALTERNATIVO`, solo si se hallan). `config/contactos_verificados.csv`: municipio_id;dependencia;canal;fecha_verificacion;metodo;verificado_por.
