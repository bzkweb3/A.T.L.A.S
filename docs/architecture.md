# Arquitetura atual do A.T.L.A.S.

## Direção

O A.T.L.A.S. está em desenvolvimento local na Fase 1 — Fundação. A aplicação mantém uma API central, uma interface web inicial, memória local persistente e provedores de IA conectados por contrato. A arquitetura deve continuar independente de fornecedor e preparada para componentes locais e remotos, sem exigir infraestrutura em nuvem nesta etapa.

## Componentes implementados

- `backend/app/api`: endpoints HTTP de chat, conversas, memória e diagnóstico.
- `backend/app/core`: configuração, regras de chat e serviços de memória.
- `backend/app/intelligence`: contrato de provedor e adaptadores OpenAI e Gemini.
- `backend/app/persistence`: conexões SQLite e repositórios para conversas e fatos.
- `frontend`: interface local de conversa e diagnóstico.
- `tests`: testes automatizados que usam provedores simulados.

## Fluxo atual

1. A interface envia mensagens para `POST /api/chat`.
2. A API valida o pedido e consulta a memória persistente relevante.
3. O serviço de inteligência chama o provedor configurado por meio do contrato `AIProvider`.
4. A troca é gravada em SQLite e a resposta retorna à interface.

O Gemini é o provedor padrão no código atual. OpenAI também pode ser selecionado por configuração. As chaves são lidas no backend; não devem ser incluídas no frontend nem versionadas.

## Persistência local

`SQLiteDatabase` administra conexões, ativa chaves estrangeiras e cria o esquema inicial. `ConversationRepository` persiste conversas e mensagens; `MemoryRepository` persiste fatos explícitos do usuário. Os serviços em `core` aplicam regras de aplicação e delegam operações SQL aos repositórios.

O banco é local, configurado por `ATLAS_DATABASE_PATH` e ignorado pelo Git. A versão do esquema é registrada em `PRAGMA user_version`. A versão inicial adota as tabelas existentes do MVP com `CREATE TABLE IF NOT EXISTS`, preservando os dados locais já gravados. Um banco criado por uma versão mais nova é recusado para evitar abertura incompatível. Ainda não há ferramenta externa de migrações; PostgreSQL não está implementado.

## Memória atual e limites

A memória de longo prazo armazena fatos simples por categoria e chave, com valor, origem e datas. Há operações de criação/atualização, consulta e exclusão individual. Algumas declarações explícitas são extraídas por regras de texto e fatos relevantes são incluídos no contexto enviado ao provedor.

Ainda faltam classificação e proteção diferenciada de dados sensíveis, autenticação, autorização por usuário, gestão completa de perfil/projetos/decisões/tarefas e exclusão de conversas pela API. A extração atual é baseada em padrões simples e não representa compreensão geral de linguagem.

## Limites desta etapa

- O sistema ainda não planeja tarefas nem coordena agentes executores.
- Nenhuma ação externa ou controle de dispositivo é executado.
- Não há autenticação ou autorização; a aplicação atual é voltada a uso local individual.
- Não há busca vetorial.
- Não há implantação em nuvem ou arquitetura distribuída em execução.
- Testes automatizados existem, mas devem ser executados separadamente para validar cada alteração.

## Próximos passos da fundação

1. Evoluir as migrações com cada mudança de esquema e definir o ciclo de vida da conexão da aplicação.
2. Estruturar a memória relacional com origem, classificação e tratamento de dados sensíveis.
3. Definir autenticação local e autorização antes de expor a API fora da máquina.
4. Atualizar os contratos e a documentação conforme a aplicação evoluir.

Agentes, execução de ações, componentes de nuvem e comunicação com dispositivos permanecem para etapas posteriores, após a consolidação da fundação e do modelo de permissões.
