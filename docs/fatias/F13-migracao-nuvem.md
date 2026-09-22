# F13 · Migração para nuvem

| | |
|---|---|
| **Esforço** | L (1 a 3 dias) |
| **Fase** | produção |
| **Depende de** | [F11](F11-observabilidade.md) |
| **Decisões associadas** | [D02](../decisoes/D02-modelo-de-execucao.md), [D03](../decisoes/D03-onde-guardar-os-dados.md), [D08](../decisoes/D08-gestao-de-segredos.md) |

## O que muda quando sai do servidor caseiro

Hoje o projeto se apoia em três garantias que **desaparecem** na nuvem:

| hoje | na nuvem |
|---|---|
| Tailscale é o firewall — portas 4200 e 8080 só existem na rede privada | IP público: `ports: "4200:4200"` expõe o Prefect **na internet** |
| Disco da máquina é permanente e barato | Disco é custo recorrente; instância efêmera perde tudo |
| Máquina ligada 24/7 sem custo marginal | VM 24/7 é a maior linha da fatura |

### O risco mais imediato

```yaml
prefect-server:
    ports:
      - "4200:4200"
adminer:
    ports:
      - "8080:8080"
```

O Prefect Server **não tem autenticação por padrão**. Numa VM com IP público, isso é
uma UI de orquestração aberta para qualquer um — com poder de disparar flows.
O Adminer é um cliente de banco exposto. Hoje é seguro **só** porque o Tailscale está
na frente. Essa proteção não viaja junto com o `docker-compose.yml`.

> Se a [F02](F02-concluir-migracao-duckdb.md) for feita antes, o Adminer some junto
> com o Postgres e metade deste risco desaparece de graça.

## O dimensionamento real

Vale encarar os números antes de escolher arquitetura:

| | |
|---|---|
| Frequência real de dado novo | **1 vez por mês** |
| Duração de um run | minutos |
| Dado útil por competência | ~1.500 linhas (1 município) |
| Download por competência | ~450 MB |
| Consumidores persistentes | **zero** |

Uma VM 24/7 para rodar minutos por mês é ociosa **99,9% do tempo**. O `cron` diário
existe só porque a data de publicação do PDET é imprevisível — não porque haja
trabalho diário.

Isso empurra fortemente para **execução efêmera agendada** em vez de VM permanente.
A decisão está em [D02](../decisoes/D02-modelo-de-execucao.md); o ponto aqui é que
**a escolha óbvia (levantar a mesma VM na nuvem) é provavelmente a errada**, e é a
que a maioria faz.

### A tensão a resolver

Execução efêmera é barata mas **não combina com Prefect Server**, que é um processo
longo com banco próprio. As saídas:

- **Prefect Cloud** (free tier) + worker efêmero — mantém o Prefect e tira o servidor;
- **abandonar o Prefect** na nuvem e usar o agendador da plataforma (GitHub Actions,
  Cloud Scheduler, cron job do provedor);
- **manter a VM** e aceitar o custo em troca de simplicidade.

Não há resposta única — há trade-off entre custo, simplicidade e o quanto "Prefect"
importa no seu currículo. Vale decidir **explicitamente**, e registrar o porquê:
essa é a pergunta de arquitetura que um entrevistador vai fazer.

## Escopo

1. Decidir o modelo de execução ([D02](../decisoes/D02-modelo-de-execucao.md)).
2. Decidir onde vivem o `.duckdb` e o raw ([D03](../decisoes/D03-onde-guardar-os-dados.md)) —
   com instância efêmera, **o warehouse precisa sobreviver ao fim do run**.
3. Fechar a rede: nenhuma porta pública sem autenticação. Tailscale também roda em
   VM de nuvem — é a migração de menor atrito e mantém o desenho atual válido.
4. Segredos fora do `.env` em disco ([D08](../decisoes/D08-gestao-de-segredos.md)).
5. **Reconstrução testada** do `.duckdb` a partir do FTP. [D03](../decisoes/D03-onde-guardar-os-dados.md)
   decidiu **não** fazer backup: os dados são públicos e regeneráveis. Reconstrução não
   testada não é plano de recuperação.
6. Retenção agressiva do raw ([F07](F07-retencao-e-permissoes.md)) — na nuvem, 2,5 GB
   parados são fatura mensal.

## Critério de aceite

- Destruir a instância e recriá-la **do zero**, a partir do repositório, reconstruindo
  o warehouse a partir do FTP. Se isso não funcionar, não é produção — é um servidor de estimação.
- Nenhuma porta aberta para a internet sem autenticação (verificar de fora da rede).
- Custo mensal medido e **registrado no README** — número real, não estimativa.

## Um contra-argumento honesto

Se o objetivo é **currículo**, "roda na nuvem" vale menos do que o repositório parece
sugerir. O que um recrutador consegue avaliar é o **código e o README**; a VM ele não vê.

Se o tempo for escasso, [F10](F10-camada-analitica.md) e
[F14](F14-narrativa-do-repositorio.md) rendem mais por hora investida do que esta fatia.
A nuvem vale pelo aprendizado e pela frase "está em produção" — não é pouco, mas não é
o primeiro dinheiro a gastar.
