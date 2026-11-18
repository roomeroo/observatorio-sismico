# Proposal

## Why

El servicio `consumer` conecta con Kafka y PostgreSQL, pero no se suscribe a ningún topic ni procesa mensajes. Sin consumo transaccional, validación, cuarentena y persistencia idempotente, los eventos publicados por el productor no llegan al almacenamiento sísmico ni quedan protegidos frente a redelivery.

## What Changes

- Suscribir el consumidor existente al topic live configurado por `KAFKA_TOPIC` (por defecto `earthquakes-live`) y procesar su envelope JSON; mantener la topología actual de cinco servicios.
- Validar los mensajes y eventos de acuerdo con los campos y formatos documentados, conservar el evento original y el contexto de extracción, y transformar timestamps Unix en milisegundos a UTC sin perder su significado o unidades originales.
- Añadir persistencia PostgreSQL transaccional para las versiones recibidas y una representación actual por `event_id`, sin permitir que una revisión anterior reemplace una versión más reciente.
- Registrar de forma durable el mensaje original rechazado, el motivo y su referencia Kafka (topic, partición y offset) antes de confirmar su offset.
- Confirmar cada offset solo después del commit de la transacción correspondiente. Ante indisponibilidad de PostgreSQL, no confirmar el mensaje y permitir reanudar su procesamiento cuando la base vuelva a estar disponible.
- Hacer idempotentes los efectos de versiones repetidas y redeliveries. No añadir transacciones distribuidas entre Kafka y PostgreSQL.
- Añadir pruebas reproducibles con envelopes sintéticos, Kafka simulado o controlable y PostgreSQL de prueba; no depender de llamadas reales a USGS.
- Mantener fuera del cambio el enriquecimiento Natural Earth, API funcional, adquisición histórica, replay, frontend y cambios del contrato HTTP. No borrar ni recrear volúmenes para instalar el esquema.

El consumidor usará `mode: live` en este cambio; el procesamiento de replay queda fuera de alcance. Se conservará la estructura actual de dependencias y se aplicará el esquema de base de forma compatible con el volumen PostgreSQL existente.

## Decisiones resueltas

- Evento sin `id` o con `updated` ausente/inválido: Se rechaza y transfiere a cuarentena (`QUARANTINE`) con motivo explícito (`MISSING_OR_INVALID_ID_OR_UPDATED`), sin inventar identidades ni versiones fallback y sin bloquear la partición.
- Distinción entre redelivery idéntica y conflicto de payloads con mismo `(event_id, updated)`: Si el hash de contenido/payload es idéntico, se trata como redelivery idempotente (sin duplicar registros). Si el contenido difiere con la misma tupla `(event_id, updated)`, el mensaje entrante se envía a cuarentena con motivo `PAYLOAD_CONFLICT_SAME_VERSION`, preservando la versión previa almacenada y evitando sobreescrituras silenciosas.

## Capabilities

### New Capabilities

<!-- No se introduce una capacidad nueva: el comportamiento pertenece al procesamiento de eventos existente. -->

### Modified Capabilities

- `event-processing-and-quality`: concretar el consumo del envelope live, la validación y cuarentena durable, el orden commit de PostgreSQL/offset y la idempotencia/versionado de F-05 y F-06.

## Impact

- Código y configuración: `backend/observatorio/consumer.py`, módulos de validación/persistencia que sean necesarios, `backend/postgres/init/001-create-schema.sql` o mecanismo de esquema compatible, pruebas backend y configuración `KAFKA_TOPIC` del consumidor en `compose.yaml`.
- Sistemas: consumer group Kafka existente, topic live del productor y PostgreSQL persistente existente; no se añade un servicio, broker, base de datos ni dependencia externa salvo que la investigación de implementación demuestre que es imprescindible.
- Contratos: delta de OpenSpec únicamente para la capacidad existente `event-processing-and-quality`; no se modifican especificaciones base ni `CONTRATO-API`.

## División recomendada

Mantener en este cambio el consumo, la escritura del historial y estado actual, y la cuarentena porque el orden de transacción y confirmación del offset los acopla. Dejar el enriquecimiento geográfico, las consultas API y el replay en cambios independientes.
