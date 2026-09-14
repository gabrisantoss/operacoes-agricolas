# Segurança e privacidade

Esta é uma distribuição demonstrativa para portfólio. Não é um serviço público de produção e não deve receber dados pessoais reais.

## Proteções da demonstração

- Serviços locais e cluster PostgreSQL dedicado, com portas específicas.
- Validação de destinos PostgreSQL em conexões da aplicação e utilidades demonstrativas.
- Senhas de banco, sessão e integração geradas no primeiro preparo.
- Configuração e dados de execução em `.demo`, fora do versionamento.
- Sessão compartilhada, autorização por função, limites de upload e controles de exportação preservados.
- Provedores de IA e entregas externas desativados no ambiente demonstrativo.

Não publique `.demo`, arquivos `.env`, dumps, anexos pessoais, logs ou documentos importados. Não reutilize senhas de outros sistemas. A verificação automática de padrões não substitui revisão humana de cada novo arquivo.

## Relatar um problema

Use o mecanismo privado de relato de vulnerabilidades do GitHub, se habilitado. Caso não esteja disponível, abra somente uma solicitação genérica de contato, sem publicar credenciais, dados pessoais ou instruções de exploração.

As dependências devem ser reavaliadas periodicamente. O registro de validação informa a situação no momento da publicação; ele não constitui garantia permanente de ausência de vulnerabilidades.
