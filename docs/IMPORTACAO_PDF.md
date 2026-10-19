# Importação manual de PDFs: repetição e sobreposição

Os relatórios RELPESAG ("Resumo de Cana Entregue - Talhão") chegam por e-mail e são inseridos manualmente. Antes de gravar, a prévia compara o PDF com os PDFs já importados e classifica a situação:

| Situação | Como é identificada | Resultado |
| --- | --- | --- |
| Arquivo idêntico | Mesmo SHA-256 de um arquivo já importado | **Bloqueado**, inclusive na confirmação |
| Mesmo período | Início e fim iguais aos de outro PDF | **Bloqueado** pela regra existente: um PDF por período. Exclua o grupo anterior no Histórico para substituí-lo |
| Período parcialmente sobreposto | Períodos se cruzam e há talhões em comum | **Revisão obrigatória**: a cana desses dias pode ser contada duas vezes |
| Conteúdo coincidente | Período diferente, mas pelo menos metade dos talhões (e no mínimo três, ou todos se forem menos) tem exatamente a mesma cana e as mesmas viagens de outro PDF | **Revisão obrigatória**: pode ser o mesmo relatório com outro período |
| Sobreposição com outros talhões | Períodos se cruzam sem talhão em comum | **Informada**; importação legítima |
| Sem relação | Nenhum dos casos acima | Importação normal |

A prévia mostra, para cada alerta, o PDF anterior (arquivo, período, data de importação), o período em comum e, por talhão, a fazenda, o talhão e a cana e as viagens dos dois PDFs.

## Revisão explícita

- Uma sobreposição ambígua não é tratada automaticamente como duplicação, e nenhum registro é descartado ou sobrescrito.
- Para gravar, o usuário marca a confirmação na prévia. A API exige o token de revisão daquela análise.
- O token muda se o arquivo ou os PDFs já gravados mudarem, e então é preciso gerar a prévia de novo.
- As entregas dos talhões revisados recebem a nota "Sobreposição revisada antes da gravação", com o arquivo e o período anteriores.
- Se for o mesmo conteúdo, o caminho é excluir o lote anterior no Histórico, que é a regra já existente, e não gravar os dois.

A análise compara apenas PDFs, como a regra anterior. Planilhas e CSV seguem o controle por hash.

## Requisito de ambiente

A leitura posicional usa o `pdftotext -bbox-layout` do **Poppler**. Um `pdftotext` do Xpdf no PATH não tem essa opção, e a importação recusa o PDF por não reconhecer as colunas. Coloque a pasta `bin` do Poppler antes no PATH ao iniciar a demonstração. Os testes de integração usam `POPPLER_BIN_DIR`.

## PDFs sintéticos

`demo.py setup` gera seis PDFs fictícios em `demo-data/pdf-sobreposicao/`, um por cenário; veja o `LEIA-ME.txt` da pasta. Os testes usam o mesmo gerador (`apps/api/src/testSupport/syntheticCaneSummaryPdf.ts`), que segue a grade de colunas lida pelo importador.
