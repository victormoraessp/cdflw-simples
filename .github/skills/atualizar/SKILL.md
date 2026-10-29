---
name: atualizar
description: 'Atualiza o cdflw: lê os arquivos da Governança, baixa o catálogo do Unity Catalog, monta o grafo, calcula as visões e regenera as referências da skill. Invoque com /atualizar.'
disable-model-invocation: true
user-invocable: true
---

# /atualizar

Rode, a partir da raiz do repositório:

```
.venv\Scripts\python.exe -m cdflw atualizar
```

(Se `.venv` não existir, use `python -m cdflw atualizar`.) O comando pode demorar alguns minutos
quando precisa ligar o cluster para a linhagem; ele imprime o estado do cluster enquanto espera.
Não interrompa. Se a linhagem vier "adiada" por cluster parado, não é erro: siga.

Se o terminal devolver saída vazia, leia `cdflw/saida/_ultimo_comando.txt`.

Quando terminar, mostre **só** isto, copiado da saída, sem reescrever:

1. Quantas regras aprovadas foram lidas e de quais arquivos.
2. Quantas tabelas vieram do catálogo e o id do snapshot; se a linhagem falhou ou foi adiada, a mensagem.
3. Quantas siglas de tabela ficaram "a confirmar" no mapa, e o conteúdo de
   `cdflw/dados/mapa_tabelas.md`. Lembre o usuário de que pode aceitar tudo com
   `python -m cdflw configurar --aceitar-mapa` e ajustar depois no `cdflw/config.toml`.
4. A calibração: quantas aprovadas reprovaram e quais checks dispararam. Se alguma reprovou, mostre as 3
   primeiras de `cdflw/dados/calibracao.json`: isso indica ajuste no validador, não na regra.
5. Os problemas estruturais de `cdflw/dados/detectados.md`, se houver.
6. A linha `cadeias: ... redundancias: ... comunidades: ...` e se o networkx estava disponível. As visões
   estão em `cdflw/dados/visoes/` e o grafo navegável em `cdflw/dados/grafo.html`.
7. Se a saída disser que faltam arquivos do Copilot em `.github`, a lista: o usuário precisa copiá-los.

Não altere nenhum arquivo além do que o comando gera. Não tente consertar o validador.
