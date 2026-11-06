# Forecast QA

Auditoría de pronósticos de demanda: identifica, corrige y descarta forecasts malos, calcula métricas por producto y recomienda modelos.

## Uso

```bash
npm install
npm test
npm run dev
```

Subí un CSV largo (`producto,fecha,pronostico,real,modelo,canal`) o uno ancho con fechas en columnas. `real` es opcional.

## Qué hace

- Parseo ES/EN, `;` y decimal coma, ISO o `dd/mm/aaaa`
- Calidad: huecos, duplicados, negativos, outliers, series cortas, constantes, filtración
- Correcciones determinísticas (clip, interpolación, winsor, tope 3×)
- Métricas: MAE, RMSE, MAPE, sMAPE, WAPE, MASE, sesgo, tracking signal, Theil, skill vs naive, etc.
- Clase Syntetos-Boylan (suave / intermitente / errática / grumosa) y modelos (ETS, Croston, Prophet, LightGBM, …)
- Exportes CSV: corregido, descartes, recomendaciones
