# Registro de validação

Verificação local em **14/09/2026**. Esta página registra o que foi executado, sem prometer cobertura completa ou ausência permanente de falhas.

| Verificação | Resultado |
| --- | --- |
| Instalação em cluster demonstrativo novo | Migrações aplicadas e cenário fictício preparado. |
| Compilação TypeScript | Shared, API, React/Vite e invólucro desktop compilados. |
| Testes Python | **139 aprovados**, executados por arquivo em processos isolados. |
| Testes da API TypeScript | **101 aprovados, 0 falhas, 0 ignorados**, incluindo PostgreSQL real. |
| Verificação HTTP integrada | **29 verificações aprovadas**: autenticação, consultas, sincronização, alteração/restauração de cadastro, exportações e endpoints removidos. |
| Exportações HTTP | PDFs de Notas, Frota e Análises; planilhas de Notas, Análises e Fazendas. Status, assinatura do arquivo e conteúdo não vazio verificados. |
| Navegador | Portal e quatro módulos abertos com dados sintéticos; capturas revisadas para apresentação. |
| npm audit | **0 vulnerabilidades conhecidas** reportadas no momento da verificação. |
| Revisão de publicação | Código e nomes de arquivos examinados; artefatos operacionais e histórico anterior excluídos antes do primeiro commit. |

## Revisão de 19/10/2026

Verificação local da branch consolidada, em clone limpo, com `demo.py setup` e `demo.py test`:

| Verificação | Resultado |
| --- | --- |
| Instalação em cluster demonstrativo novo | Migrações 0001 a 0006 aplicadas; cenário fictício, planilhas de OS e PDFs sintéticos gerados |
| Testes Python | **143 aprovados** |
| Testes da API TypeScript | **174 aprovados, 0 falhas, 0 ignorados**, com PostgreSQL real e PDFs sintéticos lidos pelo Poppler |
| Interface | Importação CSV, central de relatórios, importação de OS e cenários de PDF percorridos com Playwright; capturas novas com dados fictícios |
| npm audit | **0 vulnerabilidades** com `npm audit --audit-level=high` (o mesmo do CI), depois de atualizar no lockfile, sem mudar faixas semver, quatro dependências transitivas: `proxy-addr` 2.0.8, `shell-quote` 1.12.0, `brace-expansion` 1.1.21/2.1.7 e `source-map-js` 1.2.2 |

## Como repetir

Com os pré-requisitos instalados, execute `python demo.py setup`, seguido de `python demo.py test`. No Windows, use um clone em pasta curta: em pastas profundas, os temporários das suítes de backup de Notas e Colaboradores ultrapassam o limite de 260 caracteres por caminho e essas suítes falham por motivo de ambiente (detalhes no README). A suíte TypeScript utiliza `oa_demo_tests`; testes de repositório criam schemas temporários nesse banco. As suítes Python utilizam fixtures locais isoladas, não as bases de uma instalação operacional.

Para repetir as verificações de interface, execute `python demo.py start`, entre no portal e siga o roteiro do README. Os arquivos em `docs/screenshots` são capturas reais desta demonstração, não imagens de uma operação real.

O workflow do GitHub verifica arquivos versionados, sintaxe Python, compilação e dependências JavaScript. **Ele não substitui a suíte integrada local com PostgreSQL e Qt.**

## Correções específicas verificadas na demonstração

- Isolamento de destinos PostgreSQL e credenciais geradas localmente.
- Remoção das dependências, rotas, telas e contratos do módulo geográfico.
- Preservação da integração autenticada entre cadastros de Balança e Notas.
- Tratamento de percentuais literais em SQL compatível com psycopg.
- Arredondamento da eficiência compatível com PostgreSQL.
- Atualização dos contadores de CNH após o carregamento dos dados.
- Testes de segurança dos utilitários de restauração e proteção do histórico de notas.

## Central de relatórios, Rateio, OS e painel Safra

A prévia e o PDF da central são gerados a partir do mesmo objeto calculado. Datas disponíveis nos dados: `entry_date`, que é a data da pesagem ou entrada na balança; a data e o período do lote importado, que são a data do relatório; e `created_at`, que é a data do registro. A data da operação de corte não é armazenada. A central usa a data da pesagem, ou o início do período do lote quando ela falta.

Medidas de área e TCH:

- **Área cadastrada:** área do cadastro dos talhões com entregas no recorte.
- **Talhões encerrados:** talhões cuja OS foi encerrada e cujas entregas vinculadas a essa OS estão todas no recorte. O encerramento da OS é o registro de fim da colheita: libera o pós-colheita e é a base do Rateio. A área efetivamente colhida não é medida. Por isso a central fala em **área dos talhões encerrados**, que é a área cadastrada deles, e não em área colhida.
- **TCH talhões encerrados:** cana desses talhões dividida por essa área. Aparece como N/D quando nenhum talhão está nessa situação. Quando só parte dos talhões está, recebe o rótulo "parcial" e informa a base. A situação de cada talhão aparece no relatório detalhado.

Compatibilidade de totais:

| Visão | Cana | Área | TCH |
| --- | --- | --- | --- |
| Painel Safra | Todas as entradas do filtro | Cadastrada, dos talhões com entregas | Toda a cana ÷ área cadastrada (acompanhamento, inclui talhões em colheita) |
| Rateio de OS / OS encerradas | Entradas vinculadas à OS | Cadastrada, dos talhões colhidos da OS | Cana da OS ÷ área |
| Central de relatórios | Todas as entradas do filtro, igual ao painel | Cadastrada, igual ao painel, e a dos talhões encerrados | Só talhões encerrados com a OS completa no recorte; nesse caso é igual ao Rateio |

Testes automatizados confirmam: cargas, talhões, cana e área cadastrada da central sem filtro iguais ao painel; e cana, área e TCH dos talhões encerrados iguais ao Rateio da OS. Diferenças legítimas:

- O total da central inclui cana sem OS ou de OS ativas, que o Rateio não considera.
- Talhões com entregas de uma OS encerrada misturadas com entregas sem OS aparecem como "Parte das entregas sem OS". O Rateio usa só a parte vinculada; a central não calcula TCH para eles.
- A central filtra o período pela data de referência da entrada. O painel usa a safra ou o período do lote do PDF.
- O filtro de fazenda da central também considera a fazenda do talhão vinculado.
- O painel arredonda para três casas no servidor; a central mantém o valor completo e formata na exibição.

O seed fictício encerra as OS 90007 e 90008 ao meio-dia UTC do último dia de pesagens. Assim nenhuma entrega vinculada fica depois do encerramento, coerente com a regra do importador, que só vincula uma pesagem a uma OS se a data estiver entre o início e o encerramento. Bancos demonstrativos criados antes dessa correção mantêm os dados antigos até um novo `setup`, porque o seed só roda uma vez por banco.

Os testes de PDF da central leem o texto dos streams gerados pelo PDFKit, sem o `pdf-parse`. O pdf.js 1.10 embutido nele rejeita intermitentemente arquivos válidos.

## Limites

Não foram validados: instaladores desktop, execução gráfica Electron, carga concorrente elevada, implantação pública, integrações externas, scanners físicos ou OCR configurado. A revisão visual cobre as telas capturadas; não equivale a validar todas as combinações de formulários e relatórios. Alertas de depreciação de bibliotecas Python permanecem como oportunidade de manutenção.

O exame de privacidade combina seleção positiva de código, exclusão de artefatos, inspeção de padrões e revisão das capturas. Ele reduz o risco de publicação indevida, mas não é uma certificação formal de segurança.


## Transporte de Olhadura — revisão final de 19/10/2026

A suíte integrada `python demo.py test` passou em **173 testes Python** (160 nas suítes de aplicações/controlador e 13 adicionais de Notas com PostgreSQL real), **174 testes TypeScript com PostgreSQL** e **6 testes JavaScript de usabilidade web**, sem testes ignorados. Ambiente local Windows, Python 3.11.9, Node 22 e PostgreSQL 17. O build de todos os workspaces passou, `pip check` não encontrou dependências quebradas e `npm audit --audit-level=high` informou zero vulnerabilidades. Não foi repetida uma instalação limpa de dependências nesta revisão.

No portal autenticado, foram verificados login, bloqueio sem sessão, abertura de Notas pelo launcher, cadastro de variedade, lançamento manual, importação CSV sintética de Balança, logout e proteção após logout. Notas mantém o fluxo manual; a importação CSV pertence ao módulo Balança. A nota fictícia com colheita em 30/04/2026 e plantio em 02/05/2026 apareceu somente no mês correspondente à referência escolhida. Histórico, indicadores, 12 PDFs e quatro planilhas foram conferidos nos dois critérios. O fechamento anual foi comparado com o total de janeiro a dezembro, independentemente do recorte mensal da tela.

A revisão em navegador confirmou paginação de 123 notas em páginas de 50, 50 e 23 registros; filtros combinados com 33 resultados; restauração dos filtros após recarregar; seis opções de PDF; aviso explícito do período anual e downloads dos relatórios de mudas e fechamento. As capturas públicas de lançamento, histórico, filtros e relatórios contêm somente dados sintéticos. O talhão exibido corresponde exclusivamente à origem. Os testes automatizados cobrem armazenamento indisponível, data civil local e respostas antigas de autocomplete.

Foram corrigidos dois erros encontrados no PostgreSQL: colisão da sequência de variedades após o seed de IDs fictícios e comparação indevida de um nome com ID numérico ao resolver referências. Há testes de regressão para ambos, incluindo a preservação de sequências já avançadas. A suíte completa acima foi repetida após as correções.

Limites: caminhos de checkout muito longos no Windows podem impedir exportações; a validação final usou checkout curto. Permanecem avisos não fatais de bibliotecas Python. As capturas e conferências não comprovam todas as combinações possíveis de uso, carga ou dispositivos. Nenhum dado operacional foi usado e a instalação de trabalho não foi acessada.
