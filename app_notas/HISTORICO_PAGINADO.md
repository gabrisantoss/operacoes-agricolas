# Histórico web: páginas e filtros combinados

O histórico usa páginas de 50 notas, ordenadas por número decrescente. Anterior/Próxima mudam o deslocamento (`offset`); o banco aplica `LIMIT`/`OFFSET` e calcula o total com `COUNT(*)` usando os mesmos filtros. Não se carregam todas as notas para depois recortar a lista em Python. Se um deslocamento ficar além do resultado, o servidor retorna a última página válida; lista vazia retorna offset zero.

Origem e destino aceitam parte do nome ou código, e variedade aceita parte do nome. Os três filtros são opcionais e se combinam com AND, junto com a busca geral/campo escolhido e o período. A busca por número preserva o prefixo numérico. `%`, `_` e `!` são literais, não curingas. A comparação mantém letras acentuadas sem distinguir caixa; PostgreSQL 17 usa explicitamente a collation Unicode pg_c_utf8, pois o cluster demonstrativo usa locale C.

Colheita continua sendo a referência padrão; plantio pode ser escolhido. Toda alteração de filtros/busca/datas reinicia a página. O botão Todos mantém o comportamento anterior de retirar o recorte por período, sem apagar os outros critérios.

Os filtros novos se aplicam ao histórico web. Exportações e indicadores do BI continuam usando seu próprio período e referência, como antes, abrangendo todos os registros desse recorte, sem limite de página. A aplicação desktop e a consulta de histórico usada por ela foram preservadas. Não houve migração de banco nem nova regra de bloqueio de notas.

## Para estudar

- `web_app/server.py`, `handle_historico`: recebe parâmetros HTTP e chama a consulta paginada.
- `database.py`, `buscar_historico_paginado`: monta os predicados e parâmetros; executa COUNT e depois a seleção com LIMIT/OFFSET. `contains` escapa a busca literal. Valores são parâmetros; colunas vêm de listas internas e da validação de data.
- `web_app/static/app.js`, `historyUrl`: monta os parâmetros. `loadHistory`: busca a página e atualiza as linhas. `updateHistoryPagination`: mostra intervalo, página e total, e habilita/desabilita os botões. Respostas canceladas não substituem uma busca mais recente.
- `web_app/static/index.html`: filtros e controles da paginação.
- `tests/test_history_pagination.py`: fixtures fictícias, páginas, combinações e datas em meses diferentes.

## Validação O4.1

31 testes direcionados SQLite e 5 testes da nova consulta em PostgreSQL real passaram. Os testes PostgreSQL usaram bancos temporários exclusivos oa_demo_tests_o41_*, removidos ao final. A consulta alcançou 1.124 notas e sua última página, sem sobreposição entre páginas.

No portal autenticado, 123 notas fictícias adicionais foram cadastradas pela API: páginas de 50/50/23, filtros de origem/destino/variedade com 33 resultados, combinação vazia, busca geral, retorno à primeira página e colheita em abril/plantio em maio passaram em verificações automatizadas do navegador. A interface foi inspecionada por capturas. Os botões ficam desabilitados nos limites e durante carregamento.

Foi conferido também que a página do histórico tem 50 notas enquanto os indicadores e exportações continuam abrangendo as 124 notas fictícias do período completo (duas referências, XLSX bruto/fluxo e PDF detalhado). As suítes existentes de datas, talhão de origem, relatórios e proteção do histórico passaram. Node syntax check e git diff --check passaram. Não foi executada suíte completa nem teste de carga.

Nenhuma instalação operacional, dado real, repositório privado ou publicação participou. Evidências e relatório com linhas para estudo ficam na pasta de entregas da conversa, fora deste repositório.
