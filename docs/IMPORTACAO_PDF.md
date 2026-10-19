# Importação manual de PDFs: repetição e sobreposição

Os relatórios padronizados de pesagem ("Resumo de Cana Entregue - Talhão"), exportados do sistema corporativo, chegam por e-mail e são inseridos manualmente. Antes de gravar, a prévia compara o PDF com os PDFs já importados e classifica a situação:

| Situação | Como é identificada | Resultado |
| --- | --- | --- |
| Arquivo idêntico | Mesmo SHA-256 de um arquivo já importado | **Bloqueado**, inclusive na confirmação |
| Mesmo período com talhões em comum | Início e fim iguais e ao menos uma fazenda/talhão repetido | **Revisão obrigatória**; se for o mesmo relatório corrigido, exclua o lote anterior no Histórico |
| Período parcialmente sobreposto | Períodos se cruzam e há talhões em comum | **Revisão obrigatória**: a cana desses dias pode ser contada duas vezes |
| Conteúdo coincidente | Período diferente, mas pelo menos metade dos talhões (e no mínimo três, ou todos se forem menos) tem exatamente a mesma cana e as mesmas viagens de outro PDF | **Revisão obrigatória**: pode ser o mesmo relatório com outro período |
| Período coincidente com outros talhões | Mesmo período ou períodos que se cruzam, sem fazenda/talhão em comum | **Informada**; importação legítima |
| Sem relação | Nenhum dos casos acima | Importação normal |

A prévia mostra, para cada alerta, o PDF anterior (arquivo, período, data de importação), o período em comum e, por talhão, a fazenda, o talhão e a cana e as viagens dos dois PDFs.

## Revisão explícita

- O período sozinho não bloqueia: o antigo índice "um PDF por período" foi removido (migração 0005). Só o hash idêntico continua bloqueado.
- Uma sobreposição ambígua não é tratada automaticamente como duplicação, e nenhum registro é descartado ou sobrescrito.
- A revisão **reduz, mas não elimina**, o risco de contagem duplicada: ela depende da conferência de quem importa.
- Para gravar, o usuário marca a confirmação na prévia. A API exige o token de revisão daquela análise.
- O token muda se o arquivo ou os PDFs já gravados mudarem, e então é preciso gerar a prévia de novo.
- As entregas dos talhões revisados recebem a nota "Sobreposição revisada antes da gravação", com o arquivo e o período anteriores.
- Se for o mesmo conteúdo, o caminho é excluir o lote anterior no Histórico, que é a regra já existente, e não gravar os dois.

A análise compara apenas PDFs, como a regra anterior. Planilhas e CSV seguem o controle por hash.

## Requisito de ambiente

A leitura posicional usa o `pdftotext -bbox-layout` do **Poppler**. Quando o `pdftotext` não é encontrado, ou é de outra distribuição sem essa opção (como o Xpdf), a prévia recusa o PDF com essa explicação e não grava nada. Para apontar o Poppler sem alterar o sistema, defina `POPPLER_BIN_DIR` (pasta `bin`) ou `PDFTOTEXT_CMD` (executável) ao iniciar a aplicação, ou coloque a pasta do Poppler antes no PATH. Os testes de integração usam `POPPLER_BIN_DIR`.

## PDFs sintéticos

`demo.py setup` gera sete PDFs fictícios em `demo-data/pdf-sobreposicao/`, um por cenário; veja o `LEIA-ME.txt` da pasta. Os testes usam o mesmo gerador (`apps/api/src/testSupport/syntheticCaneSummaryPdf.ts`), que segue a grade de colunas lida pelo importador.
