# Validação O2.1 e O3 — 19/10/2026

Base: commit local `0557df9` do clone isolado da demonstração pública. Implementação: `c7fb76f`.

## Revisão visual

- Navegador: lançamento, histórico e BI/relatórios, inclusive seleção Data de plantio com período em fevereiro e nota colhida em janeiro. Rótulo talhão de origem separado da fazenda de destino; ambas as datas visíveis no histórico.
- Desktop: lançamento, histórico e controles de relatórios renderizados com o estilo da aplicação. O cabeçalho Talhao de origem estava cortado; sua largura agora considera a fonte efetiva.
- Exportações reais da API local de revisão: seis tipos de PDF para cada referência (12 arquivos) e Excel bruto/fluxo para cada referência (4 arquivos). Conferidos PDF detalhado e mosaico das páginas dos seis tipos por plantio, além das prévias dos conteúdos das planilhas. Dados de origem e destino permanecem separados; nenhum talhão de destino foi inventado. A coluna técnica talhao do Excel bruto mantém o contrato anterior, documentado como origem.
- O rodapé específico do fechamento anual passou a informar a referência também na capa e nas páginas internas. O fechamento continua anual, não mensal.

A revisão usou servidor local de teste, SQLite descartável e identidade de sessão fictícia fornecida somente pelo harness externo. A autenticação da aplicação não foi alterada. Alertas de sincronização/colaboradores nas capturas são esperados: integrações externas ficaram desativadas. Não houve conexão à instalação operacional.

## Testes direcionados

28 testes aprovados em SQLite temporário, executados a partir de app_notas:

`python -m unittest tests.test_date_reference tests.test_reporting_data tests.test_reporting_pdf tests.test_talhao_origem tests.test_tab_historico tests.test_tab_lancamento tests.test_web_server_safety`

Cobrem colheita/plantio em dias, meses e anos diferentes; padrão por colheita; contagens, dias ativos e rankings; seis coletores de relatório; API de histórico/BI; XLSX real; identificação do critério em todas as páginas dos seis PDFs; seleção desktop e exportação; validação dos nomes de coluna; preservação de notas antigas sem data de plantio. Os testes existentes verificam renderização de PDF com múltiplas páginas e proteção de histórico.

Também passaram `node --check app_notas/web_app/static/app.js`, compilação Python e `git diff --check`.

## Limites

A inspeção do desktop foi feita em renderização Qt offscreen; não foi uma sessão interativa do aplicativo completo. Planilhas foram verificadas por leitura do XLSX e prévias renderizadas, sem sessão nativa do Excel. PostgreSQL, integração com o launcher completo e suíte completa não foram executados. Não houve migração, mudança operacional, push ou publicação.

Evidências visuais e exportações ficam fora do repositório público, na pasta de entregas desta conversa.
