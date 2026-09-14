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

Com os pré-requisitos instalados, execute `python demo.py setup`, seguido de `python demo.py test`. A suíte TypeScript utiliza `oa_demo_tests`; testes de repositório criam schemas temporários nesse banco. As suítes Python utilizam fixtures locais isoladas, não as bases de uma instalação operacional.

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

## Limites

Não foram validados: instaladores desktop, execução gráfica Electron, carga concorrente elevada, implantação pública, integrações externas, scanners físicos ou OCR configurado. A revisão visual cobre as telas capturadas; não equivale a validar todas as combinações de formulários e relatórios. Alertas de depreciação de bibliotecas Python permanecem como oportunidade de manutenção.

O exame de privacidade combina seleção positiva de código, exclusão de artefatos, inspeção de padrões e revisão das capturas. Ele reduz o risco de publicação indevida, mas não é uma certificação formal de segurança.
