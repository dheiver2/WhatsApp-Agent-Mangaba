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
ONCEHUB_BOOKING_URL=https://oncehub.com/.ELW9PXD6B54K
API_HOST=0.0.0.0
API_PORT=8000
API_SECRET_KEY=change-me
WHATSAPP_API_URL=http://localhost:8000
QR_SERVER_PORT=3001
AGENT_NAME=Natasha
AGENT_PERSONA=Natasha, assistente juridica do escritorio Andrade & Lemos, feminina, carismatica, acolhedora e especializada em reajuste de plano de saude
MAX_FOLLOWUP_DAYS=7
OUTBOUND_WORKER_INTERVAL_SECONDS=300
OUTBOUND_MORNING_HOUR_START=8
OUTBOUND_MORNING_HOUR_END=12
OUTBOUND_EVENING_HOUR_START=18
OUTBOUND_EVENING_HOUR_END=21
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
- `GET /api/v1/outbound/contacts`
- `POST /api/v1/outbound/contacts`
- `POST /api/v1/outbound/run`
- `GET /api/v1/knowledge/chunks`
- `GET /api/v1/knowledge/graph`
- `GET /api/v1/knowledge/search?q=plano&top_k=5`

O agendamento usa somente o link do OnceHub em `ONCEHUB_BOOKING_URL`. O assistente pede que o cliente escolha o melhor dia e horário diretamente nessa agenda.

Modo outbound por lista:

- importe contatos em `POST /api/v1/outbound/contacts`
- Natasha faz no máximo 1 tentativa pela manhã e 1 pela noite enquanto o contato não responder
- ao responder, o contato sai automaticamente da cadência outbound e entra no fluxo normal de diagnóstico
- ao agendar/confirmar, Natasha não volta a insistir

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
