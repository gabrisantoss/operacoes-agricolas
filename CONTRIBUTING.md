# Contribuindo com a demonstração

Esta distribuição é um projeto de portfólio para execução local com dados fictícios. Toda mudança deve preservar esse escopo, o isolamento dos bancos e a ausência do módulo de mapas.

## Antes de começar

- Leia o [README](README.md), a [arquitetura](docs/ARQUITETURA.md) e a [política de segurança](SECURITY.md).
- Use uma branch própria e mantenha a alteração pequena e focada.
- Não adicione bancos, backups, arquivos de ambiente reais, credenciais, documentos pessoais ou dados operacionais.
- Use somente fixtures sintéticas e o ambiente demonstrativo. Nunca aponte testes para bancos de outra instalação.

## Reportar um problema

Informe o módulo, os passos de reprodução, o resultado esperado e o observado. Inclua versões do Windows, Python, Node.js, npm e PostgreSQL quando relevantes. Remova caminhos pessoais, tokens e credenciais de qualquer captura ou trecho de log.

Não publique vulnerabilidades ou informações sensíveis em issues abertas. Siga o canal indicado em [SECURITY.md](SECURITY.md).

## Validar uma mudança

Prepare o ambiente seguindo o README. A partir da raiz:

```powershell
py -3.12 demo.py test
```

Para alterações TypeScript, na pasta `balanca-audit`:

```powershell
npm.cmd run build
npm.cmd audit
```

Para alterações visuais, abra a demonstração, confira o módulo afetado e use apenas dados fictícios nas capturas. Para documentação, confira links relativos, imagens e a correspondência das afirmações com o código.

Registre o que realmente executou e o que não foi validado. O workflow do GitHub não substitui os testes integrados locais com PostgreSQL e Qt.

## Abrir um pull request

Explique o problema, a mudança e os riscos. Descreva se afeta contratos entre módulos, persistência ou relatórios. Não inclua credenciais geradas nem o diretório `.demo`. Alterações de escopo, exposição à internet ou integrações externas precisam de discussão específica antes da implementação.
