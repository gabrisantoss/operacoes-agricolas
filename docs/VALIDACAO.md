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

A prévia e o PDF da central são gerados a partir do mesmo objeto calculado. Em relação ao painel Safra, as definições são compatíveis:

- **Cana entregue** é a soma do peso líquido das entradas; **cargas** é o número de entradas.
- Fazenda e talhão usam as mesmas regras de identidade do painel: cadastro, código bruto e nome.
- **TCH** é a cana entregue dividida pela área cadastrada dos talhões que têm área em hectares e em alqueires. A cobertura de área é informada. Talhões sem área entram na cana, mas não na área, como no painel.
- Sem filtros, um teste automatizado confirma que os totais da central e do painel são iguais: cargas, cana, área, TCH e cobertura.

Diferenças legítimas:

| Aspecto | Painel Safra | Central de relatórios |
| --- | --- | --- |
| Período | Safra (ano) ou período do lote do PDF, por sobreposição | Data de referência da entrada (sem data, início do período do lote) |
| Filtro de fazenda | Fazenda gravada na entrada | Também a fazenda do talhão vinculado |
| TCH em período parcial | Calculado com a área total dos talhões | **N/D** quando um talhão tem entregas fora do período: a área colhida dentro dele não pode ser determinada pelos dados. Cana e cargas continuam válidas, assim como o TCH dos talhões com toda a colheita registrada no período |
| Arredondamento | Três casas no servidor | Valor completo, formatado com três casas para tonelada e duas para área e TCH |

## Limites

Não foram validados: instaladores desktop, execução gráfica Electron, carga concorrente elevada, implantação pública, integrações externas, scanners físicos ou OCR configurado. A revisão visual cobre as telas capturadas; não equivale a validar todas as combinações de formulários e relatórios. Alertas de depreciação de bibliotecas Python permanecem como oportunidade de manutenção.

O exame de privacidade combina seleção positiva de código, exclusão de artefatos, inspeção de padrões e revisão das capturas. Ele reduz o risco de publicação indevida, mas não é uma certificação formal de segurança.
