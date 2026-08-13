# Helena Dashboards

Dashboards da Helena:

- MetaAds ROI: `/`

## API do MetaAds ROI

O dashboard em `/` tenta carregar `GET /api/data` ao abrir. O endpoint deve
retornar JSON no formato abaixo; enquanto a API não estiver publicada, a página
continua funcionando com o último snapshot embutido no `index.html`.

```json
{
  "generatedAt": "2026-08-12T20:00:00Z",
  "projects": [
    { "key": "lt-dentistas", "name": "LT Dentistas", "rows": [] }
  ]
}
```

O backend deve manter tokens da Meta e credenciais do Google exclusivamente no
servidor; nenhuma credencial deve ser enviada ao navegador.
