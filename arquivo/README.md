# Arquivo de boletins CAGED (esqueleto do repositório privado)

Esta pasta é o **conteúdo inicial** do repositório privado e separado do arquivo
(fatia F15 e decisão D07, documentadas no repositório principal do projeto, `datastack`).
Ela vive aqui só como fonte versionada do esqueleto — **não há dado nem segredo nela**.
O pipeline (`pipeline/flows/arquivo.py`) adiciona `public/AAAA-MM/*`, `public/index.html`
e `envios.json` nesse repositório e dá `push`; o Netlify publica.

```
netlify.toml                      build e cabeçalhos
package.json                      @netlify/identity, @netlify/edge-functions (versões exatas)
netlify/edge-functions/gate.ts    o bloqueio (nega por padrão, fail closed)
netlify/lib/decisao.ts            a regra de acesso (testável sem o Netlify). FORA de edge-functions/:
                                  o Netlify trata todo arquivo dessa pasta como uma função
src/login.js                      página de login (build -> public/assets/login.js)
public/login.html                 única página pública, além de robots.txt e login.js
public/index.html                 página de teste; o pipeline a troca pelo índice real
public/_teste/                    arquivos-isca: provam que o bloqueio vale para PDF/XLSX
scripts/verificar-bloqueio.sh     teste de aceite, roda de fora, sem cookie
envios.json                       (criado pelo pipeline) estado de envio; fica FORA de public/
```

## Parte 1 — colocar no ar (nada de boletim real antes do aceite)

1. **Repositório privado.** Crie um repositório *privado* vazio e faça o push desta pasta
   como raiz (`git init` dentro de uma cópia dela; não é subdiretório deste repositório).
2. **Netlify**, conectando esse repositório:
   - só a branch de produção faz deploy: desligue *deploy previews* e *branch deploys*
     (`Site configuration → Build & deploy → Branches and deploy contexts`);
   - **ligue a autenticação de dois fatores na conta do Netlify** (é a chave mestra);
   - `Identity → Registration → Invite only`; deixe provedores externos desligados;
   - convide **você mesmo** e dê o papel `leitor` (`Identity → Users → Edit → Roles`).
3. **Chave de escrita do pipeline:** *deploy key* com escrita, restrita a esse único
   repositório (`Settings → Deploy keys → Allow write access`). A chave privada vai em
   `secrets/arquivo_deploy_key` **na VM**, modo `600`, nunca no git (decisão D08 do repositório principal).
4. **Rode o teste de aceite** (abaixo). Só siga para a Parte 2 se passar.

O primeiro deploy contém só o bloqueio e a página de teste. Deploys antigos do Netlify
continuam acessíveis pelo endereço permanente — por isso nenhum arquivo real entra antes
de o bloqueio provadamente funcionar.

## Teste de aceite do bloqueio

De **fora**, sem cookie:

```bash
scripts/verificar-bloqueio.sh https://SEU-SITE.netlify.app
# depois, contra o endereço permanente de um deploy antigo (item 6):
scripts/verificar-bloqueio.sh https://ID-DO-DEPLOY--SEU-SITE.netlify.app
# depois de haver arquivos reais, inclua-os:
scripts/verificar-bloqueio.sh https://SEU-SITE.netlify.app /2026-06/boletim-202606.pdf
```

Passa se nenhum caminho protegido devolver `200` (só redirect para `/login.html`, `401`
ou `403`). Passar no `/_teste/teste.pdf` é o que prova que a função intercepta **arquivos
estáticos**, não só rotas HTML. Repita depois de **qualquer** mudança de configuração.

Itens manuais (não têm como ser scriptados):

| # | Verificação | Resultado (26/09/2026) |
|---|---|---|
| 2 | Convidado **com** `leitor` entra e acessa o PDF de teste | ✅ acesso confirmado; "Sair" derruba a sessão |
| 3 | Cadastrado **sem** papel recebe 403 | ✅ `Forbidden` |
| 4 | Usuário perde o acesso — **quanto tempo leva** | ✅ **60 min** (removido o papel às 19:23, 403 às 20:23): a duração do token |
| 5 | Recuperação de senha ponta a ponta; e-mail **não** cai em spam | ✅ chegou fora do spam; formulário e redefinição funcionaram |
| 6 | Deploy antigo (permalink) também bloqueado | ✅ `verificar-bloqueio.sh` = `BLOQUEIO OK` |
| 7 | O site não aparece em busca nem em `sitemap` | ✅ `Disallow: /`, `noindex` e `sitemap.xml` bloqueado |

Apagar o usuário no Identity também corta o acesso (verificado com um usuário separado do
teste de 60 min).

O JWT dura ~1 h por padrão e mudança de papel só vale no próximo login ou renovação:
**assuma até 1 h** entre remover alguém e o acesso cair.

### O que ainda não está confirmado na documentação do Netlify

- Comportamento de uma edge function que falha **fora** do `try` do `gate.ts` (erro de
  bundle/runtime). Dentro do `try`, qualquer erro vira `503` (nega). O aceite acima é o
  que diz se isso importa na prática.
- Tamanho mínimo de senha e 2FA de usuário do Identity: a documentação consultada não
  fala. O formulário exige 12 caracteres no cliente, o que **não** é uma política do
  servidor. Não presuma 2FA.
- Não há regra `ignore` no `netlify.toml` de propósito. A tentativa de pular o deploy quando
  só o `envios.json` muda cancelou o primeiro build ("no content change"): sem cache,
  `$CACHED_COMMIT_REF` é vazio, some do comando e o `git diff` compara o commit com a
  própria árvore, devolvendo 0. Cada competência gera ~3 deploys (arquivar, `enviando`,
  `enviado`); confira o consumo de créditos do plano após o 1º envio.
- A redirect por papel (`conditions = {Role = ...}`) **não** foi adotada: o esboço do doc
  bloquearia o próprio `/login.html`, e a edge function já cobre tudo.

## Parte 2 — envio (ver README do repositório principal, seção "Entrega")

### Resolver um envio órfão

`enviando` que não virou `enviado` significa que o processo caiu no meio e não se sabe
quem recebeu. O pipeline **não reenvia sozinho** e alerta a cada run. Abra `envios.json`
neste repositório (o pipeline sincroniza com o remoto a cada run, então editar aqui basta):

- Confirmou que todos receberam → troque `"status": "enviando"` por `"enviado"` e preencha `enviado_em`.
- Ninguém recebeu → apague a entrada da competência; o próximo run refaz o envio
  (usando os mesmos arquivos já arquivados).
- Recebeu só parte → `destinatarios_enviados` diz quantos foram antes da queda, na ordem
  de `secrets/destinatarios.txt`. Decida a mão; ao terminar, marque `enviado`.

## Testes locais

```bash
docker run --rm -v "$PWD":/w -w /w node:22-slim sh -c "npm ci && npm test && npm run build"
```
