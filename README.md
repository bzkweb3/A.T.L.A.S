# A.T.L.A.S.

**Assistente de Tarefas, Linguagem, Automação e Sistemas**

> Sua inteligência, em qualquer lugar.

O A.T.L.A.S. é um projeto de inteligência artificial pessoal com um núcleo central lógico, memória persistente e contextual, coordenação futura de agentes especializados e arquitetura preparada para operar de forma híbrida entre nuvem e dispositivos locais.

## Estado atual

**Fase 1 — Fundação**

A primeira versão contém uma API FastAPI mínima, configuração centralizada e documentação inicial da arquitetura.

## Decisões técnicas aprovadas

- Banco inicial: SQLite.
- Integração de IA: abstração independente de provedores.
- Memória: estruturada e relacional.
- Desenvolvimento inicial local, priorizando ferramentas gratuitas.

## Executar localmente

Requer Python compatível com as dependências declaradas em requirements.txt.

~~~powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --reload
~~~

A API ficará disponível em http://127.0.0.1:8000.

- / — informações básicas do sistema.
- /health — verificação de saúde.
- /docs — documentação interativa da API.

## Documentação

- docs/architecture.md — Arquitetura da Fase 1.
- AGENTS.md — Instruções permanentes de desenvolvimento.

## Segurança

Não versione arquivos .env, credenciais, tokens, bancos locais ou a pasta .venv.
