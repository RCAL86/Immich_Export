# 🚀 Immich ➔ Google Photos Migrator

> Ferramenta automatizada de transferência direta (**Cloud-to-Cloud**) entre servidores **Immich** e o **Google Fotos**, preservando a linha do tempo (timeline), metadados de localização (GPS) e a estrutura completa de álbuns.

---

## 🌟 Por que este projeto foi criado?

Se você já tentou exportar fotos do Immich ou de pastas locais para o Google Fotos, certamente já enfrentou estes problemas:
1. **Perda da Linha do Tempo:** Fotos do WhatsApp, prints de tela e principalmente **vídeos (`.mp4`, `.mov`)** perdem a data de captura original. O Google Fotos acaba agrupando tudo na data do upload ("Hoje"), destruindo a sua timeline.
2. **Álbuns Desfeitos:** Fazer o upload manual solta todas as fotos na biblioteca geral, obrigando você a recriar e organizar cada álbum manualmente.
3. **Falta de Espaço em Disco:** Baixar dezenas ou centenas de gigabytes para o seu HD para só depois enviar para o Google consome muito espaço e tempo.
4. **Erros de Limite de Requisições (429 Too Many Requests):** O Google Fotos possui limites rigorosos de requisições e criações por minuto.

### 💡 Como esta ferramenta resolve:
- **Streaming em Memória:** Baixa o arquivo da API do Immich e envia direto para o Google Fotos — **sem ocupar gigabytes no seu computador**.
- **Preservação de Álbuns:** Lê todos os álbuns do Immich, recria-os automaticamente no Google Fotos e vincula as mídias aos álbuns correspondentes.
- **Injeção de Metadados em Vídeos e Fotos:**
  - Em **vídeos (`.mp4`, `.mov`, `.3gp`)**: Injeta a data original nos átomos internos do contêiner QuickTime (`mvhd`, `tkhd`, `mdhd`). O Google Fotos lê esses cabeçalhos e posiciona os vídeos no dia e ano exatos!
  - Em **fotos (`.jpg`, `.jpeg`, etc.)**: Força a gravação de `DateTimeOriginal`, `DateTimeDigitized` e coordenadas GPS no cabeçalho EXIF com base nos dados do Immich.
- **Resiliente com Retomada Automática (SQLite):** Cada envio bem-sucedido é gravado no banco local `migration.db`. Se a conexão cair ou você parar com `Ctrl + C`, ele retoma de onde parou sem reenviar nada repetido.
- **Backoff Exponencial (Anti-429):** Gerencia automaticamente pausas estratégicas e retentativas caso o Google acione limites temporários por minuto.

---

## 📋 Pré-requisitos

- **Python 3.10** ou superior instalado no computador.
- Um servidor **Immich** ativo com acesso à interface web.
- Uma conta **Google** com espaço disponível no Google Fotos.
- Um projeto no **Google Cloud Console** (gratuito) para gerar a credencial OAuth.

---

## 🛠️ Passo a Passo de Instalação e Configuração

### 1. Clonar o Repositório e Instalar Dependências

```bash
# Clone o repositório
git clone https://github.com/RCAL86/Immich_Export.git
cd Immich_Export

# Crie e ative o ambiente virtual (Windows PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# No Linux/macOS:
# python3 -m venv venv
# source venv/bin/activate

# Instale os pacotes necessários
pip install -r requirements.txt
```

---

### 2. Gerar a API Key no Immich

1. Acesse o seu servidor Immich no navegador.
2. Clique na sua foto de perfil no canto superior direito e vá em **Account Settings** (Configurações da Conta).
3. Na seção lateral, clique em **API Keys**.
4. Clique em **New API Key**, dê um nome (ex: `Migrador Google`) e copie o token gerado.

---

### 3. Configurar as Credenciais no Google Cloud (`credentials.json`)

Para que o script tenha permissão de enviar as fotos para a sua conta Google:

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/).
2. No menu superior, clique em selecionar projeto e crie um **Novo Projeto** (ex: `Immich Migrator`).
3. Vá no menu lateral **APIs e Serviços > Biblioteca**:
   - Pesquise por **Google Photos Library API**.
   - Clique nela e selecione **Ativar**.
4. Acesse **APIs e Serviços > Tela de permissão OAuth** (OAuth consent screen):
   - Tipo de usuário: selecione **Externo** (External) e clique em Criar.
   - Preencha o *Nome do app* (ex: `Immich Migrator`) e o seu *E-mail de suporte*.
   - Prossiga até a aba **Usuários de Teste** (Test Users).
   - **IMPORTANTE:** Clique em **+ Add Users** e adicione o seu próprio e-mail do Google (a conta onde as fotos serão salvas).
   - Salve até o fim.
5. Acesse **APIs e Serviços > Credenciais**:
   - Clique em **+ Criar Credenciais > ID do cliente OAuth**.
   - Tipo de aplicativo: selecione **Aplicativo para Computador** (Desktop App).
   - Nome: `Immich Desktop Client`.
   - Clique em **Criar**.
   - Na janela que abrir, clique em **Fazer o download do JSON**.
6. Renomeie o arquivo baixado para **`credentials.json`** e coloque-o na raiz da pasta deste projeto.

---

### 4. Configurar as Variáveis de Ambiente (`.env`)

Copie o arquivo de exemplo:
```powershell
Copy-Item .env.example .env
```
*(No Linux/macOS: `cp .env.example .env`)*

Abra o arquivo `.env` em um editor e preencha:

```env
# URL do seu servidor Immich (com porta, se houver)
IMMICH_URL=https://seu-servidor-immich.com
IMMICH_API_KEY=seu_token_api_do_passo_2

# Arquivo baixado do Google Cloud
GOOGLE_CREDENTIALS_FILE=credentials.json

# Opções de Migração
SYNC_ALBUMS=true
INJECT_EXIF=true

# Pausa em segundos entre requisições (evita o erro 429 do Google)
REQUEST_DELAY_SECONDS=1.5
```

---

## 🚀 Como Usar

### Menu Interativo

Basta executar o script principal:

```powershell
.\venv\Scripts\python main.py
```

Você verá o painel interativo:
```text
┌─────────────────────────────────┐
│ Immich ➔ Google Photos Migrator │
└─────────────────────────────────┘
1. Iniciar Sincronização / Migração Completa
2. Testar Conexões (Immich e Google Fotos)
3. Ver Status e Progresso Atual
4. Organizar Álbuns Agora (vincular fotos aos álbuns sem re-upload)
5. Resetar Vídeos no Banco (para reenviar com datas corrigidas)
6. Sair
```

1. **Opção 1 (Sincronização Completa):** Faz tudo no automático! Lê álbuns, ajusta datas, faz streaming de cada arquivo e registra diretamente nos álbuns do Google Fotos.
2. **Opção 2 (Testar Conexões):** Valida se o Immich e as credenciais do Google estão respondendo.
3. **Opção 3 (Ver Status):** Exibe a contagem e porcentagem em tempo real.
4. **Opção 4 (Organizar Álbuns):** Vincula fotos que já estão no Google Fotos aos seus álbuns correspondentes sem baixar nem subir nenhum arquivo novamente.
5. **Opção 5 (Resetar Vídeos):** Caso queira reenviar apenas vídeos para calibrar datas.

### Comandos Rápidos via Linha de Comando (CLI)

- **Iniciar diretamente a transferência:**
  ```powershell
  .\venv\Scripts\python main.py sync
  ```
- **Acompanhar o progresso em tempo real:**
  ```powershell
  .\venv\Scripts\python main.py status
  ```
- **Vincular fotos aos álbuns no Google Fotos (sem re-upload):**
  ```powershell
  .\venv\Scripts\python main.py sync-albums
  ```
- **Testar conectividade com ambas as APIs:**
  ```powershell
  .\venv\Scripts\python main.py test
  ```
- **Resetar status de vídeos (se precisar reenviá-los):**
  ```powershell
  .\venv\Scripts\python main.py reset-videos
  ```

---

## 📊 Acompanhamento do Progresso

Ao rodar `python main.py status` (inclusive em outro terminal enquanto a migração ocorre), você verá um relatório detalhado:

```text
                📊 Status e Progresso da Migração                 
┌──────────────────────────┬─────────────────────────────────────┐
│ Métrica                  │ Valor                               │
├──────────────────────────┼─────────────────────────────────────┤
│ Total de Itens no Immich │ 14.383 (13.208 fotos / 1.175 vídeos)│
│ Transferidos com Sucesso │ 11.798                              │
│ Itens Restantes          │ 2.585                               │
│ Progresso Concluído      │ 82,0%                               │
│ Itens com Falha          │ 1                                   │
│ Álbuns Sincronizados     │ 34                                  │
└──────────────────────────┴─────────────────────────────────────┘
```

Durante a transferência, cada linha exibe o contador e a porcentagem:
`[11799/14383 | 82.0%] ⬇️ Baixando: foto.jpg...`

---

## 🔒 Segurança e Privacidade

- **Permissões Mínimas (`photoslibrary.appendonly`):** O aplicativo solicita ao Google exclusivamente a permissão de **adicionar** novos itens e álbuns. Ele **não pode ler, apagar ou modificar** fotos pré-existentes na sua conta Google.
- **Privacidade Local:** Nenhuma chave de API, arquivo de credencial ou arquivo de mídia passa por servidores de terceiros. A comunicação é 100% direta entre o seu servidor Immich, seu computador e os servidores do Google.
- O arquivo `.gitignore` já vem configurado de fábrica para não enviar seus arquivos sensíveis (`credentials.json`, `token.json`, `.env`, `migration.db`) para o repositório Git.

---

## 📄 Licença

Distribuído sob a licença **MIT**. Consulte `LICENSE` para mais detalhes.
