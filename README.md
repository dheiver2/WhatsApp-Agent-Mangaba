# WhatsApp Agent

Agente de atendimento via WhatsApp com:

- backend Python em Starlette
- Redis para estado, fila e deduplicação
- serviço Node.js com Baileys para conexão com WhatsApp Web
- base de conhecimento local em `app/knowledge`

Este README prioriza a execução no Windows sem Docker, usando:

- `PowerShell` para subir a API e o serviço do WhatsApp
- `WSL + Ubuntu` para instalar e rodar o Redis

## Arquitetura

- API HTTP: `http://localhost:8000`
- QR Code / serviço do WhatsApp: `http://localhost:3001`
- Dashboard: `http://localhost:8000/dashboard`
- Redis: `localhost:6379`

## Pré-requisitos

- Windows 10 ou 11
- PowerShell
- WSL com Ubuntu instalado
- Python 3.12
- Node.js 20+
- npm

## Variáveis de ambiente

O projeto lê um arquivo `.env` na raiz. Se precisar recriar esse arquivo, use este modelo:

```env
OPENROUTER_API_KEY=
OPENROUTER_MODEL=deepseek/deepseek-chat-v3-0324
REDIS_URL=redis://localhost:6379/0
WHATSAPP_SERVICE_URL=http://localhost:3001
REDIS_PING_INTERVAL_SECONDS=5
PHONE_LOCK_WAIT_SECONDS=120
PHONE_LOCK_TTL_SECONDS=360
MESSAGE_PROCESSING_TTL_SECONDS=360
MESSAGE_DEDUP_TTL_SECONDS=86400
ONCEHUB_API_KEY=
ONCEHUB_API_BASE_URL=https://api.oncehub.com
ONCEHUB_BOOKING_URL=https://oncehub.com/PAGE-83B77E38F9
ONCEHUB_BOOKING_CALENDAR_ID=
ONCEHUB_WEBHOOK_SECRET=
ONCEHUB_SLOT_LOOKAHEAD_DAYS=14
API_HOST=0.0.0.0
API_PORT=8000
API_SECRET_KEY=change-me
WHATSAPP_API_URL=http://localhost:8000
QR_SERVER_PORT=3001
AGENT_NAME=Andrade & Lemos
AGENT_PERSONA=Assistente juridico especializado em reajuste de plano de saude
MAX_FOLLOWUP_DAYS=7
RESPONSE_TIMEOUT_SECONDS=300
```

`OPENROUTER_API_KEY` é obrigatória para gerar respostas do agente.

## Instalação

### 1. Dependências do Python

No `PowerShell`:

```powershell
cd "C:\Users\dheiver.santos_a3dat\Desktop\whatsapp-agent"

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Se a ativação do ambiente virtual for bloqueada, rode:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### 2. Dependências do serviço do WhatsApp

No `PowerShell`:

```powershell
cd "C:\Users\dheiver.santos_a3dat\Desktop\whatsapp-agent\whatsapp-service"
npm install
```

### 3. Redis no WSL

Os comandos abaixo devem ser executados dentro do Ubuntu no WSL, não no PowerShell.

Primeiro, no `PowerShell`, descubra o nome da distribuição e entre nela:

```powershell
wsl.exe -l -v
wsl.exe -d Ubuntu
```

Se o nome da distro não for `Ubuntu`, use o nome exato retornado por `wsl.exe -l -v`.

Depois, já dentro do Ubuntu, instale o Redis:

```bash
sudo apt-get install lsb-release curl gpg
curl -fsSL https://packages.redis.io/gpg | sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg
sudo chmod 644 /usr/share/keyrings/redis-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/redis.list
sudo apt-get update
sudo apt-get install redis
```

Suba o Redis e valide:

```bash
sudo systemctl start redis-server
redis-cli ping
```

Resultado esperado:

```text
PONG
```

## Execução

Abra 3 janelas separadas.

### Janela 1: Redis

No `PowerShell`:

```powershell
wsl.exe -d Ubuntu
```

No Ubuntu:

```bash
sudo systemctl start redis-server
redis-cli ping
```

### Janela 2: API Python

No `PowerShell`:

```powershell
cd "C:\Users\dheiver.santos_a3dat\Desktop\whatsapp-agent"
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Janela 3: serviço do WhatsApp

No `PowerShell`:

```powershell
cd "C:\Users\dheiver.santos_a3dat\Desktop\whatsapp-agent\whatsapp-service"
npm run dev
```

## Validação

Depois que os 3 processos estiverem ativos:

- Health check da API: `http://localhost:8000/api/v1/health`
- Dashboard: `http://localhost:8000/dashboard`
- QR Code do WhatsApp: `http://localhost:3001`

Endpoints úteis da API:

- `GET /api/v1/health`
- `POST /api/v1/message`
- `GET /api/v1/leads`
- `GET /api/v1/leads/{phone}`
- `GET /api/v1/oncehub/slots`
- `POST /api/v1/oncehub/webhook`
- `GET /api/v1/knowledge/chunks`
- `GET /api/v1/knowledge/graph`
- `GET /api/v1/knowledge/search?q=plano&top_k=5`

Para ativar disponibilidade real e confirmação automática do OnceHub:

- preencha `ONCEHUB_API_KEY` e `ONCEHUB_BOOKING_CALENDAR_ID` no `.env`
- cadastre o webhook do OnceHub apontando para `POST /api/v1/oncehub/webhook`
- se usar assinatura no webhook, configure o mesmo segredo em `ONCEHUB_WEBHOOK_SECRET`

## Estrutura do projeto

```text
app/
  knowledge/         base de conhecimento em .txt
  memory/            estado e histórico por usuário
  rag/               indexação, busca e geração
  static/            dashboard
  whatsapp/          integração da API com mensagens recebidas
whatsapp-service/
  index.js           conexão com WhatsApp, QR e envio/recebimento
data/chroma/         persistência local do índice de conhecimento
scripts/             utilitários
```

## Problemas comuns

### `sudo`, `apt-get` ou `chmod` não funcionam no PowerShell

Você ainda está no shell errado. Entre primeiro no Ubuntu:

```powershell
wsl.exe -d Ubuntu
```

### `curl -fsSL` falha no PowerShell

No PowerShell, `curl` é um alias do `Invoke-WebRequest`. Esse comando de instalação do Redis deve ser rodado no Ubuntu dentro do WSL.

### `redis-cli ping` não responde `PONG`

Tente iniciar o serviço manualmente no Ubuntu:

```bash
sudo systemctl start redis-server
redis-cli ping
```

### A API sobe, mas o agente não responde

Verifique se:

- o Redis está ativo em `localhost:6379`
- o arquivo `.env` existe na raiz
- `OPENROUTER_API_KEY` está preenchida
- se existir `OPENROUTER_API_KEY` definida no PowerShell ou no Windows, reinicie a API; o projeto agora prioriza a chave do `.env`

### O QR não aparece

Verifique se o serviço Node foi iniciado sem erro:

```powershell
cd "C:\Users\dheiver.santos_a3dat\Desktop\whatsapp-agent\whatsapp-service"
npm run dev
```

Depois abra `http://localhost:3001`.

## Execução com Docker

Se quiser subir tudo com Docker:

```powershell
cd "C:\Users\dheiver.santos_a3dat\Desktop\whatsapp-agent"
docker compose up --build
```

Para parar:

```powershell
docker compose down
```
