# Continuidade de tarefas de conversa

O A.T.L.A.S. registra cada solicitação em `conversation_tasks` e cada execução
em `task_attempts`. A estrutura já existe no esquema SQLite v4, portanto esta
evolução não exige migração.

## Recuperação

- Uma execução pode fazer até três tentativas automáticas no total.
- Entre tentativas, o atraso cresce de 1 para 2 segundos.
- Erros transitórios de provedor acionam nova tentativa; provedores alternativos
  configurados são consultados antes de repetir a solicitação.
- O streaming emite um evento `reset` ao trocar de tentativa. O texto parcial fica
  gravado na tentativa anterior e nunca é concatenado à resposta seguinte.
- Solicitações ainda em processamento quando o servidor reinicia são marcadas
  como interrompidas. No startup, o recuperador executa novamente tarefas elegíveis.
- Se o navegador desconecta durante o streaming, a tarefa é entregue ao mesmo
  recuperador em segundo plano. A interface atualiza a conversa concluída por
  consulta periódica.
- `start_attempt()` reivindica a tarefa sob transação SQLite, impedindo duas
  execuções simultâneas da mesma solicitação.

## Limite de escopo

O recuperador serve apenas para geração de texto sem efeitos externos. Ações
futuras que alterem arquivos, enviem mensagens ou operem dispositivos exigirão
autorização explícita e não devem ser adicionadas a esta rotina automática.

Tarefas que esgotam as três tentativas permanecem em Pendências e podem ser
retomadas manualmente. Somente uma resposta concluída é inserida no histórico
normal da conversa.
