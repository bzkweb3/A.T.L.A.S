# A.T.L.A.S.

**Assistente de Tarefas, Linguagem, Automação e Sistemas**

Sua inteligência, em qualquer lugar.

## Primeira versão funcional

Esta etapa inclui uma interface web de conversa e uma camada de provedores de IA. O Gemini é o provedor padrão para desenvolvimento; a integração OpenAI permanece disponível como alternativa.

### Requisitos

- Python 3.11 ou superior.
- VS Code ou outro editor Python.
- Chave Gemini API (para o provedor padrão) ou chave OpenAI API.

### Configuração local no Windows

1. Abra a pasta do projeto no VS Code.
2. Abra o terminal integrado pelo menu **Terminal → Novo Terminal**.
3. Crie e ative um ambiente virtual, se ainda não existir:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Instale as dependências:

   ```powershell
   python -m pip install -r requirements.txt
   ```

5. Copie `.env.example` para um novo arquivo chamado `.env` na raiz do projeto.
6. Para usar Gemini, configure `ATLAS_AI_PROVIDER=gemini`, `ATLAS_AI_MODEL=gemini-2.5-flash` e preencha `GEMINI_API_KEY`.
7. Para usar OpenAI, configure `ATLAS_AI_PROVIDER=openai`, informe o modelo desejado em `ATLAS_AI_MODEL` e preencha `OPENAI_API_KEY`.
8. Nunca compartilhe chaves em conversas, capturas de tela ou repositórios.
9. Inicie o servidor:

   ```powershell
   python -m uvicorn backend.app.main:app --reload
   ```

10. Abra `http://127.0.0.1:8000/app` no navegador.

### Testes

Com as dependências instaladas, execute:

```powershell
python -m pytest -v
```

Os testes de chat utilizam um provedor simulado e não fazem chamadas pagas às APIs.

## Rotas

- `/app`: interface inicial.
- `/`: status básico do sistema.
- `/health`: verificação de disponibilidade.
- `/api/chat`: endpoint de conversa.
- `/docs`: documentação interativa da API.

## Configuração da IA

- `ATLAS_AI_PROVIDER`: provedor ativo; `gemini` ou `openai`. Padrão: `gemini`.
- `ATLAS_AI_MODEL`: modelo utilizado pelo provedor selecionado.
- `GEMINI_API_KEY`: chave privada do Google Gemini.
- `OPENAI_API_KEY`: chave privada da OpenAI.
- `ATLAS_ENV`: ambiente de execução; padrão `development`.

O arquivo `.env` não deve ser versionado. O repositório contém apenas `.env.example`, sem credenciais reais.

## Limites desta versão

O histórico existe apenas enquanto a página permanece aberta. Memória persistente, SQLite, autenticação e agentes executores serão implementados em etapas posteriores. Ações externas não são executadas por esta versão.
