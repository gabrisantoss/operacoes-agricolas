# Roteiro de demonstração (cerca de 5 minutos)

Pré-requisitos: `py -3.12 demo.py setup`, `py -3.12 demo.py start` e login com `gestor@example.invalid` (a senha vem de `py -3.12 demo.py credentials`). Todos os dados são fictícios.

| Tempo | Onde | O que mostrar |
| --- | --- | --- |
| 0:00 | Portal | Login único e os quatro módulos integrados. Abra **Colheita e Balança** |
| 0:30 | Resultado e Safra | Indicadores da safra fictícia, divergências deliberadas e fechamento de safra |
| 1:15 | Validar | Importe `demo-data/pesagem-ficticia.csv`. A prévia reconhece as 8 colunas separadas por `;` e mostra o mapeamento. Salve e importe de novo o mesmo arquivo: a reimportação é recusada |
| 2:00 | Relatórios | Gere o relatório geral sem filtros e depois o detalhado de uma fazenda. Mostre a área cadastrada, a área dos talhões encerrados e o TCH "parcial". Escolha um período curto: o TCH vira N/D com a explicação. Exporte o PDF |
| 3:00 | Importar OS | Prévia de `demo-data/os-exportacao-demonstrativa-1.xlsx`: OS nova, OS encerrada preservada e duas divergências não aplicadas. Confirme, depois tente a mesma planilha (recusada) e a versão `-2` (atualização legítima). Abra o histórico e baixe o relatório CSV |
| 4:00 | Validar (PDF) | Em `demo-data/pdf-sobreposicao/`, grave o `01`. O `02` (idêntico) é bloqueado; o `07` (mesmo período, outra fazenda) é aceito; o `03` (mesmos talhões em período sobreposto) só é gravado depois da revisão explícita |
| 4:45 | Fechamento | Nada é enviado ao sistema corporativo. Os controles reduzem riscos de duplicidade, mas a conferência humana continua necessária. Os testes rodam com `py -3.12 demo.py test` |

Dica: para repetir o roteiro do zero, use um clone novo e um novo `setup`, porque as importações ficam gravadas no banco demonstrativo.
