# Verificación del trabajo paralelo (6 nov 2026, hora Argentina)

Varios agentes diseñaron un auditor de pronósticos **sin la planilla real**. El usuario ahora dejó el export Mann/WIX de unidades.

## Qué está mal en el trabajo previo

1. **Formato inventado.** Specs y fixtures usaron series **largas** (`sku` + `fecha` + `pronostico` + `ventas`), a veces **semanales** 2026, a veces `YYYY-MM`. El archivo real es **ancho mensual** con 162 columnas.
2. **Decimales.** Un fixture usó punto decimal “por compatibilidad”. El estándar es **coma**.
3. **Métricas.** Un plan usa WAPE como ratio 0.11; otro como 11%. El harness fija **ratio**.
4. **Veredictos.** KEEP/DISCARD vs MANTENER/DESCARTAR. El producto va en **español**.
5. **Pareja actual/forecast.** No existe en el CSV. El histórico **es** la demanda; el futuro **es** el pronóstico. Auditar “leakage F≡A en 12 puntos” no aplica a este export tal cual.

La rama `cursor/forecast-auditor-fixture-b50c` (`fixtures/forecasts_largo.csv`) queda como contraejemplo: `tests/test_parse_mann.py::test_rejects_invented_long_format` debe seguir fallando ese layout.

## Qué sí reutilizar de esos runs

- Catálogo de métricas (MAE, ME, RMSE, MAPE, sMAPE, WAPE, sesgo).
- Ideas de diagnóstico: negativos, ceros, salto de escala, intermitencia, Croston/TSB.
- UI en español, un SKU a la vez.
- Holdout y recorte a cero como correcciones.

## Hechos medidos en la planilla estándar

| Hecho | Valor |
| --- | --- |
| Filas | 4402 |
| Columnas | 162 (30 meta + 132 meses) |
| Modelos vendor | auto_SARIMA 3240, Holt-Winters 669, prophet 493 |
| Tipo de demanda | Errática 3260, Intermitente 485, Con tendencia 439, Variable moderada 218 |
| Cluster | Alto riesgo 3261, Bajo 641, Mediano 500 |
| ABC | C 3870, B 344, A 188 |
| Clientes | MANN-FILTER 2312, WIX 2090 |
| Primer mes con decimales (mayoría) | 01/11/2026 (2812 SKUs); 1562 SKUs sin ningún decimal |
| Celdas negativas | 1036 en 834 SKUs |
| Descontinuado? / Reemplazado? | todos `No` en este extracto |

`Error` vendor llega a 100 en muchos A de alto volumen: es una pista de que el modelo actual no sirve, no una métrica que debamos recalcular igual.
