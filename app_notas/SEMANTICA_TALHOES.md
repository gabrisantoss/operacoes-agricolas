# Talhões nas notas de transporte

`notas.talhao` representa exclusivamente o talhão de origem, onde a muda foi colhida. A fazenda de destino é registrada, mas seu talhão ainda não é coletado. Autocomplete e resolução de referências usam somente a fazenda de origem; sem origem resolvida, o valor digitado é preservado sem associação cadastral.

Relatórios devem distinguir fazenda de origem, talhão de origem e fazenda de destino. O relatório detalhado preserva a fazenda de destino e acrescenta a fazenda de origem para contextualizar o talhão. Totais e critérios de período permanecem iguais. A coluna técnica `talhao` e seus valores históricos são preservados; o Excel bruto mantém esse nome por compatibilidade.

Existe intenção de iniciar a coleta do talhão de destino em 2027. Quando autorizado, deverá ser campo independente e opcional, sem dedução ou preenchimento automático dos registros antigos. Esta alteração não cria coluna nem migração.

## Validação desta alteração

Base pública: `0baffdacc98a80e381477cf6bc726f4340aacf22`.
Executados 18 testes direcionados com SQLite temporário: `tests.test_talhao_origem`, `tests.test_reporting_data`, `tests.test_reporting_pdf` e `tests.test_web_server_safety`. Todos passaram. Os testes verificam ausência de associação ao destino sem origem, resolução pela origem, autocomplete sem origem, contexto no PDF e preservação de notas/totais nas exportações. As contagens existentes de talhões distintos por texto permanecem iguais.

Não foi feita validação visual interativa das telas desktop/web. Não houve alteração de instalação operacional, migração de banco ou publicação.
