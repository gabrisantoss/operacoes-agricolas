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

## Central de relatórios e painel Safra

A prévia e o PDF da central são gerados a partir do mesmo objeto calculado. A central separa três medidas de área:

- **Área cadastrada:** área do cadastro dos talhões que têm entregas no recorte. É um dado de cadastro e não comprova colheita.
- **Área colhida comprovada:** área cadastrada apenas dos talhões cuja OS está **encerrada** e cujas entregas vinculadas a essa OS estão **todas** no recorte. Ter todas as entregas registradas dentro do período não basta: sem OS encerrada, a colheita pode continuar.
- **TCH efetivo:** cana desses talhões comprovados dividida pela área colhida comprovada. Aparece como **N/D** quando nenhum talhão é comprovado. Quando só parte deles é comprovada, o indicador recebe o rótulo **"TCH efetivo parcial"**, informa a base (talhões e toneladas usados) e não representa a produtividade de todo o recorte.

Cada talhão do relatório detalhado mostra sua situação: OS encerrada, OS encerrada fora do recorte, sem OS encerrada, mais de uma OS ou sem área cadastrada. A regra segue o Rateio de OS: a produção de uma OS são as entregas vinculadas a ela, e a área usada é a área cadastrada dos talhões da OS.

Definições compartilhadas com o painel Safra: cana entregue (soma do peso líquido), cargas (número de entradas), regras de identidade de fazenda e talhão, e área cadastrada dos talhões com área em hectares e alqueires. Sem filtros, um teste automatizado confirma que cargas, talhões, cana e área cadastrada são iguais nos dois.

Diferenças legítimas:

| Aspecto | Painel Safra | Central de relatórios |
| --- | --- | --- |
| TCH | Toda a cana entregue ÷ área cadastrada dos talhões com área. É uma razão de acompanhamento e inclui talhões ainda em colheita | TCH efetivo só com talhões de colheita comprovada por OS encerrada; N/D ou "parcial" com a base informada |
| Área | Área cadastrada dos talhões com entregas | Mostra a área cadastrada e, separadamente, a área colhida comprovada |
| Período | Safra (ano) ou período do lote do PDF, por sobreposição | Data de referência da entrada (sem data, início do período do lote) |
| Filtro de fazenda | Fazenda gravada na entrada | Também a fazenda do talhão vinculado |
| Arredondamento | Três casas no servidor | Valor completo, formatado com três casas para tonelada e duas para área e TCH |

Os testes de PDF da central leem o texto dos streams gerados pelo PDFKit, e não usam o `pdf-parse`. O pdf.js 1.10 embutido nele rejeita intermitentemente arquivos válidos, que Poppler e PDFium abrem sem erro.

## Limites

Não foram validados: instaladores desktop, execução gráfica Electron, carga concorrente elevada, implantação pública, integrações externas, scanners físicos ou OCR configurado. A revisão visual cobre as telas capturadas; não equivale a validar todas as combinações de formulários e relatórios. Alertas de depreciação de bibliotecas Python permanecem como oportunidade de manutenção.

O exame de privacidade combina seleção positiva de código, exclusão de artefatos, inspeção de padrões e revisão das capturas. Ele reduz o risco de publicação indevida, mas não é uma certificação formal de segurança.
