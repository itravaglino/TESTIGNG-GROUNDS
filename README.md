# Kalibra

Auditor de pronósticos de demanda. Lee un CSV o XLSX, evalúa cada producto y devuelve tres decisiones:

- **Mantener**: el número es usable.
- **Corregir**: hay sesgo, picos, huecos, un futuro desconectado del nivel real, o un método base que le gana al archivo.
- **Descartar**: el pronóstico está vacío, el calendario está roto, o no hay forma seria de rescatarlo.

Cuando hay demanda real, Kalibra mide el error en un tramo final que no se usa para elegir la corrección. El archivo corregido no copia la demanda real: recalibra, recorta o reemplaza por un método simple (naive, media, SES, Holt, Croston, SBA o TSB).

## Cómo usarlo

```bash
pip install -r requirements.txt
python3 -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Abrí `http://127.0.0.1:8000`. Podés cargar tu archivo o el ejemplo de 13 productos.

Por consola:

```bash
python3 -m forecast_auditor mi_forecast.csv -o informe.json --csv corregido.csv
```

Sin archivo, la consola audita el ejemplo.

## Columnas

Obligatorias: **producto**, **fecha**, **pronóstico**.

Opcionales: **real** (o venta, demanda), **modelo**, **limite_inf**, **limite_sup**.

Sirven los nombres en español o en inglés. El CSV puede ir separado por coma, punto y coma o tabulación. Las fechas `dia/mes/año` y los decimales con coma se leen como en el uso local.

## Qué mira, por producto

Precisión: WMAPE, MAPE, sMAPE, MAAPE, MAE, RMSE, MSE, MedAE, RMSLE.

Contra una base: MASE, RMSSE, Theil U2, valor agregado contra el naive y contra el naive estacional.

Sesgo: error medio, sesgo %, MPE, tracking signal, error acumulado, % de períodos por encima y por debajo.

Acierto: ±10%, ±20%, ±30%, percentiles 50 y 90 del error absoluto.

Forma: correlación y R².

Intervalo, si vienen las bandas: cobertura, ancho y puntaje de Winkler al 80%.

Serie: frecuencia, huecos, negativos, ceros, picos, ADI, CV², clase de demanda (suave, errática, intermitente, irregular), estacionalidad y tendencia.

La recomendación de modelo sale de ese patrón: SES, Holt, Holt-Winters, SARIMA, Theta, Prophet, Croston, SBA, TSB, ADIDA, LightGBM o una media móvil si la historia es corta.

## Pruebas

```bash
python3 -m pytest
```
