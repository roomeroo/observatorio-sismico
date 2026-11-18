# Frontend Documentation

## Arquitectura del Frontend

El frontend de la aplicación está construido con **Angular** y hace uso de **Leaflet** y **Leaflet.markercluster** para la representación cartográfica interactiva de los terremotos.

La aplicación consta de dos vistas principales:
1. **Vista Histórica / API:** Consulta periódica de eventos a la API REST o archivo de demostración.
2. **Real-Time Map:** Vista en tiempo real impulsada por WebSocket que renderiza eventos sísmicos en vivo de forma incremental.

---

## EarthquakeContext / EarthquakeService API

El contexto y servicio de terremotos (`EarthquakeService` en Angular) actúa como el bus de eventos sísmicos en vivo para los componentes de la interfaz.

### Tipos de Datos

```typescript
export interface EarthquakeGeometry {
  type: string;
  coordinates: [number, number, number?]; // [longitud, latitud, profundidad_km]
}

export interface EarthquakeProperties {
  mag: number | null;
  place: string;
  time: number;
  updated?: number;
  country_name?: string | null;
  [key: string]: unknown;
}

export interface EarthquakeEvent {
  type?: string;
  id?: string;
  geometry?: EarthquakeGeometry;
  properties?: EarthquakeProperties;
  data?: {
    id?: string;
    magnitude?: number;
    place?: string;
    coordinates?: [number, number, number?];
  };
}
```

### Métodos del Servicio

- `connect(url?: string): Observable<EarthquakeEvent>`
  Abre la conexión WebSocket con el endpoint `/ws/earthquakes` del backend (o URL provista) y expone un flujo reactivo (`Observable`) con los eventos entrantes.
- `send(message: unknown): void`
  Envía un mensaje o acción al backend por el socket abierto.
- `disconnect(): void`
  Cierra ordenadamente el WebSocket y limpia los recursos.

---

## Componente `RealTimeMapComponent` y Módulo `RealTimeMapModule`

- **Lazy Loading:** El mapa carga dinámicamente Leaflet y MarkerCluster mediante `import('leaflet')` solo cuando el usuario ingresa a la vista, optimizando los paquetes iniciales.
- **Renderizado Dinámico:** Al recibir un evento en la suscripción, se crea un `circleMarker` configurando el radio según la magnitud y el color según la profundidad sísmica.
- **Agrupamiento (Clustering):** Integra `MarkerClusterGroup` para mantener un rendimiento óptimo ante alta densidad de eventos.
