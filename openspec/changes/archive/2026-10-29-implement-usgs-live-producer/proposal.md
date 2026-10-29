# Proposal

## Why

El servicio `producer` ya existe en Compose y conecta con Kafka, pero permanece inactivo: no consulta USGS ni publica eventos. Este cambio completa esa responsabilidad conforme al contrato documentado, sin confundir el esqueleto de infraestructura validado con un pipeline funcional.

## What Changes

- Implementar en el productor la consulta periódica del feed móvil `all_day.geojson`, usando la frecuencia aproximada de 60 segundos ya documentada, e interpretar solo respuestas/feed y campos documentados.
- Filtrar los eventos cuyo `properties.type` sea `earthquake`; comparar `id` y `properties.updated` con el estado persistente para publicar eventos nuevos y revisiones posteriores, con el ID como clave Kafka.
- Guardar únicamente `id` y `updated` confirmados en SQLite dentro de un volumen exclusivo del productor; no persistir eventos sísmicos en PostgreSQL.
- Publicar en el topic `earthquakes-live` un envelope JSON UTF-8 con `source`, `ingested_at` (Unix ms UTC), `mode: live` y el evento GeoJSON original en `event`; usar `id` como clave y actualizar estado solo después del ACK.
- Limitar cada lectura/envío a tres intentos totales, con esperas progresivas de 20 y 40 segundos; registrar el fallo agotado y mantener el estado válido. Ante un fallo de envío, continuar con los demás eventos.
- Omitir y registrar individualmente una feature sin `id` o `updated`, sin fabricar valores. Rechazar una respuesta que no sea JSON/GeoJSON válido, sin publicar sus eventos.
- Añadir pruebas reproducibles con fixtures GeoJSON sintéticos y clientes HTTP/Kafka simulados. Las pruebas no dependerán de peticiones reales a USGS.
- Mantener la topología de cinco servicios y readiness ya implementados; añadir únicamente el volumen persistente del estado del productor y su configuración. No incluir procesamiento del consumidor, persistencia de eventos sísmicos en PostgreSQL, endpoints funcionales, replay, histórico, ni cambios de frontend.

El nombre del topic, la representación JSON y la política concreta de reintentos son decisiones de implementación aprobadas para este cambio; no se atribuyen a las fuentes USGS ni modifican sus formatos.

## Capabilities

### New Capabilities

<!-- No se introduce una capacidad nueva: el comportamiento pertenece a la ingesta USGS existente. -->

### Modified Capabilities

- `usgs-live-ingestion`: concretar escenarios verificables para feed vacío o inválido, errores de red, fallos/recuperación de Kafka y pruebas deterministas, manteniendo los requisitos existentes de fuente, versionado, envelope y ACK.

## Impact

- Código: `backend/observatorio/producer.py`, pruebas backend y configuración necesaria del productor/volumen SQLite.
- Contratos: delta de OpenSpec a `usgs-live-ingestion`; no se modifican las especificaciones base, `CONTRATO-API` ni otros documentos fuente.
- Runtime: reutiliza el servicio `producer`, Kafka, la red y readiness del Compose actual; añade solo el volumen de datos del productor, sin modificar la topología.

## División recomendada

No dividir la consulta, deduplicación/versionado y publicación: son etapas acopladas por la regla de actualizar el estado solo tras el ACK. Mantener el trabajo del consumidor, la persistencia de eventos, replay y API en cambios separados, como ya delimita la arquitectura.
