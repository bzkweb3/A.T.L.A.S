# Arquitetura inicial do A.T.L.A.S.

## Direção

O A.T.L.A.S. terá um núcleo central lógico, acessível por diferentes
interfaces e preparado para coordenar memória, provedores de inteligência
artificial e agentes especializados. Os componentes concretos serão ligados
ao núcleo por contratos para reduzir dependência de fornecedores e ambientes.

O desenvolvimento e a execução atuais permanecem locais. A fundação deve
permitir uma implantação híbrida futura, sem introduzir agora serviços de
nuvem, agentes executáveis ou provedores reais de IA.

## Limites da primeira etapa

- `api` recebe requisições HTTP, valida entradas e apresenta respostas.
- `core` contém configuração e políticas transversais.
- `application` coordenará casos de uso e contratos entre a API e o núcleo.
- `memory` conterá os modelos e serviços de memória estruturada.
- `intelligence` definirá o contrato independente de provedor.
- `orchestrator` coordenará o fluxo central e, em fases futuras, agentes.
- `infrastructure` conterá implementações técnicas como SQLite e integrações.

Na etapa atual, somente a configuração básica e a fábrica da aplicação FastAPI
estão implementadas. Banco de dados, autenticação, integração real com IA,
memória e execução de agentes ainda não fazem parte do backend.

## Configuração atual

O processo lê `ATLAS_ENV` (`development`, `test` ou `production`) do ambiente
do processo. O padrão é `development`. Um valor inválido interrompe a
inicialização com uma mensagem clara. A configuração fica disponível no estado
da aplicação para os próximos módulos e não é incluída nas respostas HTTP.

Ainda não há leitura de arquivo `.env` nem configuração de segredos, banco,
autenticação ou provedor de IA. Esses parâmetros serão definidos junto às
respectivas etapas, sem guardar credenciais no código ou no repositório.

## Decisões já consolidadas

- SQLite será o banco inicial, local e isolado por uma camada de persistência.
- O desenho deve permitir avaliar PostgreSQL futuramente, sem implementá-lo
  nesta fase.
- O núcleo usará uma abstração de provedor de IA; nenhum provedor real será
  escolhido ou conectado nesta etapa.
- A memória será estruturada e relacional; busca vetorial fica fora da Fase 1.
