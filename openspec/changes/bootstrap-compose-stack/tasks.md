# Tasks

## 1. Crear el esqueleto ejecutable de los servicios Python

- [ ] 1.1 Crear la estructura backend, un Dockerfile Python reproducible y dependencias fijadas; verificar que la imagen se construye y que los comandos separados de productor, consumidor y API arrancan.
- [ ] 1.2 Implementar readiness y reintentos de conexión para productor→Kafka, consumidor→Kafka/PostgreSQL y API→PostgreSQL, sin añadir todavía extracción USGS, procesamiento de eventos ni rutas funcionales; verificar con pruebas de arranque/reintento o comprobaciones de conexión aisladas.

## 2. Configurar Kafka y PostgreSQL para desarrollo local

- [ ] 2.1 Seleccionar y fijar imágenes compatibles, configurar Kafka de nodo único en KRaft con listener interno alcanzable por nombre de servicio y retención limitada; verificar la configuración efectiva del broker y que no necesita un servicio adicional.
- [ ] 2.2 Configurar PostgreSQL con inicialización base y volumen con nombre; añadir comprobaciones de salud reales para broker y base de datos; verificar que ambos servicios alcanzan estado saludable y que la retención de Kafka está acotada.

## 3. Orquestar los cinco servicios en Compose

- [ ] 3.1 Crear `compose.yaml` en la raíz con los cinco servicios `producer`, `kafka`, `consumer`, `postgres` y `api`, conectarlos mediante DNS de Compose y expresar dependencias de readiness; verificar `docker compose config` y que no se define un sexto servicio obligatorio.
- [ ] 3.2 Configurar el listener de Uvicorn en `0.0.0.0:8000`, publicar únicamente la API en loopback cuando se use ngrok en el host, y no publicar Kafka/PostgreSQL; verificar bindings y conectividad interna de los tres servicios Python.
- [ ] 3.3 Añadir el volumen de datos de Kafka y configurar restart/readiness de los servicios; verificar que el arranque en frío y un reinicio de Kafka o PostgreSQL no hacen pasar un fallo de dependencia por un arranque correcto.

## 4. Documentar configuración y arranque seguro

- [ ] 4.1 Añadir `.env.example` sin secretos y actualizar las reglas de exclusión para el `.env` local, conservando las reglas existentes; verificar que los valores de ejemplo son placeholders y que `.env` queda excluido de Git.
- [ ] 4.2 Documentar en una guía del backend los requisitos locales, preparación de variables, `docker compose up --build -d`, comprobación del estado, parada sin borrar volúmenes y alcance todavía no funcional del pipeline; verificar que cada comando está disponible y concuerda con Compose.

## 5. Verificar la integración del baseline

- [ ] 5.1 En un entorno con Docker Compose, ejecutar el procedimiento desde un checkout limpio y comprobar que quedan activos los cinco servicios, que los procesos Python alcanzan sus dependencias y que la API escucha en el puerto interno esperado.
- [ ] 5.2 Escribir un dato de prueba local en PostgreSQL, reiniciar el contenedor y comprobar que persiste; verificar además que Kafka conserva la política de retención acotada y que ni broker ni base de datos se exponen al host/túnel.
- [ ] 5.3 Ejecutar `docker compose down` sin borrar volúmenes y confirmar que los datos siguen disponibles al volver a arrancar; dejar explícito que este smoke test no valida ingesta USGS, idempotencia, contrato API, replay ni frontend.

