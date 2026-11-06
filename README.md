# Auditor de pronósticos

Aplicación local para revisar un forecast **producto por producto**: mide el error, marca lo que hay que corregir, descarta lo que no se puede usar y recomienda un método de pronóstico.

## Cómo abrirlo

```bash
pip install -r requirements.txt
python -m auditor
```

Entra en [http://127.0.0.1:8765](http://127.0.0.1:8765). Podés subir un CSV o Excel, pegar la tabla, ver un ejemplo o bajar la serie corregida.

Desde la terminal:

```bash
python -m auditor analyze mi_forecast.csv --out informe.json
python -m auditor corregir mi_forecast.csv --out serie_corregida.csv
```

## Formato del archivo

Sirve una fila por producto y período, o una fila por producto con los meses en columnas.

Columnas que reconoce (con o sin acentos):

| Dato | Nombres aceptados |
| --- | --- |
| Producto | `sku`, `codigo`, `producto`, `item`, `material` |
| Nombre | `descripcion`, `nombre`, `articulo` |
| Lugar | `sucursal`, `canal`, `deposito`, `tienda`, `region` |
| Fecha | `fecha`, `periodo`, `mes` |
| Pronóstico | `pronostico`, `forecast`, `fcst`, `prediccion` |
| Demanda real | `venta`, `demanda`, `actual`, `real`, `historia` |
| Modelo | `modelo`, `metodo` |

También acepta separador `;`, decimal con coma (`1.234,56`) y meses en columnas (`ene-2024`, `2024-01`, `Pronostico_2024-01` junto a `Real_2024-01`). La plantilla se descarga desde la pantalla.

Sin la columna de venta el auditor igual revisa la forma del pronóstico (negativos, huecos, picos, serie plana), pero no puede calcular el error.

## Qué decide

- **Aprobar.** No hay errores que impidan usarlo. Puede haber advertencias.
- **Corregir.** Hay un defecto reparable (negativos, hueco, pico aislado, explosión final, error alto). La serie corregida viene en el CSV de salida.
- **Descartar.** El pronóstico no se puede rescatar (mitad o más en negativo, nivel absurdo contra la historia, sin valores, o un error que ya supera a la demanda). No se rellena con un número inventado.

## Métricas

Por producto, cuando hay historia que se solapa con el pronóstico: ME, MAE, MdAE, RMSE, sesgo, MPE, MAPE, MdAPE, sMAPE, WAPE, MASE, RMSSE, tracking signal, U de Theil, valor agregado contra el naive y contra el naive estacional, acierto a ±10% y ±20%, correlación y R².

El perfil de la serie trae clase de demanda (suave, errática, intermitente o grumosa, con ADI y CV²), tendencia, fuerza de estacionalidad, planitud, huecos y ratio contra la historia.

El error es **pronóstico menos real**: positivo significa que se pronosticó de más.

## Métodos que puede recomendar

Naive, naive estacional, media móvil, suavizado exponencial simple, Holt, Holt-Winters, ETS, ARIMA, SARIMA, Theta, Croston SBA, TSB, IMAPA, ensamble, Prophet, LightGBM global y reconciliación jerárquica MinT. La lista se arma según la clase de demanda, el largo de la historia y si el pronóstico actual le gana a repetir el último período. Si no le gana a ese método simple, el auditor no recomienda un modelo más pesado como primera opción.
