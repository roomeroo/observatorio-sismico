# Guion de la defensa

Sigue el orden de las diapositivas del [README](../README.md). Frases cortas, para decirlas con tus palabras. Tiempo orientativo: **8–10 min** más la demostración.

---

## Apertura (diapositivas 1–2) · 1 min

«He construido un sistema que recoge terremotos de USGS, los limpia, los asigna a un país, los guarda y los enseña en un panel web. La pregunta que responde es: dónde hay actividad sísmica y cómo se compara con un periodo histórico equivalente.

La arquitectura son los cinco servicios obligatorios en Docker: productor, Kafka, consumidor, PostgreSQL y API. Delante, ngrok da HTTPS y el panel está en Netlify. No he añadido infraestructura extra.»

---

## Extracción (3–5) · 2 min

«Uso tres fuentes: el feed en vivo, el histórico de 2025 y el catálogo de países de Natural Earth.

El feed devuelve siempre las últimas 24 horas completas, así que el productor compara `id` y `updated` con un estado persistente y publica solo lo nuevo. Marca la versión como publicada **después** de que Kafka confirme; si se cae justo en medio, reenvía y el consumidor lo tolera.

El histórico lo bajé por meses. Si un mes llegara a 20.000 resultados lo subdivido en vez de truncarlo; no ocurrió, el máximo fue julio con 2.684. En total son 18.302 eventos en 12 consultas, y puedo repetirlo sin red porque guardo los ficheros y un manifiesto.

Guardo qué consulté, cuándo y cuántos registros, y de cada sondeo del feed guardo la latencia y los descartes con su motivo, por ejemplo explosiones o voladuras de cantera.

Sobre tipos: `time` es ocurrencia, `updated` es la revisión de USGS, y no son la hora de ingesta. La magnitud puede ser nula, y la conservo como nula; la profundidad va en kilómetros. Y el texto `place` no lo uso para el país, porque el país se calcula con geometría.»

---

## Calidad (6–8) · 2 min

«Medí las seis dimensiones con SQL, y está automatizado en un script, aunque el enunciado no lo exigía.

Lo primero que vi es que el feed repite casi 5.000 features para solo 190 eventos reales. Eso se resuelve deduplicando por versión.

Completitud: ninguna magnitud nula en estos datos, pero sí muchos eventos sin país: el 16 % en vivo y el 78 % en el histórico. Eso no es un error: son terremotos en el mar. Validez y unicidad: cero violaciones en el estado actual, porque lo inválido se rechaza antes de guardar y va a cuarentena con su motivo.

La exactitud es lo más interesante. Contrasté el país del polígono con el texto de `place` y coincide en el 71,6 % de los eventos comparables. Los fallos son costas e islas pequeñas que el catálogo de baja resolución no recoge. Lo dejo documentado como limitación, no lo escondo.

Decisiones: no imputo cero a un nulo, porque desconocido no es cero; no asigno un evento marino al país más cercano, y no rechazo magnitudes ni profundidades negativas solo por serlo.»

---

## Modelado (9–12) · 2 min

«El país lo asigno con Shapely, con un árbol espacial, así que cada punto cuesta logaritmo del número de polígonos. La regla es explícita: el borde cuenta como dentro; si cae en varias entidades gana el código menor y lo marco como ambiguo; si no cae en ninguna, país nulo, "Sin país asignado".

El modelo tiene dos granos: una fila por evento para analizar y una fila por versión para auditar. Eso es lo que hace al sistema idempotente. En la tabla de ejemplo: si llega el mismo mensaje dos veces no cambia nada; si llega una revisión posterior se actualiza; si llega tarde una versión antigua se guarda en el historial pero no sustituye a la actual.

El `UPDATE` solo ocurre si la versión nueva es más reciente, todo en una transacción, y el offset de Kafka se confirma después.

Los índices son sobre tiempo, país y tiempo, y magnitud. Y los medí: con 1,8 millones de filas una búsqueda tarda 0,2 milisegundos con índice y entre 50 y 90 sin él.»

---

## Análisis (13–17) · 2 min

«El panel tiene mapa con tamaño por magnitud y color por profundidad, la magnitud nula se ve como "ND", tabla accesible, y un panel de estado con la última ingesta y avisos.

Los filtros son coherentes: si pongo magnitud mínima 5, cambian a la vez el mapa, el recuento, los gráficos, la tabla y también la media histórica.

La comparación con 2025 la hago con las mismas condiciones: misma magnitud mínima y 365 días como denominador, contando los días sin eventos. Con magnitud 4, las últimas 24 horas son 26 frente a 50 de media; con 5, son 14 frente a 5,8.

Tres conclusiones con datos de 2025, magnitud 4 o más, todo el mundo:
1. Una sola secuencia domina el año: el 30 de julio hubo 645 eventos, 12,9 veces la media diaria, por el terremoto de Kamchatka de magnitud 8,8.
2. Se cumple Gutenberg-Richter: cada unidad de magnitud divide los eventos entre unos diez.
3. La mayoría es marina y superficial: 78 % sin país y tres de cada cuatro a menos de 70 km.

Matiz importante: tras un gran terremoto, comparar las últimas 24 horas con una media anual exagera; por eso el panel avisa de que el último periodo puede estar incompleto.»

---

## Reflexión (18–21) · 2 min

«Medí la complejidad con tres tamaños. El diccionario es O(1), la lista O(n), y PostgreSQL con índice O(log n). Con 1,8 millones de filas: 0,04 microsegundos, 21 milisegundos y 0,2 milisegundos. Las filas de más las generé por réplica, las marqué como sintéticas y las dejé fuera del análisis real.

Lo que aprendí: un índice acelera las búsquedas, pero una agregación completa sigue siendo lineal.

Con 100 millones de filas, sin índice cada consulta tardaría segundos y el diccionario no cabría en memoria. Con índice sigue siendo rápido, pero habría que particionar por mes, usar un índice BRIN en el tiempo y pre-agregar por hora y país. Todo eso se hace en el mismo PostgreSQL.

Costes: la pila entera usa unos 0,85 GB de RAM y la base 14 MB. Lo que más crece son los payloads originales, por eso tienen retención de 7 días y deduplicación por hash. Una cuota gratuita no es coste cero: está el tiempo, la electricidad y el mantenimiento.

Limitaciones: el catálogo de baja resolución, que no reconcilia eventos retirados, y que el panel solo funciona con el equipo y el túnel encendidos. Mejoras: catálogo de 50 metros, reconciliación periódica con USGS y agregados precalculados.»

---

## Pruebas y despliegue (22–27) · 1 min

«Las 11 pruebas de aceptación están cubiertas: hay 115 tests de backend contra PostgreSQL real, 6 unitarios y 9 e2e, y la matriz con pasos y evidencias está en `docs/aceptacion.md`. Todo el código, la documentación y los resultados están en el repositorio.»

---

## Demostración en directo · 4–5 min

Antes de empezar, comprueba que está todo arriba:

```bash
docker compose --profile tunnel ps          # todo "healthy"
curl http://127.0.0.1:4040/api/tunnels      # la URL debe ser la de frontend/public/config.json
```

1. **En vivo.** Abre <https://adrian-observatorio-sismico.netlify.app>. Señala «Operativo», el mapa, los gráficos y «Última ingesta». *«Este panel consulta mi API, no USGS directamente.»*
2. **Filtro.** Pon «Magnitud mín.» a 5 → cambian mapa, recuento, gráficos, tabla y media 2025. Quita el filtro.
3. **Tabla y mapa enlazados.** Pulsa una fila: el mapa vuela al evento y aparece su ficha.
4. **Reproducción** (≈ 35 s):
   ```bash
   docker compose run --rm producer python -m observatorio.replay \
     --from 2025-03-28T06:00:00Z --to 2025-03-28T12:00:00Z --speed 600
   ```
   En el panel: «Datos → Reproducción». Aparece **REPRODUCCIÓN**, 23 eventos únicos. *«Mandé 25 mensajes: 23 eventos, un duplicado y una revisión antigua; el duplicado no suma y la antigua no sustituye. Los datos en vivo no han cambiado.»*
5. **Túnel.** `docker compose stop ngrok` → en ≤ 60 s aparece el banner conservando la última lectura. `docker compose start ngrok` → se recupera solo.
6. **Idempotencia (opcional).** Muestra `docs/capturas/17-tests.txt` o la matriz de `docs/aceptacion.md`.

Plan B si falla el túnel: abre el panel en local (`cd frontend && npm start`, <http://localhost:4200>) y usa las capturas de `docs/capturas/`.

---

## Preguntas probables

**¿Por qué Kafka y no escribir directo en la base?**
Separa el ritmo de recogida del de procesamiento. Si el consumidor se para, Kafka guarda los mensajes y reanuda desde el último offset confirmado. Además, es un requisito del enunciado.

**¿Qué pasa si el mensaje llega dos veces?**
Nada: la clave `(event_id, updated)` es única y el `ON CONFLICT` lo ignora. Si el contenido difiere con la misma versión, va a cuarentena como conflicto.

**¿Por qué «Sin país asignado» y no el país más cercano?**
Porque muchos terremotos ocurren en el mar y atribuirlos a un país sería inventar un dato. Lo documento y lo cuento aparte.

**¿Por qué solo el 71,6 % de exactitud?**
Es un contraste con el texto `place`, que nombra el país del pueblo de referencia. Los fallos son costas e islas pequeñas que el catálogo de 110 m no recoge. Con uno de 50 m mejoraría.

**¿Qué pasa con un evento que desaparece del feed?**
No lo borro: puede haber salido de la ventana de 24 h sin que USGS lo haya retirado. La reconciliación de eventos eliminados es una ampliación; está declarada como limitación.

**¿Y si el sistema estuvo parado más de 24 horas?**
El hueco se recupera con el histórico (FDSN), con el mismo comando, usando el intervalo que falta.

**¿Por qué la comparación usa magnitud 4?**
Porque el histórico solo contiene M ≥ 4. Comparar todas las magnitudes recientes con esa media sería comparar cosas distintas; lo corregí para que ambos lados usen el mismo umbral.

**¿Se puede predecir un terremoto con esto?**
No. Son estadísticas descriptivas, no predicción ni evaluación de riesgo.

**¿Qué cambiarías con 100 millones de filas?**
Partición mensual, índice BRIN en el tiempo, tabla de agregados por hora y país y réplicas de lectura. Sin añadir componentes.

**¿Qué decisión técnica es tuya?**
Elige una y prepárala. Sugerencias: marcar la versión como publicada solo tras la confirmación de Kafka; el esquema `replay` aislado en vez de mezclar con los datos en vivo; o la corrección de la comparación para que use el mismo umbral de magnitud en ambos lados.
