# Autenticação local do A.T.L.A.S.

## Configuração inicial

No PowerShell, na pasta do projeto e com o ambiente virtual ativado:

```powershell
python -m pip install -r requirements.txt
python -m backend.app.auth_cli create-owner
```

Digite uma senha mestra com pelo menos 14 caracteres quando solicitado. O terminal não exibe os caracteres digitados. O A.T.L.A.S. armazena somente um hash Argon2id. O primeiro cadastro só é aceito quando ainda não há proprietário; não existe rota web para configurar ou substituir essa senha.

Inicie o servidor vinculado somente ao loopback:

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Abra `http://127.0.0.1:8000/app`. A primeira visita redireciona para a tela de login. O servidor também valida IP cliente, Host e Origin; requisições de outras interfaces de rede, hosts e origens são recusadas.

## Sessões e dispositivos

- O login cria um token opaco aleatório. Somente seu SHA-256 fica no SQLite; o cookie de sessão é `HttpOnly` e `SameSite=Strict`.
- Uma sessão expira após 12 horas sem atividade ou em 30 dias, o que ocorrer primeiro.
- As rotas privadas incluem chat (streaming e legado), histórico, memória e diagnósticos.
- `GET /api/auth/sessions` lista sessões ativas. `DELETE /api/auth/sessions/{id}` encerra uma sessão; `DELETE /api/auth/devices/{id}` revoga imediatamente todas as sessões daquele dispositivo.
- O navegador recebe um cookie separado para associar sessões ao mesmo dispositivo. Esse identificador não autentica o proprietário.
- Operações que alteram estado exigem Origin da mesma origem e validação CSRF.
- Depois de cinco tentativas incorretas em dez minutos, o login é bloqueado por períodos crescentes, limitados a 15 minutos.

## Recuperação local

Se esquecer a senha, no computador que guarda o banco local execute:

```powershell
python -m backend.app.auth_cli recover-owner
```

Digite exatamente `RECUPERAR A.T.L.A.S.` no terminal e informe a nova senha duas vezes. A recuperação atualiza o hash e revoga todas as sessões existentes. Sem a confirmação literal, nenhuma alteração ocorre. Proteja o acesso ao computador e ao arquivo SQLite: esta recuperação pressupõe acesso local ao ambiente do proprietário.

## Limites e evolução futura

Esta etapa não habilita acesso pela rede nem voz. A palavra de ativação futura `ATLAS` será separada da autenticação: detectar a palavra não cria uma sessão autenticada. Uma futura interface de voz deverá usar uma sessão autenticada existente e manter seu ciclo de estados de áudio separado dos estados de login. A detecção local em standby poderá ser desenvolvida sem enviar áudio continuamente.

Antes de habilitar acesso remoto futuramente, será necessário revisar transporte HTTPS, cookies `Secure`, proteção de borda e política de origem; esta configuração local não autoriza expor o servidor diretamente à internet.
