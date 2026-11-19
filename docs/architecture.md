# Arquitetura inicial do A.T.L.A.S.

## Direção

O A.T.L.A.S. terá um núcleo central lógico, acessível por diferentes interfaces e preparado para coordenar memória, provedores de inteligência artificial e agentes especializados. Os componentes concretos serão ligados ao núcleo por contratos para reduzir dependência de fornecedores e ambientes.

O desenvolvimento e a execução atuais permanecem locais. A fundação permite uma implantação híbrida futura. Nesta entrega, a primeira integração real usa a API da OpenAI por trás de um contrato independente de provedor.

## Componentes

- `api`: recebe requisições HTTP e valida entradas.
- `core`: contém configurações transversais e leitura de variáveis de ambiente.
- `intelligence`: define o contrato de IA e o adaptador OpenAI.
- `frontend`: interface web inicial do A.T.L.A.S.
- `tests`: testes automatizados com provedor simulado, sem chamadas pagas.

## Integração de IA

O endpoint `POST /api/chat` recebe o histórico recente enviado pelo cliente e devolve a resposta do assistente. A implementação usa o SDK oficial da OpenAI e a Responses API. A chave é lida somente no backend por meio de `OPENAI_API_KEY`; o modelo é configurável por `ATLAS_AI_MODEL`, com padrão inicial `gpt-5.5`.

Crie um arquivo local `.env` com:

```dotenv
OPENAI_API_KEY=sua_chave_aqui
ATLAS_AI_MODEL=gpt-5.5
ATLAS_ENV=development
```

O arquivo `.env` é ignorado pelo Git. Nunca coloque a chave em arquivos frontend, no repositório, em capturas de tela ou em mensagens. O arquivo `.env.example` contém somente nomes e valores ilustrativos.

## Limites conhecidos desta versão

- O histórico de conversa fica temporariamente na memória da página e é enviado novamente a cada mensagem.
- Ainda não há persistência de conversas, memória estruturada, autenticação, controle multiusuário ou agentes executores.
- A interface inicial está em `/app`; a rota `/` e a rota `/health` foram preservadas.
- Testes usam um provedor simulado e não consomem créditos de API.
- A execução local e a instalação das dependências precisam ser verificadas no computador de desenvolvimento.

## Próxima evolução

Implementar memória relacional em SQLite, gestão de conversas e contexto persistente, mantendo a separação entre API, aplicação, inteligência e infraestrutura.
