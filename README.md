# Lupa

Laboratorio para auditar un forecast producto por producto. Corre en el navegador: el archivo no se envía a un servidor.

## Cómo usarlo

```bash
npm install
npm test
npm run dev
```

Abrí `http://127.0.0.1:5173`. Podés cargar el ejemplo o un CSV/Excel propio.

## Formato

Una fila por producto y período. Separador coma, punto y coma o tab.

| producto | nombre | categoria | fecha | pronostico | real |
| --- | --- | --- | --- | --- | --- |
| SKU-001 | Yerba 1kg | Almacén | 2025-01-01 | 120 | 100 |

También reconoce `sku`, `código`, `material`, `semana`, `demanda`, `venta`, `piso` y `techo`. La venta real es opcional: sin ella Lupa revisa la forma del forecast y baja la confianza. Los pisos y techos activan cobertura de intervalo.

## Qué devuelve

Para cada producto: mantener, corregir o descartar, con WAPE, sMAPE, MAPE, MAE, RMSE, MASE, U de Theil, sesgo, tracking signal, FVA contra naive y estacional, patrón Syntetos-Boylan y un modelo para usar ahora. El CSV corregido deja vacío el número de los productos descartados.
