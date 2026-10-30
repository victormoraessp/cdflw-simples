# cdflw (versão simples): o que copiar e para onde

O projeto inteiro são **10 arquivos obrigatórios** (5 do Copilot, 4 de código, 1 de configuração)
e alguns opcionais. Não há instalador: você abre cada link abaixo, copia o conteúdo e cola num
arquivo novo com o mesmo caminho dentro do seu repositório (a pasta que o VS Code abre).
Python, venv, Databricks Connect e a extensão Databricks já configurados na máquina são suficientes;
só faltam `pip install openpyxl networkx`.

Links brutos (substitua `<raw>` por `https://raw.githubusercontent.com/victormoraessp/cdflw-simples/main`):

| Copiar para | Link | O que é |
|---|---|---|
| `.github/agents/cdflw.agent.md` | `<raw>/.github/agents/cdflw.agent.md` | o agente `@cdflw` |
| `.github/skills/regras-cadflow/SKILL.md` | `<raw>/.github/skills/regras-cadflow/SKILL.md` | o padrão CadFlow (15 campos) |
| `.github/skills/nova-regra/SKILL.md` | `<raw>/.github/skills/nova-regra/SKILL.md` | `/nova-regra` |
| `.github/skills/refazer/SKILL.md` | `<raw>/.github/skills/refazer/SKILL.md` | `/refazer` |
| `.github/skills/atualizar/SKILL.md` | `<raw>/.github/skills/atualizar/SKILL.md` | `/atualizar` |
| `cdflw/__main__.py` | `<raw>/cdflw/__main__.py` | linha de comando + trilha |
| `cdflw/nucleo.py` | `<raw>/cdflw/nucleo.py` | texto, config, base, validador, gravação, referências |
| `cdflw/catalogo.py` | `<raw>/cdflw/catalogo.py` | Databricks: catálogo, cluster, testes no dado |
| `cdflw/grafo.py` | `<raw>/cdflw/grafo.py` | grafo, visões, grafo.html |
| `cdflw/config.toml` | `<raw>/cdflw/config.toml` | configuração da equipe (edite catálogo/schema ou use `configurar --uc`) |

Recomendados:

| Copiar para | Link | O que é |
|---|---|---|
| `cdflw/README.md` | `<raw>/cdflw/README.md` | como usar, em uma página |
| `cdflw/docs/MANUAL.md` | `<raw>/cdflw/docs/MANUAL.md` | tudo que o agente faz, desfazer/refazer, validador, manutenção |

Opcionais (só para quem vai manter o código):

| Copiar para | Link | O que é |
|---|---|---|
| `cdflw/tests/test_cdflw.py` | `<raw>/cdflw/tests/test_cdflw.py` | os testes (`python -m pytest cdflw/tests -q`); precisam dos exemplos abaixo |
| `cdflw/exemplos/base/Regras de governanca.md` | `<raw>/cdflw/exemplos/base/Regras%20de%20governanca.md` | base sintética |
| `cdflw/exemplos/base/regras_aprovadas_exemplo.md` | `<raw>/cdflw/exemplos/base/regras_aprovadas_exemplo.md` | aprovadas sintéticas |
| `cdflw/exemplos/uc/esquema_exemplo.json` | `<raw>/cdflw/exemplos/uc/esquema_exemplo.json` | snapshot sintético |
| `cdflw/exemplos/uc/linhagem.json` | `<raw>/cdflw/exemplos/uc/linhagem.json` | linhagem sintética |
| `cdflw/exemplos/gerar_export.py` | `<raw>/cdflw/exemplos/gerar_export.py` | gera um export .xlsx sintético |
| `cdflw/docs/TUTORIAL_AGENTE.md` | `<raw>/cdflw/docs/TUTORIAL_AGENTE.md` | como criar outro agente nos mesmos moldes |

Ao colar, salve em UTF-8 (padrão do VS Code). Acrescente ao `.gitignore` da raiz:

```
cdflw/base/
cdflw/dados/
cdflw/saida/
cdflw/config.local.toml
.github/skills/regras-cadflow/references/
.databricks/
.venv/
__pycache__/
```

## Depois de copiar

Na raiz do repositório, no terminal do VS Code:

```
pip install openpyxl networkx
python -m cdflw configurar --uc <catalogo>.<schema>
python -m cdflw instalar
```

Copie os arquivos da Governança para `cdflw\base\`, recarregue a janela do VS Code (Chat > Agent
Customizations: Agents 1, Skills 4) e rode `/atualizar` no chat. Pronto: `/nova-regra`.

Profile e cluster vêm da extensão Databricks conectada na raiz (`.databricks\project.json` ou, no modo
bundle, `.databricks\.databricks.env` + o host correspondente em `~\.databrickscfg`). Sem ela:
`python -m cdflw configurar --local --profile <profile> --cluster-nome "<cluster>"`.

## Atualizar

Copie por cima os arquivos que mudaram (a versão está em `python -m cdflw status`), rode
`python -m cdflw instalar` e, se skill, base ou validador mudaram, `/atualizar`. Compare o
`config.toml` antes de substituir o seu.

## Se algo não funcionar

Peça ao próprio Copilot: "leia cdflw/docs/MANUAL.md e cdflw/README.md e descubra por que
`python -m cdflw status` falha". O código é Python puro, sem dependência exótica, e os testes em
`cdflw/tests` mostram o comportamento esperado de cada comando.
