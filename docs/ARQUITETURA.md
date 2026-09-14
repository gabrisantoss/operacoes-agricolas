# Arquitetura

## Organização do código

```text
operacoes-agricolas/
├── launcher_web/          # Portal Python, sessão, proxy e auditoria
├── app_notas/             # Notas, transporte, UI web e PyQt, relatórios
├── app_colaboradores/     # Pessoas, CNH, escala, anexos e relatórios
├── analises/              # Apontamentos, eficiência, colheita e relatórios
├── agricola_shared/       # Compatibilidade SQL, autenticação e proteções
├── balanca-audit/
│   ├── apps/api/          # Express, repositórios, serviços e migrações
│   ├── apps/web/          # React e TypeScript
│   ├── apps/desktop/      # Invólucro Electron preservado
│   └── packages/shared/   # Contratos e validação Zod
├── scripts/               # Cenário fictício e execução de testes
├── demo-data/             # CSV sintético de importação
├── docs/                  # Apresentação, arquitetura e evidências visuais
└── demo.py                # Preparo e controlador local
```

## Comunicação e persistência

| Componente | Porta local | Banco dedicado |
| --- | --- | --- |
| Portal | 8890 | oa_demo_portal |
| Notas | 8891 | oa_demo_notas |
| Colaboradores | 8892 | oa_demo_colaboradores |
| Análises | 8888 | oa_demo_analises |
| API Balança | 8833 | oa_demo_balanca |
| PostgreSQL | 55439 | Cluster exclusivo em `.demo/postgres` |
| Testes da API | Processo temporário | oa_demo_tests, com schemas temporários |

Todos os serviços da demonstração escutam em loopback. O navegador entra pelo portal, que encaminha requisições para os módulos. O frontend React compilado é servido pelo portal; não é necessário manter o servidor de desenvolvimento Vite ativo.

O cookie `oa_demo_session` identifica a sessão compartilhada. A integração Balança → Notas utiliza uma identidade de serviço fictícia com senha aleatória local. O controlador configura explicitamente os destinos de banco e integrações, sem herdar configurações operacionais do ambiente.

## Fidelidade e adaptações

Foram preservados os módulos de negócio, a separação de repositórios/serviços, os principais layouts, formulários, relatórios e testes. A demonstração não troca os backends por respostas estáticas.

As adaptações abrangem identidade visual, variáveis e caminhos neutros, dados fictícios, isolamento dos bancos, inicialização local, remoção integral da funcionalidade geográfica e ajustes de compatibilidade encontrados nos testes. Utilidades de operação que dependiam de infraestrutura externa não integram o controlador demonstrativo.

O namespace técnico `balanca` foi mantido para não romper contratos internos. `agricola_shared` reúne código transversal. As aplicações Python mantêm compatibilidade SQLite para testes unitários, mas a execução integrada demonstrativa utiliza PostgreSQL.

## Dados e ciclo de vida

O gerador usa constantes fictícias, UUIDs determinísticos e aleatoriedade com semente fixa. As datas partem do dia do preparo. Cada banco registra uma versão de seed para evitar duplicação. Alterações feitas pela interface são persistentes durante o uso local.

`.demo` reúne configuração, cluster, logs, credenciais geradas, fixtures de execução e dependências Python. Esses arquivos são deliberadamente ignorados pelo Git. O repositório inclui somente o código, configurações demonstrativas, documentação e imagens revisadas.
