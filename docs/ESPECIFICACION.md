# PROMPT MAESTRO — INTELIGENCIA MUNICIPAL AMBA 2026

## ROL Y OBJETIVO

Actuá como especialista en scraping web, análisis político-institucional, gobierno abierto y construcción de bases de datos públicas argentinas.

Tu misión es construir una base de datos verificable, estructurada y actualizable sobre los gobiernos municipales del Área Metropolitana de Buenos Aires (AMBA), utilizando como fuente inicial:

https://municipiosargentinos.net/

Metodología del portal:
https://municipiosargentinos.net/metodologia/

Fecha de corte inicial: 21 de octubre de 2026.

El resultado deberá entregarse en archivos CSV descargables, aptos para Excel, Python, Power BI, SQL y sistemas de monitoreo político.

No produzcas solamente un informe narrativo: el entregable principal son los datasets completos.

## 1. ALCANCE TERRITORIAL

Relevar los siguientes 40 municipios bonaerenses del AMBA:

Almirante Brown, Avellaneda, Berazategui, Berisso, Brandsen, Campana, Cañuelas, Ensenada, Escobar, Esteban Echeverría, Exaltación de la Cruz, Ezeiza, Florencio Varela, General Las Heras, General Rodríguez, General San Martín, Hurlingham, Ituzaingó, José C. Paz, La Matanza, Lanús, La Plata, Lomas de Zamora, Luján, Malvinas Argentinas, Marcos Paz, Merlo, Moreno, Morón, Pilar, Presidente Perón, Quilmes, San Fernando, San Isidro, San Miguel, San Vicente, Tigre, Tres de Febrero, Vicente López y Zárate.

No confundir AMBA con el filtro Conurbano de 24 municipios utilizado por el portal.

Incluir CABA como jurisdicción adicional, en un archivo separado, porque su estructura institucional, Jefatura de Gobierno y Legislatura no son equivalentes a las de los municipios bonaerenses. No asignarle índices provinciales que no le correspondan.

## 2. EXTRACCIÓN DEL PORTAL PRINCIPAL

Identificar la arquitectura del sitio, enlaces internos y fichas individuales de municipios.

Las fichas pueden seguir el patrón:

https://municipiosargentinos.net/m/{slug-del-municipio}/

Utilizar únicamente rutas comprobadas mediante navegación y enlaces reales.

Extraer de cada ficha todos los datos disponibles relacionados con gobierno, intendente, indicadores, presupuesto, seguridad, servicios, transparencia y control.

Identificar la fecha de actualización de cada ficha, el período de cada indicador y los enlaces a sus fuentes.

Conservar los puntajes originales, sin sustituirlos por estimaciones.

Consultar y respetar robots.txt, condiciones de acceso, límites del servidor y restricciones técnicas. Aplicar solicitudes moderadas y reintentos limitados ante errores temporales. Si aparece HTTP 429 o una restricción persistente, no intentar eludirla: registrar la incidencia y continuar con otras fuentes públicas permitidas.

## 3. INFORMACIÓN POLÍTICO-INSTITUCIONAL

Para cada municipio registrar:

**Identificación del gobierno**
- Nombre oficial del municipio.
- Código INDEC.
- Sección electoral.
- Población del Censo 2022.
- Sitio web institucional oficial.
- Dirección de la sede municipal.
- Correo institucional general.
- Teléfono institucional general.

**Autoridad ejecutiva**
- Nombre del intendente en funciones.
- Apellido del intendente.
- Nombre completo normalizado.
- Cargo exacto.
- Condición: titular, interino, suplente o reemplazante.
- Fecha de asunción efectiva.
- Fecha de finalización prevista del mandato, cuando corresponda.
- Partido político de pertenencia.
- Frente o coalición electoral.
- Espacio político con el que actualmente se identifica.
- Condición de oficialismo u oposición respecto del gobierno provincial, como variable descriptiva documentada.
- Fuente que acredita la autoridad y su situación política.

Distinguir partido político, alianza electoral y pertenencia política actual. No utilizarlos como sinónimos.

Verificar sustituciones, licencias y cambios de autoridades hasta la fecha de corte.

## 4. COMPOSICIÓN DEL CONCEJO DELIBERANTE

Investigar el Honorable Concejo Deliberante (HCD) de cada municipio.

Extraer:

- Cantidad total de bancas.
- Nombre y apellido del presidente del HCD.
- Partido y bloque del presidente.
- Bloques políticos formalmente constituidos.
- Cantidad de concejales por bloque.
- Cantidad de bancas alineadas con el intendente.
- Cantidad de bancas de oposición.
- Cantidad de bancas independientes o de alineamiento no confirmado.
- Porcentaje de representación del oficialismo.
- Existencia o ausencia de mayoría propia.
- Existencia de acuerdos legislativos documentados.
- Fecha de constitución de la composición vigente.
- Última renovación electoral aplicable.
- URL del sitio oficial del Concejo.
- URL de la nómina de concejales o documentación respaldatoria.

Clasificar la posición legislativa del intendente como:

MAYORIA_PROPIA | MAYORIA_CON_ALIADOS | MINORIA | EMPATE | SIN_VERIFICAR.

Distinguir bancas partidarias de apoyos circunstanciales.

Las elecciones de 2025 pueden servir como antecedente, pero no sustituyen la composición vigente del Concejo. Confirmar cambios de bloque, reemplazos, licencias y autoridades posteriores.

Si no existe documentación suficiente, registrar SIN_VERIFICAR, sin inventar alianzas.

## 5. CONTACTOS INSTITUCIONALES Y PROTOCOLO

Buscar información de contacto de carácter público y oficial, especialmente:

- Oficina de Ceremonial y Protocolo.
- Dirección de Relaciones Institucionales.
- Secretaría Privada del intendente.
- Despacho del intendente.
- Presidencia del Concejo Deliberante.
- Secretaría Administrativa del Concejo.

Para cada oficina registrar:

municipio, organismo, dependencia, nombre_responsable, apellido_responsable, cargo, email_institucional, telefono_institucional, interno, direccion, horario_atencion, url_contacto, fecha_verificacion.

Priorizar los contactos publicados específicamente para protocolo, ceremonial y relaciones institucionales.

Si no existe correo de protocolo, buscar un canal institucional alternativo e identificarlo expresamente como tal.

No inventar direcciones de correo ni deducirlas de patrones. No extraer teléfonos privados, domicilios particulares o información personal no destinada al contacto institucional.

## 6. INDICADORES DE TRANSPARENCIA, SEGURIDAD Y CONTROL

Utilizar la metodología original de Municipios Argentinos.

**Índice general municipal**
- Puntaje global sobre 100.
- Posición en el ranking provincial.
- Posición entre municipios comparables.
- Grupo de comparación.
- Semáforo de transparencia.
- Rango de posiciones del análisis de sensibilidad, si está disponible.

**Pilar transparencia — ponderación 50 %**
- Puntaje del pilar sobre 100.
- Puntaje de relevamiento propio, cuando exista.
- Tipo y origen de medición.
- Publicación del presupuesto municipal.
- Publicación de ejecución presupuestaria.
- Disponibilidad de rendiciones de cuentas.
- Publicación de deuda municipal.
- Existencia de portal de transparencia o datos abiertos.
- Enlace a la documentación oficial.
- Año de referencia.

**Pilar servicios y seguridad — ponderación 35 %**
- Puntaje conjunto sobre 100.
- Puntaje específico de seguridad sobre 100, si está publicado.
- Tasa de homicidios dolosos por 100.000 habitantes.
- Período de la tasa.
- Cantidad de víctimas del último año publicado.
- Indicadores de delitos disponibles.
- Cobertura de agua de red.
- Cobertura de cloacas.
- Cobertura de gas de red.
- Mortalidad infantil, cuando esté disponible.
- Fuentes estadísticas y períodos.

No confundir el puntaje de seguridad con la tasa real de delitos ni con el puntaje conjunto de servicios y seguridad.

**Pilar control externo y judicial — ponderación 15 %**
- Puntaje del pilar sobre 100.
- Último ejercicio auditado.
- Estado del fallo del Honorable Tribunal de Cuentas.
- Cantidad de señales de control registradas.
- Existencia de cargos o multas documentados.
- Identificación de observaciones relevantes.
- Causas judiciales verificadas que el portal utiliza en su evaluación.
- Fuentes documentales.

Distinguir claramente observaciones administrativas, cargos patrimoniales, multas, investigaciones y sentencias.

No presentar una causa abierta como condena ni interpretar un puntaje bajo como prueba de corrupción.

Mantener separados los indicadores originales del portal y cualquier dato adicional.

No recalcular el índice global salvo que la tarea lo requiera expresamente y se cuente con todos los componentes y reglas metodológicas verificadas.

## 7. FUENTES COMPLEMENTARIAS Y VERIFICACIÓN

Contrastar los datos del portal con:

1. Gobierno de la Provincia de Buenos Aires: https://www.gba.gob.ar/
2. Junta Electoral de la Provincia de Buenos Aires y documentación electoral oficial.
3. Sitios web de los 40 municipios.
4. Sitios oficiales de los concejos deliberantes.
5. Boletines oficiales y decretos de designación.
6. Honorable Tribunal de Cuentas bonaerense.
7. INDEC y estadísticas oficiales.
8. Fuentes públicas oficiales de seguridad y presupuesto.

La información de los intendentes, bloques legislativos y contactos institucionales deberá verificarse con especial atención a los cambios ocurridos después de las últimas elecciones.

Si las fuentes discrepan, conservar el dato más actualizado y mejor documentado, dejando constancia del conflicto.

No considerar automáticamente vigente un directorio institucional antiguo.

## 8. ESTRUCTURA DE LOS ARCHIVOS CSV

Generar los siguientes archivos:

**01_amba_municipios.csv**

Una fila por municipio: exactamente 40 registros.

Columnas mínimas:

municipio, codigo_indec, seccion_electoral, poblacion_2022, sitio_oficial, intendente_nombre, intendente_apellido, intendente_nombre_completo, intendente_condicion, fecha_asuncion, partido_politico, frente_electoral, alineamiento_actual, presidente_hcd, partido_presidente_hcd, total_bancas, bancas_oficialismo, bancas_oposicion, bancas_no_verificadas, porcentaje_oficialismo, situacion_legislativa, indice_municipal, ranking_provincial, ranking_pares, grupo_comparacion, transparencia_puntaje, transparencia_relevamiento_propio, transparencia_origen, transparencia_semaforo, servicios_seguridad_puntaje, seguridad_puntaje, control_puntaje, señales_control, ultimo_fallo_htc, presupuesto_publicado, ejecucion_publicada, sitio_hcd, email_institucional, telefono_institucional, fuente_portal, fuente_gobierno, fuente_hcd, fecha_actualizacion_portal, fecha_verificacion.

**02_amba_concejos_bloques.csv**

Una fila por bloque político de cada HCD:

municipio, bloque, partido_o_frente, cantidad_bancas, posicion_frente_intendente, nombre_presidente_bloque, fecha_composicion, fuente_oficial, fecha_verificacion.

**03_amba_contactos_protocolo.csv**

Una fila por oficina o contacto institucional público:

municipio, organismo, dependencia, responsable_nombre, responsable_apellido, cargo, email_institucional, telefono_institucional, interno, direccion, horario_atencion, sitio_web, url_fuente, fecha_verificacion, estado_contacto.

**04_amba_indicadores.csv**

Una fila por municipio y período de relevamiento:

municipio, periodo, indice_global, transparencia_puntaje, transparencia_relevamiento_propio, transparencia_origen, servicios_seguridad_puntaje, seguridad_puntaje, control_puntaje, ranking_provincial, ranking_pares, semaforo, homicidios_tasa_100k, homicidios_periodo, victimas_homicidio_ultimo_anio, cobertura_agua_pct, cobertura_cloacas_pct, cobertura_gas_pct, ultimo_fallo_htc, señales_control, empleados_municipales, tipo_dato_empleo, periodo_empleo, gasto_por_habitante, periodo_gasto, fuente_portal, fecha_actualizacion.

**05_amba_fuentes.csv**

Una fila por fuente relevante utilizada en la verificación:

municipio, campo_verificado, valor_obtenido, fuente_tipo, organismo, titulo_documento, url, fecha_documento, periodo_referencia, fecha_consulta, nivel_confianza, observaciones.

**06_amba_incidencias.csv**

Registrar las incidencias y vacíos:

municipio, campo, tipo_incidencia, descripcion, fuente_1, fuente_2, accion_recomendada, estado_verificacion.

**07_caba_institucional.csv**

Ficha diferenciada para Ciudad Autónoma de Buenos Aires, incluyendo Jefe de Gobierno, pertenencia política, Legislatura, bloques, representación oficialista, contactos institucionales y fuentes oficiales.

No asignar a CABA puntajes de un índice que solo cubre municipios bonaerenses.

## 9. REGLAS DE CALIDAD Y NORMALIZACIÓN

- Generar CSV UTF-8 con BOM para compatibilidad con Excel.
- Usar punto y coma como separador.
- Conservar encabezados en snake_case y sin espacios.
- Utilizar fechas ISO 8601: AAAA-MM-DD.
- Guardar puntajes como números y no como cadenas acompañadas de /100.
- Usar valores numéricos consistentes y registrar separadamente las unidades.
- Para datos ausentes usar campos vacíos y documentar su causa en incidencias.
- Reservar 0 para valores comprobados como cero.
- No mezclar datos de años diferentes sin identificar períodos.
- No confundir cargos presupuestados con empleados efectivamente ocupados.
- Mantener las direcciones URL completas.
- No duplicar municipios, bloques ni registros de contacto.
- Asignar a cada municipio su código oficial cuando pueda verificarse.
- Conservar la fecha de la última consulta y el origen de los datos.

## 10. VALIDACIONES OBLIGATORIAS

Antes de entregar, comprobar:

A. Estén representados exactamente los 40 municipios solicitados.

B. No existan duplicados en el archivo maestro.

C. Los puntajes extraídos coincidan con los del portal en la fecha de consulta.

D. La suma de bancas oficiales, opositoras y no verificadas coincida con el total de concejales, cuando los datos estén completos.

E. Todo intendente tenga una fuente de validación y una condición funcional actual.

F. Cada puntaje y dato sensible a cambios políticos tenga referencia y período.

G. Los contactos de ceremonial estén identificados como específicos o alternativos.

H. Existan registros de incidencias para los campos no disponibles o contradictorios.

I. Los CSV puedan importarse correctamente y que la codificación conserve tildes y eñes.

J. La información de CABA permanezca separada de los indicadores provinciales.

## 11. ENTREGABLE FINAL

Entregar los siete CSV como archivos descargables y, si es posible, agrupados en un ZIP.

Acompañar con un breve informe de calidad que incluya:

- Total de municipios procesados.
- Cantidad de intendentes verificados.
- Cantidad de concejos con composición confirmada.
- Cantidad de contactos de protocolo encontrados.
- Porcentaje de cobertura de los campos principales.
- Fuentes consultadas.
- Fecha de corte del dataset.
- Municipios que necesitan revisión manual.
- Restricciones de acceso o extracción encontradas.

Presentar además una tabla comparativa ordenada por índice municipal, con los 40 partidos, sus intendentes, espacios políticos, posición del oficialismo en el HCD y puntajes de transparencia, seguridad y control.

**Regla final:** priorizar exactitud, trazabilidad y comparabilidad por encima de la completitud artificial. Nunca fabricar información faltante. Si un dato no se puede verificar, indicarlo y conservar la jurisdicción en la base.

Iniciar la extracción y generar los archivos reales, no únicamente describir cómo hacerlo.
