# 08 · Bot do Telegram

Arquivo: `scripts/telegram_bot.py` (821 linhas). Cliente da Bot API:
`app/services/telegram_service.py`.

## O que ele é

A interface principal no celular quando o app não está aberto. **Privado**:
responde só ao `TELEGRAM_CHAT_ID` configurado; qualquer outro chat é ignorado e
logado.

**Roda no Pi**, unit `investimentos-bot.service`. ⚠️ **Nunca rode em duas
máquinas** — os dois fazem long polling e o cliente recebe resposta em dobro.
Proteção local: pidfile em `storage/telegram_bot.pid` (single-instance) — desde
2026-08-06 usa o lock compartilhado do `analysis_runner` (criação atômica
`O_EXCL` + identidade pid/starttime), então um PID reciclado pós-reboot nunca
prende o bot num loop de `Restart=always` (A28).

## Texto sem `/` = conversa com o consultor

Qualquer mensagem que não comece com `/` vira um turno do consultor
(`chat_service.converse(text, ChatChannel.TELEGRAM)`), que é **a mesma conversa**
da página `/consultor`.

- Fila serial (`_chat_queue` + `_chat_worker`): um turno por vez, na ordem. Se
  houver 2+ na frente, o bot avisa "📥 Na fila".
- Indicador "digitando…" renovado a cada 5s enquanto o turno roda.
- O worker sobrevive a qualquer exceção — erro vira mensagem, não morte do bot.

## Os 16 comandos

Registrados via `setMyCommands` no boot (aparecem no menu do Telegram).

### Finanças pessoais
| Comando | O que faz |
|---|---|
| `/gasto <valor> [descrição #categoria]` | registro rápido de gasto (`source=bot`) |
| `/ganho <valor> [descrição #categoria]` | registro rápido de ganho |
| `/financas [AAAA-MM]` | resumo do mês: gastos × ganhos × saldo, por categoria |
| `/resetchat` | descarta a sessão do consultor (a memória fixa fica) |

### Investimentos
| Comando | O que faz |
|---|---|
| `/aporte <valor>` | cria o aporte e roda o comitê inteiro (opus/max). Devolve onde investir e quanto |
| `/ordens` | folha de ordens pendente do último aporte |
| `/executei <ticker> <qtd> <preço>` | confirma execução; o lote **herda tese, alvo e stop** do comitê |
| `/comprei <ticker> <classe> <qtd> <preço>` | compra avulsa. Classe: `rf`, `acoes` ou `crypto` (aceita aliases) |
| `/vender <ticker>` | venda com **confirmação em 2 passos** (expira em 120s). Bloqueia ação/crypto antes de 30d; CDB sempre libera |
| `/carteira` | posições e o que já pode ser vendido |
| `/atualizar` | marcação a mercado agora |
| `/revisao` | roda a revisão semanal do comitê agora |
| `/relatorios` | últimos relatórios (semanais e de maturidade) |
| `/ir [ano]` | apuração simplificada de IR (DARF por mês) |
| `/status` | alocação atual vs alvo, análises rodando agora, análises travadas, última revisão |
| `/ajuda` | a mensagem de ajuda |

**Sem alias `fii`** em `_CLASS_ALIASES`, de propósito: FII está fora do mandato.

`_parse_amount` entende formato pt-BR: `5.000,50`, `5000,50`, `R$ 5000`.

## Fotos e arquivos

| Tipo | Comportamento |
|---|---|
| Foto / documento (PDF, CSV, planilha) ≤20 MB | baixado via `getFile` para `storage/chat_workspace/inbox/` e enfileirado como turno do consultor. Cupom vira gasto registrado; extrato/fatura vira lançamentos |
| Acima de 20 MB | aviso (é o teto de download da Bot API) |
| Áudio, voz, vídeo, sticker, animação, localização, contato | aviso de "não leio esse tipo" |
| Mensagem de serviço (entrou no grupo etc.) | **silêncio** |

Nome de arquivo é saneado (`_safe_filename`: só ASCII word chars, ponto e
traço) — sem path traversal. Foto: o Telegram lista tamanhos em ordem crescente,
então o bot pega o **último** (o maior).

## Envio: markdown → Telegram HTML

`telegram_service.format_for_telegram()`:

- `**negrito**` e `# título` → `<b>`
- `` `código` `` → `<code>`
- **Tabelas markdown → blocos `<pre>` monoespaçados alinhados** (o Telegram não
  tem tabela)
- Chunking em 4000 chars (o limite duro é 4096)
- Se o envio HTML for rejeitado, cai para texto puro — **uma mensagem nunca se
  perde**
- Token é redigido de qualquer log de erro

Também expõe `send_document` (usado pelo relatório mensal, que manda um `.md`
anexo), `download_file`, `send_chat_action` e `set_my_commands`.

## Pareamento seguro

`scripts/telegram_setup.py` imprime um **código de 6 dígitos** e só o chat que
enviar exatamente esse código vira o dono. Antes disso, o primeiro chat aleatório
que mandasse `/start` sequestrava o bot. O `chat_id` é gravado no `.env`.

## Notificações automáticas

O bot é o canal de saída de tudo:

| Evento | Mensagem |
|---|---|
| Aporte concluído | folha de ordens limpa (bloco de máquina removido) + lembrete do `/executei` |
| Revisão semanal | relatório executivo |
| Lote maturou (30d) | aviso de maturidade com recomendação por lote |
| Alvo/stop cruzado | alerta de nível (1 por cruzamento) |
| Relatório mensal | texto + anexo `.md` |
| **Qualquer cron que quebrou** | erro explícito — não só o sucesso |
| Auto-resume desistiu (5 falhas) | aviso de que parou de tentar |

## Onde mexer

| Quero… | Mexa em |
|---|---|
| adicionar um comando | `_HELP`, `_BOT_COMMANDS` e o dispatch em `_handle()` — os três |
| mudar a formatação de saída | `telegram_service.format_for_telegram` |
| mudar o comportamento conversacional | `_CONSULTANT_ORDERS` em `chat_service.py` (não no bot) |
| aceitar um tipo novo de mídia | `_extract_media` + `_UNSUPPORTED_MEDIA_KEYS` |

Testes: `tests/test_bot_media.py` (6) e `tests/test_telegram_service.py` (5).
