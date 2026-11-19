# A.T.L.A.S. — Arquitetura da Fase 1

## Visão

O A.T.L.A.S. terá um núcleo central lógico, independente das interfaces, dos provedores de inteligência artificial e das implementações de persistência. A primeira execução será local; os contratos deverão permitir uma evolução futura para uma arquitetura híbrida, com núcleo em nuvem e componentes locais autorizados.

## Decisões aprovadas

- **Banco inicial:** SQLite, com acesso isolado por uma camada de persistência.
- **Inteligência artificial:** abstração de provedores. Nenhum fornecedor ou modelo está definido nesta etapa.
- **Memória:** estruturada e relacional. Busca vetorial não faz parte da Fase 1.
- **Execução:** desenvolvimento local, sem contratação de infraestrutura paga nesta etapa.
- **Segurança:** negar por padrão; agentes e ações futuras terão identidade, capacidades e permissões explícitas.

## Limites da primeira entrega

A fundação começa pela configuração centralizada e inicialização da API. Persistência, memória, autenticação e integração real com IA serão adicionadas em etapas separadas, com testes e revisão.

Agentes de computador, navegador e arquivos não serão executados nesta fase. Voz, dispositivos, automações avançadas e interfaces espaciais permanecem para as fases previstas no documento mestre.

## Estrutura lógica

~~~text
Interfaces
   |
API FastAPI
   |
Núcleo / serviços de aplicação
   |-- políticas e autorização
   |-- memória estruturada
   |-- abstração de provedor de IA
   |-- contratos futuros de agentes
   |
Infraestrutura
   |-- SQLite
   |-- implementações técnicas
~~~

## Configuração atual

- ATLAS_ENV: development, test ou production.
- ATLAS_LOG_LEVEL: CRITICAL, ERROR, WARNING, INFO ou DEBUG.

Configurações secretas não devem ser versionadas. A configuração será ampliada quando banco, autenticação e provedores forem introduzidos.

## Critérios de evolução

Cada etapa deve:
1. Ter escopo pequeno e explícito.
2. Preservar as rotas e comportamentos já aprovados.
3. Incluir testes automatizados adequados.
4. Documentar decisões e dependências.
5. Ser revisada antes de avançar para a próxima etapa.
