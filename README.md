# A.T.L.A.S.

**Assistente de Tarefas, Linguagem, Automação e Sistemas**

Sua inteligência, em qualquer lugar.

## Primeira versão funcional

Esta etapa adiciona uma interface web de conversa e integração de backend com a API da OpenAI, mantendo uma camada de provedor independente.

### Requisitos

- Python 3.11 ou superior (recomendado: Python 3.12).
- Uma chave de API da OpenAI com faturamento configurado.
- VS Code ou outro editor Python.

### Configuração local no Windows

1. Abra a pasta do projeto no VS Code.
2. Abra o terminal integrado pelo menu **Terminal → Novo Terminal**.
3. Crie um ambiente virtual:

   ```powershell
   py -m venv .venv
   ```

4. Ative o ambiente:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   Se a política do PowerShell impedir a ativação, use o interpretador `.venv\Scripts\python.exe` diretamente nos comandos seguintes.

5. Instale as dependências:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

6. Copie `.env.example` para um novo arquivo chamado `.env` na raiz do projeto.
7. Abra o arquivo `.env` e substitua o valor de `OPENAI_API_KEY` pela sua chave. Não envie a chave em conversas, capturas de tela ou repositórios.
8. Inicie o servidor:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
   ```

9. Abra `http://127.0.0.1:8000/app` no navegador.

### Testes

Com as dependências instaladas, execute:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Os testes de chat utilizam um provedor simulado e não fazem chamadas pagas à API.

## Rotas

- `/app`: interface inicial.
- `/`: status básico do sistema.
- `/health`: verificação de disponibilidade.
- `/api/chat`: endpoint de conversa.
- `/docs`: documentação interativa da API.

## Configuração da IA

- `OPENAI_API_KEY`: chave privada, lida exclusivamente pelo backend.
- `ATLAS_AI_MODEL`: modelo de IA; padrão inicial `gpt-5.5`.
- `ATLAS_ENV`: ambiente de execução; padrão `development`.

O arquivo `.env` não deve ser versionado. O repositório contém apenas `.env.example`, sem credenciais reais.

## Limites desta versão

O histórico existe apenas enquanto a página permanece aberta. Memória persistente, SQLite, autenticação e agentes executores serão implementados em etapas posteriores. Ações externas não são executadas por esta versão.
