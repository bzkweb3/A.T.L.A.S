# Instruções permanentes — A.T.L.A.S.

## Autoridade do projeto
- O documento mestre A.T.L.A.S. v1.1 e as decisões aprovadas pelo proprietário são a referência do projeto.
- Não redefina a visão, as fases ou decisões arquiteturais sem aprovação explícita.
- O A.T.L.A.S. é uma inteligência central lógica, abstrata e não humanoide.

## Decisões técnicas aprovadas
- Banco inicial: SQLite.
- Integração de IA: abstração independente de provedores.
- Memória: estruturada e relacional.
- Priorizar soluções locais e gratuitas na fase inicial.
- Preparar a arquitetura para evolução híbrida, sem exigir nuvem agora.

## Forma de trabalho
- Trabalhe em etapas pequenas, com escopo e critérios de conclusão.
- Antes de mudanças amplas, inspecione o estado atual e explique o plano.
- Não apague, renomeie ou reescreva arquivos sem necessidade demonstrada.
- Preserve rotas e comportamentos existentes.
- Não introduza dependências sem justificar sua necessidade e verificar compatibilidade com a versão de Python do projeto.
- Adicione testes para novos comportamentos e execute os testes disponíveis.
- Atualize a documentação quando uma decisão ou contrato mudar.
- Nunca inclua segredos, tokens, credenciais, bancos locais ou arquivos .env no Git.

## Limites da Fase 1
- Consolidar backend, configuração, contratos, persistência inicial e memória estruturada.
- Não implementar ainda agentes executores, voz, automação de desktop/navegador, dispositivos, busca vetorial ou interfaces holográficas.
- Não simular respostas de IA quando nenhum provedor estiver configurado.
- Operações sensíveis futuras deverão exigir autorização explícita e auditoria.

## Comunicação
- Explique mudanças objetivamente: arquivos alterados, motivo, testes executados e limitações conhecidas.
- Não afirme que algo foi testado se não foi.
