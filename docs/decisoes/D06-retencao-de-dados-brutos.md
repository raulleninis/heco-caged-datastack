# D06 · Política de retenção do raw

**Status:** decidida (21/09/2026) · **Bloqueia:** [F07](../fatias/F07-retencao-e-permissoes.md) · **Urgência:** baixa

## Contexto

`data/raw` tem **2,5 GB** e cresce ~450 MB/mês. Nada é apagado. Desses 450 MB por
competência, o projeto usa **~1.500 linhas** (um município).

## A dependência que complica

`stg_caged_movimentacoes` é **view**, e lê `/data/raw/extraido/*.txt` por glob.
Apagar os `.txt` **quebra a staging** e todo `dbt test` sobre ela.

Isso cria uma ordem obrigatória: materializar a staging como `table`
([F09](../fatias/F09-testes-de-qualidade.md)) **antes** de apagar `.txt`.

## Opções

| | ganho | risco |
|---|---|---|
| **A. Apagar só o `.7z` após extração** ✅ | ~metade do espaço, imediato | nenhum — nada depende do `.7z` |
| **B. Apagar o `.txt` após `dbt run`** ✅✅ | quase tudo | exige staging materializada como tabela |
| **C. Manter N competências** | limita o crescimento | precisa decidir N; mantém o problema menor |
| **D. Arquivar em object storage** | espaço local zero | custo e complexidade por dado regenerável |

## Recomendação

**A agora, B depois da [F09](../fatias/F09-testes-de-qualidade.md).**

O FTP do PDET é a fonte de verdade e continua lá. Guardar 450 MB para extrair 1.500
linhas é pagar aluguel por lixo — e na nuvem esse aluguel aparece na fatura.

**D não se justifica:** é dado público, regenerável, e re-baixar custa minutos.

> Guarde uma **amostra pequena** do recorte do município versionada no repositório —
> mas isso é [F10](../fatias/F10-camada-analitica.md) (para destravar o "clone e rode"),
> não retenção.

## Decisão

> **Data:** 21/09/2026
> **Escolha:** **A agora, B depois da [F09](../fatias/F09-testes-de-qualidade.md).**
> **Porquê:** o FTP do PDET é a fonte de verdade e o dado é regenerável; guardar 450 MB
> por competência para usar ~1.500 linhas é pagar aluguel por lixo. Coerente com a
> [D03](D03-onde-guardar-os-dados.md) (sem backup do warehouse).

**O que muda** *(a implementar na [F07](F07-retencao-e-permissoes.md))*: hoje nada é
apagado (2,5 GB, ~500 MB/mês contando `.7z` e `.txt`). Depois: o `.7z` é apagado após a
extração; o `.txt` só é apagado depois do `dbt run`, e **só quando a staging for
materializada como tabela** (F09), porque hoje ela é uma view que lê os `.txt` por glob.
