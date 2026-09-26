# F15 · Entrega por e-mail e arquivo autenticado

| | |
|---|---|
| **Status** | ✅ **Concluída (26/09/2026)** — bloqueio aceito no Netlify real e ensaio de envio real feito; a lista de destinatários entra a partir da 202608 (ver "Fechamento") |
| **Esforço** | L (1 a 3 dias) — pode ser cortada em duas (ver ordem de entrega) |
| **Fase** | produção |
| **Depende de** | [F04](F04-religar-dbt-no-flow.md), [F06](F06-janela-resiliente.md) |
| **Recomendada junto** | [F11](F11-observabilidade.md) — sem alerta de falha, um envio que não acontece é indistinguível de "ainda não publicou" |
| **Decisões associadas** | [D08](../decisoes/D08-gestao-de-segredos.md), [D07](../decisoes/D07-repositorio-publico.md) |

## Objetivo

Todo mês, quando o PDET publicar uma competência nova, o projeto gera **um boletim e uma
planilha** e os envia por **e-mail a uma lista**. Cada boletim e planilha enviados fica
guardado num **arquivo consultável**, protegido por **login e senha**.

Nada disto existe hoje: os docs só citam e-mail como canal de *alerta* (F11).

## Decisões já tomadas

| | Escolha | Porquê |
|---|---|---|
| Hospedagem do arquivo | **Netlify** (site estático) | plano gratuito; sem RAM na VM (~830 MiB, dividida com o observia); sem porta pública |
| Autenticação | **Netlify Identity**, modo *somente convite*, e-mail + senha | usuário e senha com recuperação de conta, incluído nos planos gratuitos |
| Bloqueio | **Edge Function** que nega tudo por padrão (*fail closed*) | o Identity protege no nível da aplicação: sem esta camada, um PDF em URL pública é baixável sem login |
| Publicação | **Repositório privado dedicado** conectado ao Netlify | sem Node na VM; o histórico do git é o backup do que foi enviado |
| Acesso à UI do Prefect | túnel SSH, portas em `127.0.0.1` | Tailscale não é necessário em produção; a única porta pública é a do SSH |

**Ainda aberta:** o *provedor* de e-mail (conta e domínio). O código fala SMTP puro, então
qualquer provedor serve — ver "Envio do e-mail".

## Ordem de entrega

Cada bloco é verificável sozinho; dá para parar depois de qualquer um.

1. **Arquivo protegido com página de teste** — o bloqueio funcionando *antes* de qualquer
   arquivo real existir (ver "O primeiro deploy").
2. **Geração + arquivamento** do boletim e da planilha por competência.
3. **Envio idempotente** por e-mail.

Se precisar cortar em duas fatias, o corte natural é entre (1) e (2)+(3).

---

## 1. Arquivo protegido no Netlify

### Estrutura do repositório do arquivo

Repositório **separado e privado** (não este). O pipeline só adiciona arquivos e dá `push`.

```
arquivo/
├── netlify.toml
├── package.json                      # dependências da edge function
├── netlify/edge-functions/gate.ts    # o bloqueio
└── public/
    ├── login.html                    # única página pública
    ├── index.html                    # gerado pelo pipeline: lista as competências
    └── 2026-06/
        ├── boletim-202606.pdf
        └── planilha-202606.xlsx
```

### O bloqueio: negar por padrão

A regra é **tudo exige login, exceto uma lista explícita**. O erro clássico é o inverso:
proteger só `/privado/*` e esquecer um caminho.

```ts
// netlify/edge-functions/gate.ts  — ESBOÇO: validar contra a documentação do Netlify
import { getUser } from '@netlify/identity'
import type { Config, Context } from '@netlify/edge-functions'

const PUBLICO = ['/login.html', '/favicon.ico']   // allow-list explícita

export default async (req: Request, context: Context) => {
  const { pathname } = new URL(req.url)
  if (PUBLICO.includes(pathname)) return context.next()

  const user = await getUser()
  if (!user) return Response.redirect(new URL('/login.html', req.url), 302)
  if (!user.roles?.includes('leitor')) return new Response('Forbidden', { status: 403 })

  const resp = await context.next()
  resp.headers.set('Cache-Control', 'private, no-store')
  return resp
}

export const config: Config = { path: '/*' }
```

Pontos a confirmar, porque **não foram verificados**:

- que a função intercepta **arquivos estáticos** (PDF, XLSX), não só rotas HTML — é
  exatamente o que o teste de aceite abaixo pega;
- que um **erro dentro da função falha fechado** (nega), em vez de deixar a requisição
  passar; veja a opção de comportamento em caso de erro das edge functions;
- a assinatura exata de `getUser()` e de `context.next()` na versão instalada.

### Segunda camada (opcional): redirect por papel

O Netlify também aceita regras de redirect com condição de papel, avaliadas na borda:

```toml
[[redirects]]
from = "/*"
to = "/:splat"
status = 200
force = true
conditions = {Role = ["leitor"]}

[[redirects]]
from = "/*"
to = "/login.html"
status = 401
force = true
```

A documentação que li não diz se isso vale para o Identity nos planos gratuitos (só
declara restrição de plano para provedores JWT externos). **Trate como bônus**: se o plano
não aceitar, a edge function sozinha continua sendo a proteção. O teste de aceite diz qual
das duas está valendo.

### Cabeçalhos

```toml
[[headers]]
for = "/*"
  [headers.values]
  X-Robots-Tag = "noindex, nofollow"
  Referrer-Policy = "no-referrer"
  X-Content-Type-Options = "nosniff"
  Cache-Control = "private, no-store"
```

Mais um `robots.txt` com `Disallow: /`. Isto **não é proteção** — é para o site não
aparecer em buscadores caso a URL vaze.

### Configuração do Identity

| Item | Valor |
|---|---|
| Registro | **Somente convite** (nunca aberto) |
| Provedores externos (Google etc.) | desligados, a menos que você os queira |
| Papéis | `leitor` para os destinatários; um papel de administração para você |
| Convite | pelo painel; cada pessoa define a própria senha pelo link |
| Política de senha | verifique se o tamanho mínimo é configurável; se não, oriente senha longa |
| Autenticação de dois fatores | **não vi na documentação** — não presuma que exista |
| E-mails de convite e recuperação | os modelos padrão do Netlify (personalizá-los é recurso Pro); confira que **não caem em spam** |

**Remover uma pessoa não é imediato.** Mudanças de papel não invalidam tokens já emitidos:
a pessoa removida continua com acesso até o token expirar ou renovar. Registre o prazo real
(confirme; costuma ser da ordem de uma hora) e aceite-o, ou encurte-o.

### Configuração do projeto no Netlify

- **Só a branch de produção** faz deploy. Desligue *deploy previews* e *branch deploys*:
  menos URLs a proteger.
- **Autenticação de dois fatores na conta do Netlify.** É a chave mestra: quem entra na
  conta administra tudo, inclusive os usuários.
- **Chave de escrita** do pipeline no repositório do arquivo: *deploy key* restrita a esse
  único repositório, guardada fora do git ([D08](../decisoes/D08-gestao-de-segredos.md)).
- Confirme o consumo de **créditos** por deploy no plano gratuito: 1 deploy por mês deve
  sobrar, mas é um número a checar, não a supor.

### O primeiro deploy

Cada deploy no Netlify tem uma URL permanente própria, e **deploys antigos continuam
acessíveis**. Se um arquivo real for publicado antes de o bloqueio existir, ele fica
público naquele endereço para sempre.

Por isso o **primeiro deploy contém só o bloqueio e uma página de teste**. Nenhum boletim
entra até o teste de aceite passar.

---

## 2. Gerar e arquivar

1. Ao fim do run com competência nova, gerar `boletim-AAAAMM.pdf` (ou `.html`) e
   `planilha-AAAAMM.xlsx` a partir do **mart**, não do raw (que será apagado — F07).
2. Copiar para `public/AAAA-MM/` no repositório do arquivo, regenerar o `index.html` e
   dar `push`. O Netlify publica.
3. Registrar o **sha256** de cada arquivo.

### Arquivar o que foi enviado, não regenerar

O CAGED recebe declarações fora do prazo e exclusões que corrigem meses anteriores
([F12](F12-for-exc-reconciliacao.md)). Um boletim regenerado hoje para 202603 pode dar
números diferentes do que a lista recebeu em abril. O arquivo existe para responder
"o que foi enviado", então guarda-se **exatamente os bytes que foram anexados**.

Essas saídas **não se regeneram** e são o único produto durável do projeto: o histórico
do git do repositório privado é o backup. Teste a restauração clonando-o do zero.

---

## 3. Envio idempotente

### O estado: "já enviei a competência X?"

O cron é diário porque a data de publicação do PDET é imprevisível. Sem estado, o flow
reenviaria todo dia, e um reprocessamento manual duplicaria o e-mail para a lista inteira.

O controle vive num `envios.json` **no repositório do arquivo**, não no warehouse.
Motivo ([D03](../decisoes/D03-onde-guardar-os-dados.md)): o warehouse fica sem backup e
pode ser reconstruído do zero; se o estado de envio estivesse nele, reconstruí-lo faria o
próximo run reenviar todas as competências à lista inteira.

| campo (por competência) | |
|---|---|
| `competencia` | chave |
| `status` | `enviando` → `enviado` |
| `enviado_em` | |
| `sha256_boletim`, `sha256_planilha` | o que foi de fato anexado |

Ordem dentro do flow (cada gravação é um commit com `push`):

```
gera → arquiva → grava `enviando` → envia → grava `enviado`
```

Um `enviando` que **não virou `enviado`** significa que o processo morreu no meio do envio
e ninguém sabe se a lista recebeu. **Não reenvie automaticamente**: gere um alerta e
decida a mão. Duplicar e-mail para uma lista é pior que atrasá-lo.

### Envio do e-mail

**Decisão aberta — provedor.** Critérios, não uma recomendação fechada:

| | |
|---|---|
| Porta 25 | instâncias da Oracle costumam bloqueá-la na saída; use 587/465 ou uma API por HTTPS |
| Entregabilidade | para uma **lista**, sem domínio próprio com SPF/DKIM/DMARC o e-mail tende a cair em spam |
| Candidatos | serviço de e-mail transacional (Resend, Brevo, SendGrid…), o Email Delivery da própria OCI, ou Gmail com senha de app para uma lista muito pequena |
| Limites e planos gratuitos | mudam com o tempo — confirme na hora de escolher |

Regras independentes do provedor:

- **Um envio por destinatário** (ou cópia oculta), nunca todos visíveis em `Para`.
- Cabeçalho `List-Unsubscribe` e um jeito real de sair da lista.
- **Modo de teste:** um parâmetro que envia só para você. O primeiro envio real nunca é o
  primeiro envio.
- **A lista de destinatários é dado pessoal (LGPD):** fica fora do repositório
  ([D07](../decisoes/D07-repositorio-publico.md), [D08](../decisoes/D08-gestao-de-segredos.md)),
  assim como a lista de usuários do Identity.
- Credenciais SMTP/API em segredo, nunca no `.env` versionado.

### O e-mail é o elo mais fraco

Anexos por e-mail não têm controle de acesso: qualquer destinatário pode encaminhá-los. O
login protege o **arquivo online**, não o que já foi enviado. Se o conteúdo for realmente
sensível, o desenho muda: o e-mail leva só um **link** para o arquivo protegido. Os dados
de origem (Novo CAGED) são públicos, então isto só importa se o boletim contiver análise
própria.

---

## Fora de escopo

- Alerta de falha e de silêncio ([F11](F11-observabilidade.md)) — mas veja "Recomendada junto".
- Backup do `.duckdb` ([F13](F13-migracao-nuvem.md)).
- Página de cadastro aberta, pagamento, comentários. O arquivo é somente leitura.

## Critério de aceite

**Bloqueio** (antes de publicar qualquer arquivo real, e depois de cada mudança na
configuração). Rode de **fora**, sem cookie:

```bash
curl -sI https://SEU-SITE.netlify.app/                          # nunca 200 — redirect ou 401
curl -sI https://SEU-SITE.netlify.app/2026-06/boletim-202606.pdf  # nunca 200
curl -sI https://SEU-SITE.netlify.app/2026-06/planilha-202606.xlsx # nunca 200
```

1. Os três acima **não devolvem 200**. O passo mais importante: prova que a função
   intercepta arquivos estáticos.
2. Usuário convidado **com** papel `leitor`: entra e baixa o PDF.
3. Usuário cadastrado **sem** papel: recebe 403.
4. Usuário removido: perde o acesso — meça **quanto tempo** leva e registre no README.
5. **Recuperação de senha** funciona ponta a ponta; o e-mail chega fora do spam.
6. O endereço permanente de um deploy antigo também está bloqueado.
7. A URL do site não aparece em busca nem em `sitemap`.

**Envio:**

8. Modo de teste: o e-mail chega só para você, com os dois anexos corretos.
9. **Rodar o flow duas vezes** para a mesma competência gera **um único** envio.
10. Simular a queda do SMTP durante o envio: fica um `enviando` órfão, **sem reenvio
    automático**, e chega um alerta.
11. FTP sem competência nova: nenhum e-mail, nenhum alerta (estado normal).

**Arquivo:**

12. Clonar o repositório do arquivo do zero e conferir os `sha256` contra o `envios.json`.
13. **Apagar o `.duckdb` e reconstruí-lo:** nenhum e-mail é reenviado.

---

## Registro de implementação (25/09/2026)

Implementada nas duas partes sugeridas em "Ordem de entrega". *(Texto de 25/09, antes do
Netlify e do ensaio real: os registros mais abaixo trazem o que foi de fato executado.)*
A entrega vem desligada por padrão: `ENTREGA_HABILITADA=false`.

### Parte A — arquivo protegido (`arquivo/`)

Esqueleto do repositório privado: `netlify.toml`, edge function `gate.ts` (nega por
padrão; erro interno vira 503) com a regra em `netlify/lib/decisao.ts` (fora de
`edge-functions/`: o Netlify empacota como função todo arquivo daquela pasta e o primeiro
deploy falhou por isso, corrigido em seguida), página de login headless sobre
`@netlify/identity` (convite, recuperação de senha, sair), `robots.txt`, arquivos-isca em
`public/_teste/` e `scripts/verificar-bloqueio.sh`. Passo a passo e tabela de aceite manual
em [arquivo/README.md](../../arquivo/README.md).

Validado na documentação atual (25/09/2026): `getUser()` sem argumentos, devolve `User`
com `roles` ou `null` e nunca lança; registro *somente convite* existe; o Identity está nos
planos gratuitos; o JWT dura 1 h por padrão e, no servidor, `getUser()` **não** renova
sozinho — por isso o `gate.ts` chama `refreshSession()` antes. `@netlify/identity` 2.x exige
Node ≥ 22.12 (`NODE_VERSION` no `netlify.toml`).

Desvios do esboço do doc: (a) a allow-list inclui `/assets/login.js` e `/robots.txt`
(sem o primeiro o login não funciona; o segundo torna o `Disallow` legível); (b) a
"segunda camada" de redirect por papel **não** foi adotada — o esboço bloquearia o próprio
`/login.html` e a edge function já cobre tudo; (c) tentei pular o deploy quando só o `envios.json` muda
(`ignore` no `netlify.toml`), mas ela cancelou o primeiro build: sem cache `$CACHED_COMMIT_REF`
é vazio, some do comando e o `git diff --quiet` devolve 0 ("Canceled build due to no content
change"). A regra foi removida; cada competência gera ~3 deploys, a conferir contra os créditos
do plano.

### Parte B — gerar, arquivar e enviar (`pipeline/flows/`)

| arquivo | papel |
|---|---|
| `boletim.py` | lê o **mart** (não o raw) e gera `boletim-AAAAMM.pdf` (fpdf2) e `planilha-AAAAMM.xlsx` (xlsxwriter) |
| `arquivo.py` | clone/sync do repositório do arquivo, `envios.json`, índice, commit + push |
| `entrega.py` | orquestra `gera → arquiva → enviando → envia → enviado`; SMTP; CLI `teste` / `enviar` |
| `tests/test_entrega.py` | 15 testes com remoto git local e SMTP dublê |

Decisões tomadas na implementação (revisáveis):

- **SMTP genérico** (587 STARTTLS / 465 TLS), sem SDK de provedor: mantém a escolha do
  provedor aberta. A porta 25 não é usada.
- **Só a competência mais recente do mart** é candidata a envio automático. Sem isso, o
  primeiro run com a entrega ligada mandaria 4–6 boletins antigos à lista, e reconstruir o
  warehouse poderia disparar reenvios. Uma antiga só sai pelo comando manual `enviar`.
- **Sem `ENTREGA_HABILITADA=true` nada acontece.** O comando `teste` funciona sem ela.
- **Órfão não bloqueia a competência seguinte**, mas alerta (ntfy, prioridade alta) a cada
  run até alguém resolver — ver "Resolver um envio órfão" no README do arquivo.
- Se o `enviado` não conseguir subir ao remoto, o estado que vale é `enviando` (o clone
  local é descartado no próximo run): erra para o lado de **não** duplicar.
- O corpo do e-mail **não traz números**: os números estão nos anexos, e reler o mart ali
  poderia divergir dos bytes arquivados.
- O boletim declara que só entra o `CAGEDMOV` no prazo (F12 ainda não existe).

### O que foi verificado e o que não foi

| item do aceite | estado |
|---|---|
| 1 (bloqueio, 3 × não-200) | script validado contra servidores simulados (falha no aberto, passa no fechado). **Contra o Netlify real: pendente** |
| 2–7 (login, papel, remoção, recuperação, deploy antigo, busca) | **pendentes** — dependem do Netlify real (tabela em `arquivo/README.md`) |
| 8 (modo de teste) | lógica e anexos testados; **envio a um SMTP real e a caixa de entrada/spam: pendentes** |
| 9 (rodar 2× = 1 envio) | ✅ teste automatizado |
| 10 (queda do SMTP → órfão, sem reenvio, alerta) | ✅ teste automatizado; o alerta ntfy real não foi exercitado |
| 11 (sem competência nova: silêncio) | ✅ teste automatizado |
| 12 (clone do zero confere os sha256) | ✅ teste automatizado (com remoto git local) |
| 13 (apagar o `.duckdb` não reenvia) | ✅ teste automatizado |

Rodar os testes: `docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests --entrypoint python pipeline -m unittest discover -s /app/tests -v`
(a suíte de decisão do bloqueio: `cd arquivo && npm test`).

### Para concluir a fatia *(superado pelo "Fechamento", no fim)*

1. Criar o repositório privado, o site no Netlify e a deploy key; passar no aceite do bloqueio.
2. Escolher o provedor SMTP; preencher `.env` e `secrets/` (deploy key, `destinatarios.txt`).
3. `docker compose up -d --build`; `docker compose exec pipeline python flows/entrega.py teste`.
4. Só então `ENTREGA_HABILITADA=true`. Registrar aqui as datas e os resultados reais.

### Registro de execução real (25/09/2026)

Repositório privado `datastack_netlify` criado; site `observacaged.netlify.app` no Netlify;
Identity em *somente convite*; deploy key própria (só esse repositório) testada pelo pipeline
(clone e sync a partir da imagem nova).

| item | resultado |
|---|---|
| 1 (bloqueio, não-200) | ✅ `verificar-bloqueio.sh` contra o Netlify real: `/`, `/index.html`, `_teste/teste.pdf`, `_teste/teste.xlsx` e `sitemap.xml` redirecionam ao login (302); `login.html` e `robots.txt` = 200. **Prova que a edge function intercepta estáticos** |
| 2 (login com papel `leitor`) | ✅ login, acesso ao arquivo estático e "Sair" funcionando. O PDF-isca não abria por ser malformado (defeito meu); trocado por PDF/XLSX válidos |
| 3 (sem papel → 403) | ✅ `Forbidden` |
| 4 (remoção de acesso) | ✅ **60 min** entre remover o papel (19:23) e o 403 (20:23) = duração do token. Apagar o usuário no Identity também corta o acesso |
| 5 (recuperação de senha) | ✅ e-mail fora do spam; formulário e redefinição funcionaram |
| 6 (deploy antigo) | ✅ `BLOQUEIO OK` no permalink de um deploy antigo |
| 7 (busca/sitemap) | ✅ `Disallow: /`, `noindex`, `sitemap.xml` bloqueado |
| 8 (modo de teste) | ✅ SMTP do Resend com o domínio próprio verificado (`boletim.obsnss.space`): SPF, DKIM e DMARC = `pass`, os dois anexos chegaram, Gmail na caixa de entrada. **Outlook classificou como spam** (SCL 5, domínio novo): ver "Pendências" |

**Três defeitos meus que só apareceram no Netlify real** (os testes locais não os pegavam):

1. `decisao.ts` dentro de `netlify/edge-functions/`: o Netlify empacota todo arquivo daquela
   pasta como função e exige `export default`. O 1º deploy falhou. Movido para `netlify/lib/`.
2. Regra `ignore` no `netlify.toml`: cancelou o build ("no content change"). Sem cache,
   `$CACHED_COMMIT_REF` é vazio, some do comando e o `git diff --quiet` devolve 0. Removida.
3. O bloqueio negava por padrão **a própria API do Identity** (`/.netlify/identity/*`), então
   o login chamava `/token`, era redirecionado ao HTML do login e nunca completava (a tela só
   piscava). Liberado esse prefixo, e só ele, com testes de escape por `..` e `%2e%2e`.

Lição registrada: o teste de aceite do bloqueio (item 1) só olha o lado de quem **não** tem
login. Um bloqueio "fechado demais" passa nele; só o login real revela.

**Parte A concluída:** o bloqueio está aceito no Netlify real (itens 1 a 7).

### Pendências da Parte B
- **Caixa `contato@obsnss.space` (Umbler):** o MX aponta certo, mas o servidor da Umbler
  responde `550 5.7.1 Relaying denied` (não reconhece o domínio). Pendente no painel deles.
  Enquanto isso, `EMAIL_SAIR_DA_LISTA` e `EMAIL_RESPONDER_PARA` ficam com um endereço pessoal.
- **Outlook/Hotmail:** o 1º e-mail caiu em spam apesar de SPF/DKIM/DMARC `pass` (reputação de
  domínio novo). Avisar os destinatários para adicionarem o remetente aos contatos.
- **Ensaio de envio real** (só o dono na lista) e liberação para a lista de verdade.

### Domínio próprio e DNS (26/09/2026)

- **Arquivo em `https://caged.obsnss.space`** (CNAME `caged` → `observacaged.netlify.app`, "somente
  DNS" na Cloudflare, para o Netlify emitir o certificado). Let's Encrypt válido; o Identity responde
  (200) e o bloqueio passa (`BLOQUEIO OK`, incluindo `_teste/teste.pdf`). A sessão de login é por
  endereço: no domínio novo é preciso entrar de novo. Os endereços `*.netlify.app` (o do site e os de
  deploys antigos) continuam existindo e continuam bloqueados.
- **DNS migrado do GoDaddy para a Cloudflare** (só o registro do domínio ficou no GoDaddy). Antes de
  trocar os nameservers, os quatro registros do Resend/DMARC foram comparados byte a byte nos
  nameservers da Cloudflare; depois da troca continuaram resolvendo nos três resolvedores públicos e o
  boletim seguiu autenticando. Lição: os CNAMEs do Resend têm de ficar em "somente DNS".
- **Caixa `contato@obsnss.space`:** a Umbler foi abandonada (recusava o domínio: `550 Relaying denied`
  na entrada e `554 obsnss.space is blocked` na saída). Passou a ser um **encaminhamento do Email Routing
  da Cloudflare para o Gmail** (só recebe; serve ao `Reply-To` e ao "sair da lista"). Verificado: o MX
  da Cloudflare aceita `contato@` (250) e recusa endereço inexistente (550); um e-mail de teste chegou
  com SPF, DKIM, DMARC e ARC = `pass` (caiu em spam no Gmail por ser texto sem sentido de um domínio
  novo; resolve-se com um filtro "nunca enviar para spam" para `contato@`).

### Ensaio de envio real (26/09/2026)

`docker compose exec pipeline python flows/entrega.py enviar 202607`, com só o dono do projeto em
`destinatarios.txt` (2 endereços dele). Durou ~18 s: gerou o boletim e a planilha a partir do mart
(já com o histórico 2020–2026), arquivou no repositório privado (3 commits do pipeline: `arquivo` →
`enviando` → `enviado`), enviou um e-mail por endereço e o Netlify publicou.

| item | resultado |
|---|---|
| 8 (envio) | ✅ 2 de 2 enviados, 0 recusados. Chegaram nas duas caixas, com os dois anexos abrindo, gráfico de 12 meses, comparação com o mesmo mês do ano anterior, link do arquivo e `Reply-To` para `contato@obsnss.space` (confirmado pelo usuário) |
| 9 (rodar 2× = 1 envio) | ✅ a 2ª execução respondeu `ja_enviado`, sem commit novo e sem e-mail |
| 12 (clone do zero × `sha256`) | ✅ boletim e planilha conferem com o `envios.json` |
| bloqueio com o arquivo real | ✅ `BLOQUEIO OK` incluindo `/2026-07/boletim-202607.pdf`, `planilha-202607.xlsx` e `index.html`; logado, o índice lista julho/2026 e os arquivos abrem |
| LGPD | ✅ nenhum endereço de e-mail em nenhum arquivo do repositório do arquivo (o `envios.json` guarda só contagens) |
| 10 (queda do SMTP → órfão, sem reenvio, alerta) | coberto por teste automatizado; **não** foi simulado com o SMTP real |
| 11 (sem competência nova: silêncio) | coberto por teste automatizado; a confirmação real virá nos próximos runs diários |
| 13 (apagar o `.duckdb` não reenvia) | coberto por teste automatizado; **não** foi feito com o warehouse real |

Nota: o teste de bloqueio (`verificar-bloqueio.sh`) só prova que o caminho **não é público**; o gate
também responde 302 para um caminho inexistente. Que o arquivo foi de fato publicado só se confirma
logado.

### Fechamento

**Decisão (26/09/2026): o ensaio vale como o envio de `202607`.** A lista real recebe a partir da
próxima competência (`202608`, quando o PDET publicar). Nada de `202607` será reenviado.

Estado em produção: `ENTREGA_HABILITADA` continua desligada até o usuário ligá-la. Com ela ligada e
`202607` já `enviado`, o flow diário não faz nada até a 202608 sair (silêncio, sem alerta).

**Pendências operacionais, todas do usuário (envolvem segredos e pessoas):**

1. Trocar `secrets/destinatarios.txt` pela lista real (um e-mail por linha) **antes** de ligar a entrega.
2. Ligar `ENTREGA_HABILITADA=true` no `.env` e `docker compose up -d`.
3. Avisar os destinatários para adicionarem `boletim@boletim.obsnss.space` aos contatos: o Outlook
   classificou o primeiro e-mail como spam (SCL 5, reputação de domínio novo, apesar de
   SPF/DKIM/DMARC `pass`).
4. Quem quiser abrir o arquivo online precisa de um convite no Identity com o papel `leitor`
   (o e-mail leva só o link). Cada convite é emitido no painel do Netlify.
5. No Netlify, marcar `caged.obsnss.space` como domínio principal (os e-mails do Identity passam a
   usar o endereço novo).
6. Criar no Gmail o filtro "nunca enviar para spam" para `contato@obsnss.space`.

**Fica aberto, fora do escopo desta fatia:** o `Outlook → spam` depende de reputação, que só melhora
com envio regular; se persistir por semanas, considerar HTML no e-mail e IP dedicado (plano pago do
Resend). Ver também [F12](F12-for-exc-reconciliacao.md): o boletim declara que só entra o `CAGEDMOV`
no prazo.

### Comandos manuais (acrescentado depois do fechamento)

| comando | faz | e-mail | `envios.json` |
|---|---|---|---|
| `entrega.py teste [AAAAMM]` | gera e manda só para `EMAIL_TESTE` | 1, para o dono | não |
| `entrega.py enviar AAAAMM` | gera (ou reaproveita o arquivado), arquiva e envia à lista | sim | sim |
| `entrega.py arquivar AAAAMM..AAAAMM [AAAAMM ...]` | gera e **só arquiva** | **não** | **não** |

O `arquivar` serve para constituir o histórico no arquivo sem avisar ninguém: não sobrescreve o que já
está arquivado (enviado ou não), faz um único commit para o lote (um deploy do Netlify) e o índice o
mostra como "arquivado", não "enviado em". O que ele gera reflete o mart **de hoje**, não o que foi
enviado na época, e por isso não conta como envio; um `enviar` posterior reaproveita esses mesmos bytes.
