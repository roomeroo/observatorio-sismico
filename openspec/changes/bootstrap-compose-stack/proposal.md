# Proposal

## Why

El repositorio aporta el frontend y los contratos, pero todavía no dispone de los cinco servicios backend ni de una configuración Compose con la que arrancarlos juntos. Un baseline ejecutable permite comprobar desde el principio la topología, la red y la disponibilidad de las dependencias, antes de incorporar la lógica sísmica.

## What Changes

- Establecer `compose.yaml` en la raíz con servicios separados para productor, Kafka, consumidor, PostgreSQL y API.
- Proporcionar el esqueleto mínimo y reproducible de contenedores Python para productor, consumidor y FastAPI, manteniendo sus procesos y responsabilidades separados.
- Configurar nombres de servicio para comunicación interna, readiness/reintentos, volúmenes persistentes y retención limitada de Kafka.
- Incluir configuración de ejemplo sin credenciales e instrucciones para construir, arrancar, comprobar y detener el baseline.
- Hacer que la API escuche dentro del contenedor en `0.0.0.0:8000`; limitar cualquier puerto publicado al host local según la opción de túnel documentada.

Este cambio cubre la infraestructura inicial y el arranque de los servicios. **No** implementa aún extracción USGS, publicación/consumo funcional de eventos, modelo de datos sísmicos, enriquecimiento, idempotencia, endpoints funcionales del contrato, estadísticas, replay, Angular ni despliegue Netlify/ngrok.

## Capabilities

### New Capabilities

<!-- No se crea una capacidad nueva: el comportamiento pertenece al runtime existente. -->

### Modified Capabilities

- `runtime-deployment-and-publication`: precisar los criterios verificables del baseline Compose de cinco servicios, su readiness/persistencia y su conectividad interna.

## Impact

- Añade configuración Compose, Dockerfile(s), esqueleto de aplicaciones backend, configuración de entorno de ejemplo e instrucciones operativas.
- Afecta al runtime local Docker y a los requisitos existentes `NF-01`, `NF-03` y `NF-05`.
- No cambia el contrato HTTP ni los requisitos de procesamiento y presentación; el arranque de este baseline no demuestra por sí solo el pipeline completo.

