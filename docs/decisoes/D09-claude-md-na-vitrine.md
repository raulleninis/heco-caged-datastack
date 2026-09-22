# D09 · O que fazer com o CLAUDE.MD

**Status:** decidida (21/09/2026) · **Bloqueia:** [F14](../fatias/F14-narrativa-do-repositorio.md) · **Urgência:** baixa

## Contexto

`CLAUDE.MD` está na **raiz**, em caixa alta, ao lado do `README.md`. Não está
commitado ainda — então a decisão ainda é livre.

Ele é um bom documento: explica decisões de arquitetura, a restrição de concorrência
do DuckDB, os gotchas do PDET. Boa parte desse conteúdo é **melhor que o README**
em densidade técnica.

Dois problemas:

1. **Duplicação de verdade.** Hoje ele já contradiz o código em dois pontos
   (Postgres removido, defasagem de 1 mês). Dois documentos descrevendo a mesma
   arquitetura **divergem** — é o que já aconteceu.
2. **Exposição não escolhida.** Um recrutador vai abrir. Usar IA no fluxo de trabalho
   é normal hoje; a questão é que a **forma de comunicar isso** deveria ser sua
   decisão deliberada, não um efeito colateral do nome do arquivo.

## Opções

| | |
|---|---|
| **A. Mover para `.claude/CLAUDE.md`** ✅ | Convenção padrão; sai da vitrine; segue funcionando |
| **B. Manter na raiz e assumir** | Honesto e atual. Exige uma seção no README explicando a escolha — vira parte da narrativa em vez de um arquivo solto |
| **C. Não versionar** | ❌ Perde o conteúdo para você mesmo e para colaboração futura |
| **D. Fundir no README + ADRs** ✅✅ | Migra o conteúdo bom para [docs/decisoes/](.) e para a seção "Decisões técnicas" do README; o `CLAUDE.md` fica só com instrução operacional para agente |

## Recomendação

**D, com A como acabamento.**

O raciocínio de arquitetura que está no `CLAUDE.MD` — *por que DuckDB, por que remover
Postgres, qual a restrição de concorrência* — **é exatamente o que um entrevistador
quer ver**, e hoje está escondido num arquivo endereçado a uma IA. Migre esse conteúdo
para onde ele rende: `docs/decisoes/` e o README.

O que sobrar (comandos, convenções, gotchas operacionais) vai para `.claude/CLAUDE.md`.
Assim cada fato tem **um** dono, e a divergência não se reconstrói.

## Nota técnica

O arquivo versionado se chama `CLAUDE.MD` — extensão em **caixa alta**. Em Linux o
carregamento é sensível a caixa; confirme que ele está realmente sendo lido pelo
agente, e não ignorado silenciosamente.

## Decisão

> **Data:** 21/09/2026
> **Escolha:** **D com A como acabamento.**
> **Porquê:** o raciocínio de arquitetura é o que um entrevistador quer ver e hoje está
> escondido num arquivo endereçado a uma IA; cada fato passa a ter um só dono.

**O que muda** *(a implementar na [F14](../fatias/F14-narrativa-do-repositorio.md))*: hoje
o `CLAUDE.MD` está na raiz, **não commitado**, e já contradiz o código em dois pontos.
Depois: o conteúdo de arquitetura migra para `docs/decisoes/` e para o README; o que
sobrar (comandos, convenções, gotchas operacionais) vai para `.claude/CLAUDE.md`.
Verificar antes se a extensão em caixa alta (`.MD`) está sendo lida pelo agente.
