# Importação gerencial de OS via Excel

O sistema oficial da operação (sistema corporativo) continua sendo a fonte de todos os processos. A Balança recebe uma cópia das OS para organização, acompanhamento, consultas e relatórios:

```
sistema corporativo (oficial) → planilha Excel exportada → prévia na Balança → registro gerencial → consultas e relatórios
```

A Balança **não envia nada ao sistema corporativo** e não altera automaticamente registros já existentes além do que a planilha comprova: ela cria OS novas e acrescenta setores a OS ativas. Nada é removido, encerrado ou reaberto pela importação.

## Layout demonstrativo

O layout real da exportação do sistema corporativo não está documentado neste repositório. A demonstração usa apenas as três colunas que o importador público já aceita; as demais colunas são ignoradas.

| Coluna | Mapeamento na Balança |
| --- | --- |
| `Codigo da OS` | Número da OS. Linhas com o mesmo código formam uma OS |
| `Propriedade` | Fazenda cadastrada, pelo número da propriedade ou pelo código (`100-901`, `100901` e `0100901` são equivalentes). Nenhuma fazenda é criada |
| `Setor` | Código do talhão ativo nessa fazenda. Nenhum talhão é criado |

Arquivos de exemplo, todos fictícios e com aba `LEIA-ME`, gerados por `demo.py setup` em `demo-data/`: `os-exportacao-demonstrativa-1.xlsx` (primeiro export), `-2.xlsx` (export posterior) e `-inconsistente.xlsx` (cadastro inexistente). O repositório não versiona planilhas (`*.xls*` no `.gitignore`), para evitar publicar arquivos operacionais por engano.

## Resultado de cada linha

| Resultado | Quando | Efeito |
| --- | --- | --- |
| Criar OS | OS ainda não existe na Balança | Criada com origem `EXCEL` |
| Adicionar setor | OS ativa existe e o setor ainda não está nela | Setor acrescentado; a origem da OS é preservada |
| Sem alteração | Setor já vinculado, ou OS encerrada com os mesmos setores | Nenhum |
| Divergência | Ver tabela abaixo | Relatada, **não aplicada**; não bloqueia as demais linhas |
| Erro | Fazenda ou setor inexistente ou inativo, campo obrigatório ausente, fórmula nas colunas de identificação | Bloqueia a confirmação até corrigir o cadastro ou a planilha |

Divergências, para conferir no sistema corporativo:

- **OS encerrada com setor novo:** a OS está encerrada na Balança e a planilha traz um setor que não está nela.
- **Setor em outra OS ativa:** aplicar deixaria o setor em duas OS ativas, e as pesagens não poderiam ser vinculadas.
- **Setor duas vezes na planilha:** o mesmo setor aparece em duas OS no mesmo arquivo.
- **Setor ausente na planilha:** o setor está vinculado na Balança e não aparece no export. É mantido, sem remoção automática.

## Reimportação e atualização

- **Mesmo arquivo (mesmo SHA-256):** a prévia informa quando e com que nome ele já foi importado, e a confirmação é recusada. Não há registro duplicado.
- **Export posterior com conteúdo diferente:** é tratado como atualização legítima. Só o que mudou é aplicado, e o resto aparece como "sem alteração".
- **Mesmas linhas em outro arquivo:** um export salvo de novo, com as mesmas linhas, tem bytes diferentes e não conta como o mesmo arquivo. Mesmo assim, nada é duplicado: todas as linhas saem como "sem alteração", e a importação fica registrada sem mudanças.
- A confirmação exige a prévia do mesmo arquivo e falha se as OS mudarem entre a prévia e a confirmação. As OS e o registro da importação são gravados na mesma transação.

## Consulta e relatório

Cada importação confirmada fica no histórico, com arquivo, hash, usuário, data, contagens, resultado por linha e divergências. A tela **Colheita e Balança → Importar OS** mostra a prévia, o histórico e o detalhe, e exporta um relatório CSV da importação. As rotas são `GET /orders/import-excel/history`, `/history/:id` e `/history/:id/report.csv`.
